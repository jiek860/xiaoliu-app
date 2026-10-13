# -*- coding: utf-8 -*-
"""工具调用器 v11.0 - 真Function Calling：LLM输出JSON→自动执行→结果喂回"""
import json
import time
from modules.base import BaseModule


class ToolCaller(BaseModule):
    NAME = "tool_caller"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.usage_history = []
        # 可用工具清单（每个工具有参数说明）
        self.tools = {
            "deep_search": {
                "desc": "联网搜索网页",
                "mod": "deep_search", "method": "search",
                "args": {"query": "搜索关键词"},
            },
            "vector_search": {
                "desc": "搜索历史记忆",
                "mod": "vector_store", "method": "search",
                "args": {"query": "搜索词"},
            },
            "graph_query": {
                "desc": "查询知识图谱",
                "mod": "knowledge_graph", "method": "rag_query",
                "args": {"query": "查询内容"},
            },
            "code_run": {
                "desc": "运行Python代码",
                "mod": "code_runner", "method": "run",
                "args": {"code": "Python代码"},
            },
            "file_read": {
                "desc": "读文件内容",
                "mod": "file_upload", "method": "read",
                "args": {"path": "文件路径"},
            },
            "task_plan": {
                "desc": "规划任务步骤",
                "mod": "task_planner", "method": "run_goal",
                "args": {"goal": "任务目标"},
            },
            "computer": {
                "desc": "控制电脑：打开软件/截屏/系统信息",
                "mod": "computer_controller", "method": "try_handle",
                "args": {"action": "操作"},
            },
            # 浏览器（Playwright，DOM 选择器级，headless）。
            # 入口是 browser.run/1 个文本参数 —— 注意 tool_caller 分发时只传
            # list(args.values())[0]，多参数传不过去，所以这里只声明 1 个参数，
            # 由 browser.try_handle 自己解析（和上面的 computer 同一形状）。
            "browser": {
                "desc": "浏览器：打开网页/读页面文字/点击/输入/截图（DOM级）",
                "mod": "browser", "method": "run",
                "args": {"action": "如：打开 https://example.com 并读取页面文字"},
            },
            # 开发者文件工具。同样只声明 1 个参数（tool_caller 只传第一个），
            # fs_edit 的参数是一段 JSON 文本。
            "fs_read": {
                "desc": "读文件内容（带行号）",
                "mod": "computer_controller", "method": "read_text",
                "args": {"path": "文件路径"},
            },
            "fs_search": {
                "desc": "在项目目录里搜文件内容",
                "mod": "computer_controller", "method": "search_text",
                "args": {"keyword": "关键词或正则"},
            },
            "fs_edit": {
                "desc": "精确替换文件内容（原文须唯一，改前自动备份）",
                "mod": "computer_controller", "method": "edit_text",
                "args": {"spec": 'JSON: {"path":"a.py","old":"原文","new":"新文"}'},
            },
            # UI 元素树：按控件名操作，不依赖坐标（需 uiautomation）
            "ui_find": {
                "desc": "按控件名/类型在窗口里找控件（只定位，不点击）",
                "mod": "computer_controller", "method": "ui_find",
                "args": {"name": "控件名，如：确定"},
            },
            "ui_click": {
                "desc": "按控件名点击按钮/链接（比点坐标可靠）",
                "mod": "computer_controller", "method": "ui_click",
                "args": {"name": "控件名，如：确定"},
            },
            "ui_dump": {
                "desc": "打印某窗口的控件树，用于看清程序界面结构",
                "mod": "computer_controller", "method": "ui_dump",
                "args": {"window": "窗口名，如：记事本"},
            },
            # 命令执行：默认关闭（规则「电脑控制.允许命令」= false），
            # 开启后也只放白名单命令且每条要弹窗确认。列在这里是为了
            # 开启后 LLM 能调用它 —— 防线是"规则 + 确认"，不是把它藏起来。
            "shell": {
                "desc": "执行一条白名单内的命令（默认禁用，需规则开启）",
                "mod": "computer_controller", "method": "shell",
                "args": {"cmd": "如：git status（不允许 && | > 等串联）"},
            },
        }
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
        except Exception:
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
                        }
        except Exception:
            pass

    # 两级筛选的阈值：进 LLM 提示词的候选工具上限。
    # 实测（2026-10-13）：19 个工具时提示词 1213 字符，35 个变 2021（1.7 倍），
    # 100 个变 5855（4.8 倍）。工具越多模型选错率越高，所以先粗筛再决策。
    _MAX_CANDIDATES = 15

    def _candidates(self, query):
        """第一级粗筛：按关键词把候选缩到 ~15 个

        context_builder._TOOL_HINTS 是**第 0 级**（不像要动手就不进 tool_caller）；
        这里是第 1 级。关键词一个都没命中时退回内置工具（通用能力）。
        """
        try:
            from core import module_caps
            sub = module_caps.shortlist(self.tools, query, self._MAX_CANDIDATES)
            if sub:
                return dict(sub)
        except Exception:
            pass
        return dict(self.tools)

    def _llm_decide(self, query):
        """真Function Calling：LLM输出JSON决定用什么工具和参数"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return []
        cand = self._candidates(query)
        tool_desc = "\n".join([
            f'- "{k}": {v["desc"]}，参数: {json.dumps(v["args"], ensure_ascii=False)}'
            for k, v in cand.items()
        ])
        prompt = f"""你是工具调用决策器。根据用户问题决定用哪些工具。

