# -*- coding: utf-8 -*-
"""P1-1: 工作流执行器（官方随包模块）

读 data/workflows/*.yaml|yml|json 顺序执行；动作 llm/search/code/wait/set；
支持 {{变量}}、when 条件、on_error/retry、start_async/stop、cron tick 和内置模板。

不负责的事项：
  - 不负责大模型调用细节（由 llm 模块做）
  - 不负责联网搜索实现（由 deep_search 做）
  - 不负责代码沙箱（由 code_runner 做）
  - 不负责用户级定时任务界面（由 scheduler 负责触发）
"""
import json
import os
import re
import threading
import time

from modules.base import BaseModule

try:
    from core.plugin_errors import make_error
except ImportError:  # 独立加载时保持可用
    def make_error(code, message="", **_kwargs):
        return {"error": {"code": code, "message": message}}
class WorkflowCancelled(Exception):
    """工作流被 stop() 取消。"""
class WorkflowError(Exception):
    """单步执行失败。"""

class WorkflowRunner(BaseModule):
    """轻量 YAML 工作流执行器。"""

    NAME = "workflow_runner"
    VERSION = "1.1.0"
    NOT_RESPONSIBLE = ("大模型调用", "联网搜索实现", "代码沙箱", "定时任务 UI")

    BUILTIN_WORKFLOWS = (
        ("daily_digest", "每日摘要", "搜索今日科技要点并生成三条摘要", (
            {"name": "资料", "action": "search", "query": "今天的重要科技新闻"},
            {"name": "摘要", "action": "llm",
             "prompt": "根据下面的资料，用 3 条要点总结今天值得关注的事：\n{{prev}}"},
        )),
        ("research_brief", "研究简报", "围绕一个主题搜索并整理成简报", (
            {"name": "资料", "action": "search", "query": "{{input}}"},
            {"name": "简报", "action": "llm",
             "prompt": "围绕「{{input}}」整理一份简报，包含背景、关键事实、"
                       "争议点与结论。参考资料：\n{{prev}}"},
        )),
        ("code_review", "代码检查", "运行一段 Python 代码并总结结果", (
            {"name": "运行", "action": "code", "code": "{{input}}",
             "on_error": "continue"},
            {"name": "总结", "action": "llm",
             "prompt": "根据下面的运行结果，指出问题并给出修改建议：\n{{prev}}"},
        )),
    )

    TOOLS = [
        {"name": "workflow_list", "method": "list_workflows",
         "desc": "列出可用工作流（含内置模板）", "args": {}, "readonly": True,
         "hints": ["工作流列表", "有哪些工作流", "工作流模板"],
         "contract": {
             "params": {}, "returns": {"type": "array",
                                       "items": {"type": "string"}},
             "errors": ["PLUGIN_INTERNAL_ERROR"],
             "side_effects": ["filesystem_read:data/workflows"],
             "idempotent": True, "concurrency_safe": True, "timeout_ms": 5000,
             "description": "返回工作流 id 列表，内置模板即使还没落盘也会列出",
             "not_responsible": ["执行工作流"]}},
        {"name": "workflow_templates", "method": "ensure_templates",
         "desc": "把内置工作流模板写入 data/workflows",
         "args": {}, "readonly": False, "confirm": True,
         "hints": ["工作流模板", "创建工作流模板", "内置工作流"],
         "contract": {
             "params": {}, "returns": {"type": "object"},
             "errors": ["PLUGIN_INTERNAL_ERROR", "PLUGIN_NOT_AVAILABLE"],
             "side_effects": ["filesystem_write:data/workflows"],
             "idempotent": True, "timeout_ms": 10000, "concurrency_safe": False,
             "description": "只补齐缺失的内置模板，不覆盖用户已改的文件",
             "not_responsible": ["编辑工作流内容"]}},
        {"name": "workflow_run", "method": "run",
         "desc": "运行工作流（后台执行）",
         "args": {"name": "工作流名", "input": "初始输入（可选）"},
         "readonly": False, "confirm": True, "bg": True,
         "hints": ["跑工作流", "执行工作流", "运行工作流"],
         "contract": {
             "params": {"name": {"type": "string", "required": True},
                        "input": {"type": "string", "required": False}},
             "returns": {"type": "object"},
             "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_BAD_INPUT",
                        "PLUGIN_CANCELLED", "PLUGIN_INTERNAL_ERROR"],
             "side_effects": ["filesystem_read:data/workflows", "network:llm",
                              "network:deep_search", "process:code_runner"],
             "idempotent": False, "timeout_ms": 600000,
             "concurrency_safe": False,
             "description": "按步骤执行工作流，支持变量、条件、重试和失败继续",
             "not_responsible": ["模型调用", "代码沙箱"]}},
        {"name": "workflow_status", "method": "status",
         "desc": "查看工作流运行状态与最近结果", "args": {}, "readonly": True,
         "hints": ["工作流状态", "工作流跑完了吗"],
         "contract": {
             "params": {}, "returns": {"type": "object"},
             "errors": ["PLUGIN_INTERNAL_ERROR"], "side_effects": [],
             "idempotent": True, "concurrency_safe": True, "timeout_ms": 5000,
             "description": "返回是否运行中、取消标记、工作流数量和最近一次结果",
             "not_responsible": ["启动工作流"]}},
    ]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.workflow_dir = os.path.join(self.base, "data", "workflows")
        self._running = False
        self._thread = None
        self._cancel = threading.Event()
        self._last_result, self._last_error = {}, ""
        self._last_tick = {}
        os.makedirs(self.workflow_dir, exist_ok=True)
    @staticmethod
    def _safe_name(name):
        raw = str(name or "").strip()
        if not raw or os.path.basename(raw) != raw or raw in (".", ".."):
            return ""
        for ext in (".yaml", ".yml", ".json"):
            if raw.lower().endswith(ext):
                return raw[:-len(ext)].strip()
        return raw.strip()
    def _find_file(self, name):
        return next((p for p in (
            os.path.join(self.workflow_dir, name + ext)
            for ext in (".yaml", ".yml", ".json")) if os.path.exists(p)), "")
    def _parse_simple(self, path):
        """PyYAML 不可用时的极简解析：name/schedule 与 steps 常见字段。"""
        out, current = {"steps": []}, None
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\r\n")
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                if text.startswith("- "):
                    if current is not None:
                        out["steps"].append(current)
                    current, text = {}, text[2:]
                    if ":" in text:
                        key, value = text.split(":", 1)
                        current[key.strip()] = value.strip().strip("'\"")
                    continue
                if ":" not in text:
                    continue
                indent = len(line) - len(line.lstrip())
                key, value = text.split(":", 1)
                key, value = key.strip(), value.strip().strip("'\"")
                if key == "steps" and not value: continue  # 表头别覆盖列表
                if current is not None and indent >= 4:
                    current[key] = value
                elif indent <= 2:
                    out[key] = value
        if current is not None:
            out["steps"].append(current)
        return out
    def _normalize(self, data, name):
        if not isinstance(data, dict): return None
        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            self._last_error = "工作流 %s 没有 steps" % name
            return None
        clean = []
        for i, step in enumerate(steps):
            step = {"prompt": step} if isinstance(step, str) else step
            if not isinstance(step, dict):
                self._last_error = "工作流 %s 第 %d 步不是字典" % (name, i + 1)
                return None
            step = dict(step)
            extra = step.pop("with", None)
            if isinstance(extra, dict):
                for key, value in extra.items():
                    step.setdefault(key, value)
            step["action"] = step.get("action") or step.get("use") or "llm"
            step.setdefault("name", "步骤%d" % (i + 1))
            clean.append(step)
        return {"name": str(data.get("name") or name),
                "title": str(data.get("title") or data.get("name") or name),
                "schedule": data.get("schedule"), "steps": clean}
    def load(self, name):
        """按 id 读取工作流；找不到返回 None，并在 _last_error 说明原因。"""
        clean = self._safe_name(name)
        if not clean:
            self._last_error = "工作流名不合法: %s" % str(name)[:80]
            return None
        path = self._find_file(clean)
        if path:
            try:
                if path.lower().endswith(".json"):
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                else:
                    try:
                        import yaml
                    except ImportError:
                        data = self._parse_simple(path)
                    else:
                        with open(path, encoding="utf-8") as f:
                            data = yaml.safe_load(f)
                return self._normalize(data, clean)
            except Exception as e:
                self._last_error = "读取工作流 %s 失败: %s" % (clean, str(e)[:120])
                return None
        for bid, title, desc, steps in self.BUILTIN_WORKFLOWS:
            if bid == clean:
                return {"name": bid, "title": title, "desc": desc,
                        "builtin": True, "steps": [dict(s) for s in steps]}
        self._last_error = "工作流不存在: %s" % clean
        return None
    def list_workflows(self):
        try:
            names = {os.path.splitext(f)[0] for f in os.listdir(self.workflow_dir)
                     if f.lower().endswith((".yaml", ".yml", ".json"))}
        except Exception as e:
            self._last_error = "扫描工作流目录失败: %s" % str(e)[:120]
            names = set()
        names.update(item[0] for item in self.BUILTIN_WORKFLOWS)
        return sorted(names)
    def templates(self):
        return [{"name": b, "title": t, "desc": d, "steps": len(s),
                 "builtin": True} for b, t, d, s in self.BUILTIN_WORKFLOWS]
    def ensure_templates(self):
        """只补缺失模板，绝不覆盖用户改过的同名文件。"""
        written, existing, errors = [], [], {}
        try:
            import yaml
        except ImportError:
            yaml = None
        for bid, title, desc, steps in self.BUILTIN_WORKFLOWS:
            if self._find_file(bid):
                existing.append(bid)
                continue
            payload = {"name": bid, "title": title, "desc": desc,
                       "steps": [dict(step) for step in steps]}
            try:
                if yaml is not None:
                    text = yaml.safe_dump(payload, allow_unicode=True,
                                          sort_keys=False)
                    ext = ".yaml"
                else:
                    text = json.dumps(payload, ensure_ascii=False, indent=2)
                    ext = ".json"
                path = os.path.join(self.workflow_dir, bid + ext)
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(path + ".tmp", path)
                written.append(bid)
            except Exception as e:
                errors[bid] = str(e)[:120]
        if errors:
            self._last_error = "部分模板写入失败: %s" % json.dumps(
                errors, ensure_ascii=False)
            return self._failure("PLUGIN_INTERNAL_ERROR",
                                 "部分模板写入失败，请检查 data/workflows 权限",
                                 written=written, existing=existing,
                                 errors=errors)
        return {"ok": True, "written": written, "existing": existing}
    def _render(self, text, context):
        out = str(text if text is not None else "")
        for key in sorted(context, key=lambda x: -len(str(x))):
            value = context[key]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            out = out.replace("{{%s}}" % key, str(value)).replace(
                "{%s}" % key, str(value))
        return out
    def _value(self, expr, context):
        key = str(expr or "").strip().strip("{}").strip()
        return context[key] if key in context else (
            context.get("prev", "") if key == "prev" else "")
    def _eval_when(self, expr, context):
        """安全条件判断，不 eval。空条件视为 True。"""
        text = str(expr or "").strip()
        if not text:
            return True
        for op in (" not contains ", " 不包含 ", " contains ", " 包含 "):
            if op in text:
                left, right = text.split(op, 1)
                right = self._render(right.strip().strip("'\""), context)
                found = str(right) in str(self._value(left, context))
                return found if op.strip() in ("contains", "包含") else not found
        match = re.search(r"(^|[^<>=!])(==|!=|>=|<=|>|<)([^=]|$)", text)
        if match:
            op = match.group(2)
            left = self._value(text[:match.start(2)].strip(), context)
            right = self._render(
                text[match.end(2):].strip().strip("'\""), context)
            if op == "==":
                return str(left) == str(right)
            if op == "!=":
                return str(left) != str(right)
            try:
                left, right = float(left), float(right)
            except (TypeError, ValueError):
                return False
            return {">": left > right, "<": left < right,
                    ">=": left >= right, "<=": left <= right}[op]
        value = self._value(text, context)
        if isinstance(value, str) and value.strip().lower() in (
                "", "false", "0", "no", "none", "否"):
            return False
        return bool(value)
    def _module(self, name):
        module = self.trunk.modules.get(name) if self.trunk else None
        if not module and self.trunk and hasattr(self.trunk, "call"):
            self.trunk.call(name, "__no__")
            module = self.trunk.modules.get(name)
        return module
    @staticmethod
    def _result_failed(result):
        if not isinstance(result, dict):
            return False
        return (result.get("ok") is False or result.get("成功") is False
                or bool(result.get("error")))
    @staticmethod
    def _result_reason(result):
        if not isinstance(result, dict):
            return "步骤返回失败"
        err = result.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        return str(err or result.get("stderr") or "步骤返回失败")[:300]
    def _run_step(self, action, step, context):
        if self._cancel.is_set():
            raise WorkflowCancelled("工作流已取消")
        action = str(action or "llm").lower()
        if action == "set":
            return self._render(step.get("value", ""), context)
        if action == "wait":
            try:
                seconds = max(0.0, min(float(
                    step.get("seconds", 0) or 0), 3600.0))
            except (TypeError, ValueError):
                seconds = 0.0
            if self._cancel.wait(seconds):
                raise WorkflowCancelled("等待时被停止")
            return "waited"
        if action == "llm":
            llm = self._module("llm")
            if not llm or not hasattr(llm, "chat"):
                raise WorkflowError("llm 模块不可用")
            prompt = self._render(step.get("prompt", ""), context)
            if not prompt.strip():
                raise WorkflowError("llm 步骤缺少 prompt")
            reply = llm.chat(prompt)
            if reply is None:
                raise WorkflowError("llm 没有返回内容")
            return reply
        if action == "search":
            search = self._module("deep_search")
            if not search or not hasattr(search, "search"):
                raise WorkflowError("deep_search 模块不可用")
            query = self._render(step.get("query", ""), context)
            if not query.strip():
                raise WorkflowError("search 步骤缺少 query")
            return search.search(query)
        if action == "code":
            runner = self._module("code_runner")
            if not runner or not hasattr(runner, "run_code"):
                raise WorkflowError("code_runner 模块不可用")
            code = self._render(step.get("code", ""), context)
            if not code.strip():
                raise WorkflowError("code 步骤缺少 code")
            old = getattr(runner, "timeout", None)
            try:
                if step.get("timeout") is not None:
                    runner.timeout = int(step.get("timeout"))
                result = runner.run_code(code)
            finally:
                if step.get("timeout") is not None and old is not None:
                    runner.timeout = old
            if self._result_failed(result):
                raise WorkflowError(self._result_reason(result))
            return result
        raise WorkflowError("未知动作: %s" % action)
    def run(self, name, input=None, context=None):
        """同步执行工作流；stop() 可从另一线程取消。"""
        self._count += 1
        if not self._running:
            self._cancel.clear()
        self._running = True
        started = time.time()
        workflow = self.load(name)
        if not workflow:
            self._running = False
            return self._failure("PLUGIN_BAD_INPUT",
                                 self._last_error or ("工作流不存在: %s" % name))
        ctx = dict(context) if isinstance(context, dict) else {}
        ctx["input"] = str(input) if input is not None else ctx.get("input", "")
        ctx.setdefault("prev", "")
        results, failed_step = [], ""
        try:
            for index, step in enumerate(workflow["steps"]):
                if self._cancel.is_set():
                    raise WorkflowCancelled("工作流已取消")
                step_name = str(step.get("name") or ("步骤%d" % (index + 1)))
                action = str(step.get("action") or "llm")
                if not self._eval_when(step.get("when", ""), ctx):
                    results.append({"step": step_name, "action": action,
                                    "skipped": True})
                    ctx[step_name] = ctx["prev"] = ""
                    continue
                try:
                    retries = max(0, min(int(step.get("retry", 0)), 5))
                except (TypeError, ValueError):
                    retries = 0
                attempts, result, error = 0, None, ""
                for attempt in range(retries + 1):
                    attempts = attempt + 1
                    try:
                        result = self._run_step(action, step, ctx)
                        if self._result_failed(result):
                            raise WorkflowError(self._result_reason(result))
                        error = ""
                        break
                    except WorkflowCancelled:
                        raise
                    except Exception as e:
                        error = str(e)[:300]
                        if attempt < retries and self._cancel.wait(
                                min(2.0, 0.5 * attempts)):
                            raise WorkflowCancelled(
                                "重试等待时被停止") from None
                row = {"step": step_name, "action": action, "attempts": attempts}
                row["result"] = result
                if error:
                    row.update({"ok": False, "error": error})
                    row.pop("result", None)
                results.append(row)
                ctx[step_name] = ctx["prev"] = result if not error else {
                    "ok": False, "error": error}
                if error:
                    failed_step = step_name
                    if str(step.get("on_error") or "stop").lower() not in (
                            "continue", "skip", "忽略"):
                        return self._finish_failure(
                            workflow, ctx, results, failed_step, error,
                            "PLUGIN_INTERNAL_ERROR", started)
                    continue
            out = {"ok": True, "workflow": workflow.get("name") or name,
                   "steps": len(workflow["steps"]), "results": results,
                   "context": ctx, "elapsed": round(time.time() - started, 2)}
            self._last_result = out
            self._last_error = ""
            self._add_history("工作流 %s: %d 步完成" % (
                workflow.get("name") or name, len(results)))
            return out
        except WorkflowCancelled:
            return self._finish_failure(
                workflow, ctx, results, failed_step, "工作流已取消",
                "PLUGIN_CANCELLED", started, cancelled=True)
        except Exception as e:
            return self._finish_failure(
                workflow, ctx, results, failed_step, str(e)[:300],
                "PLUGIN_INTERNAL_ERROR", started)
        finally:
            self._running = False
    def _finish_failure(self, workflow, ctx, results, failed_step,
                        error, code, started, cancelled=False):
        self._last_error = error
        out = self._failure(code, error, workflow=workflow.get("name"),
                            failed_step=failed_step, results=results,
                            context=ctx, elapsed=round(time.time() - started, 2))
        if cancelled:
            out["cancelled"] = True
        self._last_result = out
        self._add_history("工作流 %s: 失败 - %s" % (
            workflow.get("name") or "", error))
        return out
    def start(self, name=None, context=None):
        base = super().start()
        if not base.get("ok"):
            return base
        self._cancel.clear()
        templates = self.ensure_templates()
        result = {"ok": True, "stage": base.get("stage"),
                  "templates": templates.get("written", [])}
        if not name:
            result["workflows"] = self.list_workflows()
            return result
        started = self.start_async(name, context)
        if not started.get("ok"):
            return started
        result["started"] = name
        return result
    def start_async(self, name, context=None):
        if self._running and self._thread and self._thread.is_alive():
            return self._failure("PLUGIN_BUSY", "工作流正在运行，稍后再试")
        self._cancel.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._background_run, args=(name, context),
            daemon=True, name="workflow-runner")
        self._thread.start()
        return {"ok": True, "started": name, "running": True}
    def _background_run(self, name, context):
        try:
            self.run(name, context=context)
        finally:
            self._running = False
    def stop(self):
        self._cancel.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        result = super().stop()
        result["cancelled"] = True
        return result
    def _on_start(self):
        os.makedirs(self.workflow_dir, exist_ok=True)
        self._cancel.clear()
    def _on_stop(self):
        self._cancel.set()
    def status(self):
        last = self._last_result if isinstance(self._last_result, dict) else {}
        return {
            "ok": True, "running": bool(self._running),
            "cancel_requested": self._cancel.is_set(),
            "workflows": len(self.list_workflows()),
            "last": {
                "workflow": last.get("workflow") or last.get("started") or "",
                "ok": last.get("ok"),
                "cancelled": bool(last.get("cancelled")),
                "failed_step": last.get("failed_step") or "",
                "results": (last.get("results") or [])[-5:],
                "error": self._last_error},
            "lifecycle": super().health()}
    def health(self):
        info = super().health()
        info.update({
            "模块": self.NAME, "工作流": len(self.list_workflows()),
            "运行中": bool(self._running), "取消标记": self._cancel.is_set(),
            "last_ok": self._last_result.get("ok") if isinstance(
                self._last_result, dict) else None,
            "last_error": self._last_error[:200]})
        return info
    @staticmethod
    def _cron_field(field, value, low, high):
        for part in str(field).split(","):
            part = part.strip()
            step = 1
            if "/" in part:
                part, _, raw_step = part.partition("/")
                step = max(1, int(raw_step)) if raw_step.isdigit() else 1
            try:
                if part == "*":
                    start, end = low, high
                elif "-" in part:
                    start, end = [int(x) for x in part.split("-", 1)]
                else:
                    start = end = int(part)
            except ValueError:
                continue
            if start <= value <= end and (value - start) % step == 0:
                return True
        return False
    def _cron_match(self, schedule, now):
        parts = str(schedule or "").split()
        if len(parts) != 5:
            return False
        cron_dow = (now.tm_wday + 1) % 7
        minute, hour, dom, month, dow = parts
        return (self._cron_field(minute, now.tm_min, 0, 59)
                and self._cron_field(hour, now.tm_hour, 0, 23)
                and self._cron_field(dom, now.tm_mday, 1, 31)
                and self._cron_field(month, now.tm_mon, 1, 12)
                and (self._cron_field(dow, cron_dow, 0, 6)
                     or (cron_dow == 0 and self._cron_field(dow, 7, 7, 7))))
    def tick(self, now=None):
        """scheduler 调用：把当前分钟到期的 workflow 跑一遍。"""
        if self._running:
            return {"ok": True, "ran": [], "skipped": "busy"}
        stamp = time.strftime("%Y-%m-%d %H:%M", now or time.localtime())
        due = []
        for name in self.list_workflows():
            workflow = self.load(name)
            schedule = workflow.get("schedule") if workflow else None
            if (schedule and self._last_tick.get(name) != stamp
                    and self._cron_match(schedule, now or time.localtime())):
                due.append(name)
        ran, errors = [], {}
        for name in due:
            self._last_tick[name] = stamp
            result = self.run(name)
            if result.get("ok"):
                ran.append(name)
            else:
                errors[name] = result.get("error") or "执行失败"
        return {"ok": not errors, "ran": ran, "due": due, "errors": errors}
    @staticmethod
    def _failure(code, message, **extra):
        return dict({"ok": False}, **make_error(
            code, message, module="workflow_runner"), **extra)
