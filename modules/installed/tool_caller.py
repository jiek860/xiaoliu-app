# -*- coding: utf-8 -*-
"""工具调用器 v11.0 - 真Function Calling：LLM输出JSON→自动执行→结果喂回"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import time
from modules.base import BaseModule
from modules.installed.tool_catalog import BUILTIN_TOOLS
from core import security_policy
from core import tool_policy


class ToolCaller(BaseModule):
    NAME = "tool_caller"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.usage_history = []
        # 可用工具清单（每个工具有参数说明）；清单本身在 tool_catalog.py
        self.tools = {k: dict(v) for k, v in BUILTIN_TOOLS.items()}
        # ── 接上能力注册表（core/module_caps.py）──
        # 两个来源：插件模块在签名清单里声明 tools；core 模块在 core/core_caps.py 声明。
        # 空表 = 没接，行为与改动前完全一致；任何异常也不会影响内置工具。
        self._caps_loaded = 0
        try:
            from core import module_caps
            extra = module_caps.load_tools(getattr(self.trunk, "base", None))
            for k, v in (extra or {}).items():
                if k not in self.tools:          # 内置优先，注册表不覆盖它
                    self.tools[k] = v
            self._caps_loaded = len(extra or {})
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        self._merge_mcp_tools()

    def _merge_mcp_tools(self):
        try:
            mc = self.trunk.modules.get("mcp_server")
            if not mc:
                self.trunk.call("mcp_server", "__no__")
                mc = self.trunk.modules.get("mcp_server")
            if mc and hasattr(mc, "list_tools"):
                for t in mc.list_tools().get("工具", []):
                    key = "mcp_" + str(t.get("name", "")).strip()
                    if key and key not in self.tools:
                        self.tools[key] = {
                            "desc": "MCP外部工具-" + str(t.get("desc", "")),
                            "mod": "mcp_server", "method": "call_tool",
                            "args": {"input": "输入"},
                            "mcp_name": t.get("name"),
                            "confirm": True, "risk": "mcp_external",
                        }
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    # 两级筛选的阈值：进 LLM 提示词的候选工具上限。
    # 实测（2026-10-13）：19 个工具时提示词 1213 字符，35 个变 2021（1.7 倍），
    # 100 个变 5855（4.8 倍）。工具越多模型选错率越高，所以先粗筛再决策。
    _MAX_CANDIDATES = 15

    def _candidates(self, query):
        """第一级粗筛：先按模式收窄，再按关键词缩到 ~15 个

        两级：
            模式收窄   core/tool_presets —— 日常/干活/编程，默认"全部"不过滤
            关键词粗筛  hints 匹配（2 字滑窗，解决"整理记忆" vs "整理下记忆"）

        context_builder._TOOL_HINTS 是**第 0 级**（不像要动手就不进 tool_caller）；
        这里是第 1 级。关键词一个都没命中时退回内置工具（通用能力）。
        """
        try:
            from core import tool_presets
            pool = tool_presets.filter_tools(self.tools,
                                             tool_presets.current(self.trunk))
        except Exception:
            pool = self.tools
        try:
            from core import module_caps
            sub = module_caps.shortlist(pool, query, self._MAX_CANDIDATES)
            if sub:
                return dict(sub)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return dict(pool)

    def _llm_decide(self, query, provenance=None):
        """真Function Calling：LLM输出JSON决定用什么工具和参数"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return []
        cand = self._candidates(query)
        tool_desc = "\n".join([
            f'- "{k}": {v["desc"]}，参数: {json.dumps(v["args"], ensure_ascii=False)}'
            for k, v in cand.items()
        ])
        untrusted_rule = ""
        if provenance is not None and getattr(provenance, "untrusted", False):
            from core.untrusted_content import UNTRUSTED_SYSTEM_RULES
            untrusted_rule = UNTRUSTED_SYSTEM_RULES
        prompt = f"""你是工具调用决策器。根据用户问题决定用哪些工具。

可用工具：
{tool_desc}

用户问题：{query[:200]}

{untrusted_rule}

返回JSON格式（不需要工具就返回空数组）：
[{{"tool": "工具名", "args": {{"参数名": "参数值"}}}}]

只返回JSON，不要其他文字："""
        try:
            untrusted_rule = ""
            if provenance is not None and getattr(provenance, "untrusted", False):
                from core.untrusted_content import UNTRUSTED_SYSTEM_RULES
                untrusted_rule = UNTRUSTED_SYSTEM_RULES
            r = llm.chat(prompt).strip()
            # 提取JSON
            if "[" in r:
                r = r[r.index("["):r.rindex("]")+1]
            calls = json.loads(r)
            # 验证工具存在
            valid = []
            for c in calls:
                if isinstance(c, dict) and c.get("tool") in self.tools:
                    valid.append(c)
            return valid[:3]
        except:
            return []

    def _dispatch(self, info, args, query, tool_name="", provenance=None):
        """把参数交给目标方法 —— 按签名决定用 kwargs 还是按位置传

        原来这里写死成：
            arg_val = list(args.values())[0] if args else query
            self.trunk.call(info["mod"], info["method"], arg_val)
        也就是**只传第一个参数值**。于是多参数能力全部残废：
            debate(topic, rounds)              -> rounds 丢
            chat_vote(message, models)         -> models 丢
            export_encrypted(out_path,password)-> 缺必填 password，直接抛异常

        现在：先看声明里的参数名是否都在方法签名里 —— 都在就按 kwargs 传（支持多参数）；
        否则退回"只传第一个值"。
        退回这条是**必需的兼容路径**：现有内置工具里有几个声明名和方法参数名对不上
        （computer 声明 {"action"} 但方法是 try_handle(text)，
         browser 声明 {"action"} 但方法是 run(text)），它们必须继续走老路。
        """
        method = info["method"]
        from core.tool_schema import validate_args
        _ok, _why = validate_args(args, info.get("args") or {})
        if not _ok:
            return {"ok": False, "错误": _why}
        base = getattr(self.trunk, "base", None)
        _safe, _why = tool_policy.validate_args_safety(args, base=base)
        if not _safe:
            return {"ok": False, "错误": _why}
        if provenance is not None and getattr(provenance, "untrusted", False):
            if not tool_policy.untrusted_can_execute(info):
                try:
                    from core.permission_center import get_permission_center
                    get_permission_center(self.trunk).audit.append({
                        "subject": "tool:" + str(tool_name),
                        "decision": "deny", "result": "untrusted_provenance",
                        "reason": "外部内容不能直接触发有副作用的工具",
                        "args_preview": str(args)[:300]})
                except Exception:  # 静默是故意的
                    pass
                return {"ok": False,
                        "错误": "外部内容不能直接触发有副作用的工具；请用户明确确认"}
        # 统一权限中心：所有工具执行前都在这里做最终决策。
        from core.permission_center import get_permission_center
        pc = get_permission_center(self.trunk)
        decision = pc.authorize(tool_name, info=info, args=args)
        if not decision.get("allow"):
            if decision.get("requires_confirm"):
                if not self._confirm_tool(tool_name, args, info):
                    pc.audit.append({"subject": "tool:" + str(tool_name),
                                     "decision": "deny", "result": "cancel",
                                     "reason": "用户取消"})
                    return {"ok": False, "错误": "已取消"}
            else:
                pc.audit.append({"subject": "tool:" + str(tool_name),
                                 "decision": "deny", "result": "blocked",
                                 "reason": decision.get("reason", "")})
                return {"ok": False, "错误": decision.get("reason", "操作被拒绝")}

        # 长任务加 bg 标记 -> 转后台执行，立刻返回
        #
        # 为什么必须这么做：聊天触发时 _dispatch 是被回复流程**同步**调用的
        # （core/pipeline/legacy_reply.py:133、context_builder.py:200），
        # 而自动更新闭环要跑几分钟、任务闭环要派子智能体、学习要联网搜资料 ——
        # 同步跑会把整条回复卡死。
        # 撤按钮之前这些能力走的是 GUI 的 BgWorker（后台线程），所以没这个问题；
        # 撤按钮后聊天成了主要入口，必须在这里补上，否则等于把"后台跑"退化成"卡界面"。
        if info.get("bg") and not info.get("readonly"):
            label = tool_name or ("%s.%s" % (info["mod"], method))
            self._run_bg(info, args, query, label, provenance=provenance)
            return {"ok": True, "已在后台开始": label,
                    "说明": "这个能力比较慢，已转后台执行，你可以继续聊；"
                            "完成后会写进日志（data/logs/trunk.log）"}

        return self._invoke(info, args, query, tool_name)

    def _invoke(self, info, args, query, tool_name=None):
        """真正执行（同步路径与后台路径共用同一份传参逻辑）"""
        r = self._call_module(info, args, query)
        return self._explain_none(info, r, tool_name)

    def _explain_none(self, info, r, tool_name=None):
        """结果若是 None，区分"真没结果"和"被 @safe 吞掉的错误"

        为什么需要：被 @safe 包住的方法出错时返回 None，调用方**无法区分**
        这和"这方法本来就返回空"。实测吃过亏 —— ocr_available() 被多传了一个
        参数，TypeError 变成 None，现象上就是"这功能没反应"，查了很久。

        @safe 那边按函数名/限定名记下最近一次错误（core/safe.py:last_error），
        这里问一句就知道是不是刚出错了。是的话给模型一个明确的失败信息，
        而不是让它以为"没结果"。
        """
        if r is not None:
            return r
        label = tool_name or info.get("method") or "?"
        try:
            from core import safe as _safe
            # 优先用限定名（Todo.stats），避免 stats/run 这类同名方法串台
            m = self.trunk.modules.get(info.get("mod"))
            fn = getattr(m, info.get("method"), None) if m else None
            keys = []
            inner = getattr(fn, "__func__", fn) if fn is not None else None
            q = getattr(inner, "__qualname__", None)
            if q:
                keys.append(q)
            keys.append(info.get("method"))
            err = next((e for e in (_safe.last_error(k) for k in keys if k)), None)
        except Exception:
            err = None
        if not err:
            return r                      # 真没结果，保持原样
        # 翻译成人话 + 下一步（原来是"「x」执行出错：TypeError: ..."，
        # 用户看不懂也不知道该做什么）。技术细节仍附在后面供排查。
        try:
            from core.error_text import describe
            return {"ok": False,
                    "错误": describe(err, subject=label)}
        except Exception:
            return {"ok": False,
                    "错误": "「%s」执行出错：%s" % (label, err)}

    def _call_module(self, info, args, query):
        """按签名决定怎么传参（三条兼容路径见下面注释）"""
        method = info["method"]
        m = self.trunk.modules.get(info["mod"])
        fn = getattr(m, method, None) if m is not None else None
        names, required = [], []
        if fn is not None:
            try:
                import inspect
                ps = list(inspect.signature(fn).parameters.values())
                names = [p.name for p in ps
                         if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
                required = [p.name for p in ps
                            if p.default is p.empty and p.kind in
                            (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
            except Exception:
                names, required = [], []

        # ① 声明了参数且名字都对得上 -> 按 kwargs 传（支持多参数）
        if args and names and all(k in names for k in args):
            return self.trunk.call(info["mod"], method, **args)

        # ② 没声明参数 -> 看方法到底要不要参数，别硬塞
        #    原来这里写的是 `arg_val = list(args.values())[0] if args else query`，
        #    于是零参数的 list_pending() 会被调成 list_pending("")，
        #    直接 TypeError（被 @safe 吞掉就变成静默返回 None）。
        if not args:
            if not required:
                return self.trunk.call(info["mod"], method)      # 零参数方法
            return self.trunk.call(info["mod"], method, query)    # 要吃参数，用整句

        # ③ 声明了参数但名字对不上（如 computer 声明 action / 方法却是 text）
        #    -> 退回"只传第一个值"，这是现有内置工具的兼容路径
        return self.trunk.call(info["mod"], method, list(args.values())[0])

    def _run_bg(self, info, args, query, label, provenance=None):
        """把长任务丢到后台线程，立刻返回

        用 threading 而不是 Qt 的 QThread：tool_caller 是模块，不该依赖 Qt
        （微核约定：模块之间不互相 import，也不该绑死某个 GUI 框架）。
        结果写日志 —— 后台线程不碰任何控件，避免跨线程操作 Qt 对象。
        """
        import threading

        def _work():
            try:
                r = self._invoke(info, args, query, label)
                self.trunk._log("后台能力完成: %s -> %s"
                                % (label, str(r)[:160]))
                # 通知界面（状态栏回调内部自己保证线程安全，失败就算了）
                try:
                    self.trunk._set_status("✅ %s 已完成（详情见日志）" % label)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            except Exception as e:
                self.trunk._log("后台能力失败: %s - %s"
                                % (label, str(e)[:80]), "WARN")

        threading.Thread(target=_work, daemon=True,
                         name="x6cap-%s" % str(label)[:14]).start()

    def _confirm_tool(self, tool_name, args, info=None):
        """需确认的能力：没有确认界面就拒绝，并支持会话/永久授权。"""
        info = info if info is not None else self.tools.get(tool_name, {})
        policy = security_policy.classify(tool_name, info)
        try:
            if not getattr(self.trunk, "confirm_cb", None):
                return bool(policy.get("readonly")
                            and not policy.get("confirm")
                            and not policy.get("danger"))
            detail = self._confirm_detail(tool_name, args)
            action = "执行「%s」" % tool_name
            scope_cb = getattr(self.trunk, "confirm_scope_cb", None)
            if callable(scope_cb):
                scope = scope_cb(action, detail)
                if scope in ("once", "session", "always"):
                    if scope in ("session", "always"):
                        try:
                            from core.permission_center import get_permission_center
                            pc2 = get_permission_center(self.trunk)
                            pc2.approve(
                                tool_name, scope=scope,
                                reason="用户在确认框中选择 %s" % scope,
                                constraints=pc2.suggest_constraints(
                                    tool_name, args))
                        except Exception as e:  # 静默是故意的 - 规则落盘失败不影响本次已确认执行
                            _x6_swallowed(__name__, e, "best-effort fallback")
                    return True
                return False
            return bool(self.trunk.confirm(action, detail))
        except Exception:
            return False

    @staticmethod
    def _confirm_detail(tool_name, args):
        """确认框必须展示真正要执行的内容，不能只给工具名。"""
        try:
            parts = []
            if isinstance(args, dict):
                for k, v in args.items():
                    sv = str(v)
                    if len(sv) > 300:
                        sv = sv[:300] + ""
                    parts.append("%s=%s" % (k, sv))
            detail = ("工具: %s\n参数:\n%s"
                      % (tool_name, "\n".join(parts)))[:1200]
            if tool_name == "fs_edit" and isinstance(args, dict):
                try:
                    import json
                    from core.diff_review import preview_edit
                    spec = args.get("spec")
                    if isinstance(spec, str):
                        spec = json.loads(spec)
                    if isinstance(spec, dict):
                        diff = preview_edit(spec.get("path", ""),
                                            spec.get("old", ""),
                                            spec.get("new", ""))
                        if diff.get("diff"):
                            detail += ("\n\nDiff (+%d/-%d):\n%s"
                                       % (diff.get("added", 0),
                                          diff.get("removed", 0),
                                          diff["diff"][:1800]))
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            return detail[:3500]
        except Exception:
            return str(args)[:1200]

    def _rule_allows(self, rule_id):
        try:
            return bool(self.trunk.rule(rule_id, False))
        except Exception:
            return False

    def _danger_allowed(self, tool_name):
        try:
            return bool(self.trunk.rule("电脑控制.允许命令", False))
        except Exception:
            return False

    def _model_facing_result(self, tool_name, info, result):
        """Mark web/browser/MCP/plugin outputs as untrusted before the LLM sees them."""
        external = (str(tool_name).startswith("mcp_")
                    or (info or {}).get("source") == "plugin"
                    or (info or {}).get("risk") in
                    ("network", "ui_network", "mcp_external", "read_sensitive"))
        if not external or result is None:
            return result
        from core.untrusted_content import wrap_untrusted
        kind = "mcp" if str(tool_name).startswith("mcp_") else (
            "plugin" if (info or {}).get("source") == "plugin" else "web")
        return wrap_untrusted(str(result), source=str(tool_name), kind=kind)

    def call_tools(self, query, provenance=None):
        """真Function Calling流程：LLM决策→执行→结果返回"""
        if provenance is None:
            try:
                from core.untrusted_content import (
                    external_provenance, is_external_tool_result)
                if is_external_tool_result(query):
                    provenance = external_provenance("tool_context", kind="external")
            except Exception:  # 静默是故意的
                pass
        calls = self._llm_decide(query, provenance=provenance)
        if not calls:
            return {"用工具": "无", "回答": "直接聊天"}

        results = []
        # 工具调用日志：tool_call_logger 这个模块登记了却没人调用，
        # 它专门就是干这个的（记工具名/参数/结果/耗时，留最近 50 条）。
        tcl = self.trunk.modules.get("tool_call_logger")
        if tcl is None:
            try:
                self.trunk.call("tool_call_logger", "__no__")
                tcl = self.trunk.modules.get("tool_call_logger")
            except Exception:
                tcl = None

        for call in calls:
            tool_name = call["tool"]
            args = call.get("args", {})
            info = self.tools[tool_name]
            _t0 = time.time()
            try:
                if (provenance is not None
                        and getattr(provenance, "untrusted", False)):
                    raise PermissionError("外部内容不能直接调用 MCP 工具")
                if tool_name.startswith("mcp_"):
                    policy = security_policy.classify(tool_name, info)
                    if getattr(self.trunk, "_remote_tool_locked", False):
                        try:
                            remote_ok = bool(getattr(self.trunk, "_remote_tools_allowed", False)
                                             or (getattr(self.trunk, "config", {}) or {})
                                             .get("bot_allow_tools", False))
                        except Exception:
                            remote_ok = False
                        if not remote_ok:
                            raise PermissionError("远程会话已禁用 MCP 工具")
                    if policy.get("confirm") and not self._confirm_tool(
                            tool_name, args, info):
                        raise PermissionError("用户未确认 MCP 工具调用")
                    r = self.trunk.call(info["mod"], info["method"],
                                        info.get("mcp_name", tool_name), args)
                else:
                    self.trunk.call(info["mod"], "__no__")
                    r = self._dispatch(info, args, query, tool_name, provenance=provenance)
                shown = self._model_facing_result(tool_name, info, r)
                results.append({"工具": tool_name, "参数": args,
                                "结果": str(shown)[:4000], "成功": True})
                self.usage_history.append({"tool": tool_name, "query": query, "ok": True})
                _res = r
            except Exception as e:
                results.append({"工具": tool_name, "参数": args, "结果": str(e)[:60], "成功": False})
                self.usage_history.append({"tool": tool_name, "query": query, "ok": False})
                _res = e
            if tcl is not None:
                try:
                    tcl.log_call(tool_name, args, _res, time.time() - _t0)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass

        return {"用工具": [c["tool"] for c in calls], "结果": results}

    def run(self, query=""):
        if query:
            return self.call_tools(query)
        ok = sum(1 for h in self.usage_history if h["ok"])
        return {"工具数": len(self.tools), "总调用": len(self.usage_history), "成功率": f"{ok/max(len(self.usage_history),1)*100:.0f}%"}