可用工具：
{tool_desc}

用户问题：{query[:200]}

返回JSON格式（不需要工具就返回空数组）：
[{{"tool": "工具名", "args": {{"参数名": "参数值"}}}}]

只返回JSON，不要其他文字："""
        try:
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

    def _dispatch(self, info, args, query, tool_name=""):
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
        # 能力注册表来的声明带 readonly/confirm/danger，先做安全分级
        if info.get("danger") and not self._danger_allowed(tool_name):
            return {"ok": False, "错误": "「%s」是危险操作且未被允许" % tool_name}
        if info.get("confirm") and not self._confirm_tool(tool_name, args):
            return {"ok": False, "错误": "已取消"}

        m = self.trunk.modules.get(info["mod"])
        fn = getattr(m, method, None) if m is not None else None
        names = []
        if fn is not None:
            try:
                import inspect
                names = [p.name for p in inspect.signature(fn).parameters.values()
                         if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
            except Exception:
                names = []
        if args and names and all(k in names for k in args):
            return self.trunk.call(info["mod"], method, **args)
        arg_val = list(args.values())[0] if args else query
        return self.trunk.call(info["mod"], method, arg_val)

    def _confirm_tool(self, tool_name, args):
        """需确认的能力：没有确认界面就拒绝（和 shell 同一条原则）"""
        try:
            if not getattr(self.trunk, "confirm_cb", None):
                # 无界面环境下**只读能力**放行，写操作拒绝
                info = self.tools.get(tool_name, {})
                if info.get("readonly"):
                    return True
                return False
            return bool(self.trunk.confirm("执行「%s」" % tool_name,
                                           str(args)[:150]))
        except Exception:
            return False

    def _danger_allowed(self, tool_name):
        try:
            return bool(self.trunk.rule("电脑控制.允许命令", False))
        except Exception:
            return False

    def call_tools(self, query):
        """真Function Calling流程：LLM决策→执行→结果返回"""
        calls = self._llm_decide(query)
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
                if tool_name.startswith("mcp_"):
                    r = self.trunk.call(info["mod"], info["method"],
                                        info.get("mcp_name", tool_name), args)
                else:
                    self.trunk.call(info["mod"], "__no__")
                    r = self._dispatch(info, args, query, tool_name)
                results.append({"工具": tool_name, "参数": args, "结果": str(r)[:400], "成功": True})
                self.usage_history.append({"tool": tool_name, "query": query, "ok": True})
                _res = r
            except Exception as e:
                results.append({"工具": tool_name, "参数": args, "结果": str(e)[:60], "成功": False})
                self.usage_history.append({"tool": tool_name, "query": query, "ok": False})
                _res = e
            if tcl is not None:
                try:
                    tcl.log_call(tool_name, args, _res, time.time() - _t0)
                except Exception:
                    pass

        return {"用工具": [c["tool"] for c in calls], "结果": results}

    def run(self, query=""):
        if query:
            return self.call_tools(query)
        ok = sum(1 for h in self.usage_history if h["ok"])
        return {"工具数": len(self.tools), "总调用": len(self.usage_history), "成功率": f"{ok/max(len(self.usage_history),1)*100:.0f}%"}

