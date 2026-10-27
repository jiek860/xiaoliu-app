# -*- coding: utf-8 -*-
"""策划专家：把目标拆成可执行步骤，并能落成 workflow_runner 工作流。

专属工具链：
  1. llm 生成结构化计划（JSON：id/title/action/args/depends_on/done_when）
  2. 校验动作必须能被 workflow_runner 执行
  3. plan_to_workflow 写入 data/workflows/*.yaml，可立即后台执行
  4. next_steps 按依赖关系计算“现在能做哪几步”

不负责的事项：
  - 不负责模型选择与密钥管理（由 llm 模块做）
  - 不负责替用户批准执行
  - 不负责具体工具的实现（由 workflow_runner / 各模块做）
  - 不负责项目排期资源管理
"""
import json
import os
import re
import time

from core.agent_generic import AgentGeneric

try:
    from core.plugin_errors import make_error
except ImportError:  # 独立加载时保持可用
    def make_error(code, message="", **_kwargs):
        return {"error": {"code": code, "message": message}}


class AgentPlanner(AgentGeneric):
    """策划专家：输出可执行步骤，并落成工作流。"""

    NAME = "agent_planner"
    VERSION = "1.1.0"
    ROLE = "策划专家"
    SYSTEM_PROMPT = "你是策划专家，擅长拆解目标为可执行步骤，给方案和备选。"
    NOT_RESPONSIBLE = ("模型选择", "用户批准执行", "具体工具实现", "资源排期")
    ALLOWED_ACTIONS = ("search", "llm", "code", "set", "wait")

    TOOLS = [
        {
            "name": "agent_plan",
            "method": "plan",
            "desc": "策划专家：把目标拆成可执行 JSON 步骤",
            "args": {"goal": "要达成的目标",
                     "constraints": "约束/资源/截止时间（可选）"},
            "readonly": True,
            "hints": ["做个计划", "拆解目标", "执行步骤", "方案步骤"],
            "contract": {
                "params": {
                    "goal": {"type": "string", "required": True},
                    "constraints": {"type": "string", "required": False},
                },
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_INTERNAL_ERROR"],
                "side_effects": ["network:llm"],
                "idempotent": False,
                "timeout_ms": 120000,
                "concurrency_safe": True,
                "description": "输出带 id、动作、依赖和验收标准的步骤列表",
                "not_responsible": ["执行步骤", "替用户批准"],
            },
        },
        {
            "name": "agent_plan_workflow",
            "method": "plan_to_workflow",
            "desc": "策划专家：把计划写成 workflow_runner 工作流",
            "args": {"goal": "目标", "name": "工作流名（可选）",
                     "run": "写完后是否立即后台执行（true/false，默认 false）",
                     "overwrite": "同名文件是否覆盖（true/false，默认 false）"},
            "readonly": False,
            "confirm": True,
            "hints": ["计划变工作流", "生成可执行工作流", "自动执行计划"],
            "contract": {
                "params": {
                    "goal": {"type": "string", "required": True},
                    "name": {"type": "string", "required": False},
                    "run": {"type": "boolean", "required": False},
                    "overwrite": {"type": "boolean", "required": False},
                },
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_BAD_INPUT",
                           "PLUGIN_INTERNAL_ERROR"],
                "side_effects": ["filesystem_write:data/workflows",
                                 "network:llm", "network:deep_search",
                                 "process:code_runner"],
                "idempotent": False,
                "timeout_ms": 240000,
                "concurrency_safe": False,
                "description": "生成计划并写成 YAML，可选立即交给 workflow_runner 后台跑",
                "not_responsible": ["保证计划正确", "替用户批准"],
            },
        },
        {
            "name": "agent_plan_next",
            "method": "next_steps",
            "desc": "策划专家：按依赖算出下一步能做什么",
            "args": {"steps": "步骤列表（JSON 字符串）",
                     "done": "已完成的 id，逗号分隔（可选）"},
            "readonly": True,
            "hints": ["下一步做什么", "计划执行到哪", "哪些步骤能做"],
            "contract": {
                "params": {
                    "steps": {"type": "string", "required": True},
                    "done": {"type": "string", "required": False},
                },
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_BAD_INPUT"],
                "side_effects": [],
                "idempotent": True,
                "concurrency_safe": True,
                "timeout_ms": 5000,
                "description": "返回 ready/blocked/remaining 三组步骤 id",
                "not_responsible": ["执行步骤"],
            },
        },
    ]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self._last_error = ""

    # ------------------------------------------------------------------ 基础
    def _module(self, name):
        module = self.trunk.modules.get(name) if self.trunk else None
        if not module and self.trunk and hasattr(self.trunk, "call"):
            self.trunk.call(name, "__no__")
            module = self.trunk.modules.get(name)
        return module

    def _chat(self, prompt):
        llm = self._module("llm")
        if not llm or not hasattr(llm, "chat"):
            return "", False
        try:
            reply = llm.chat([
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": str(prompt)[:5000]},
            ])
            return str(reply or "").strip(), bool(reply)
        except Exception as e:
            self._last_error = "LLM 调用失败: %s" % str(e)[:120]
            return "", False

    @staticmethod
    def _parse_json(text):
        raw = str(text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        return json.loads(raw)

    @staticmethod
    def _truthy(value):
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in ("1", "true", "yes", "y", "是")

    def _fallback_plan(self, goal):
        return [
            {"id": "s1", "title": "明确目标与验收标准",
             "action": "set", "args": {"value": goal},
             "depends_on": [], "done_when": "目标一句话说清"},
            {"id": "s2", "title": "收集资料",
             "action": "search", "args": {"query": goal},
             "depends_on": ["s1"], "done_when": "至少拿到 3 条有效资料"},
            {"id": "s3", "title": "形成方案",
             "action": "llm",
             "args": {"prompt": "基于资料为「%s」给出可执行方案，"
                               "包含步骤、风险和备选。" % goal},
             "depends_on": ["s2"], "done_when": "方案含步骤/风险/备选"},
            {"id": "s4", "title": "人工确认后执行",
             "action": "wait", "args": {"seconds": 0},
             "depends_on": ["s3"], "done_when": "用户确认方案"},
        ]

    def _normalize_plan(self, raw, goal):
        if not isinstance(raw, list) or not raw:
            return None
        steps, seen = [], set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id") or ("s%d" % (index + 1))).strip()
            if not sid or sid in seen:
                sid = "s%d" % (index + 1)
            seen.add(sid)
            action = str(item.get("action") or "llm").lower()
            if action not in self.ALLOWED_ACTIONS:
                action = "llm"
            args = item.get("args")
            if not isinstance(args, dict):
                args = {}
            title = str(item.get("title") or ("步骤%d" % (index + 1))).strip()
            if action == "search" and not args.get("query"):
                args["query"] = title or goal
            if action == "llm" and not args.get("prompt"):
                args["prompt"] = "围绕「%s」完成任务：%s" % (goal, title)
            if action == "code" and not args.get("code"):
                action = "llm"
                args["prompt"] = "为「%s」编写并说明实现代码。" % title
            if action == "set" and not args.get("value"):
                args["value"] = title
            if action == "wait":
                try:
                    args["seconds"] = float(args.get("seconds", 0) or 0)
                except (TypeError, ValueError):
                    args["seconds"] = 0
            depends = item.get("depends_on") or []
            if not isinstance(depends, list):
                depends = [depends]
            steps.append({
                "id": sid,
                "title": title[:80],
                "action": action,
                "args": args,
                "depends_on": [str(d) for d in depends],
                "done_when": str(item.get("done_when") or ""),
            })
        if not steps:
            return None
        valid_ids = {step["id"] for step in steps}
        for step in steps:
            step["depends_on"] = [d for d in step["depends_on"]
                                  if d in valid_ids and d != step["id"]]
        return steps

    # ------------------------------------------------------------------ 工具
    def plan(self, goal, constraints=""):
        goal = str(goal or "").strip()
        constraints = str(constraints or "").strip()
        if not goal:
            return self._failure("PLUGIN_MISSING_ARG", "缺少 goal（要达成的目标）")
        prompt = (
            "目标：%s\n约束：%s\n\n请拆成 3~7 个可执行步骤，只输出 JSON 数组，"
            "不要 markdown。每项格式：\n"
            '{"id":"s1","title":"步骤名","action":"search|llm|code|set|wait",'
            '"args":{},"depends_on":[],"done_when":"验收标准"}\n'
            "要求：步骤要具体；有依赖就写 depends_on；"
            "search 的 args 用 query，llm 用 prompt，code 用 code，"
            "set 用 value，wait 用 seconds。") % (goal, constraints or "无")
        reply, has_llm = self._chat(prompt)
        steps = None
        if reply:
            try:
                steps = self._normalize_plan(self._parse_json(reply), goal)
            except Exception as e:
                self._last_error = "计划 JSON 解析失败: %s" % str(e)[:120]
        if not steps:
            steps = self._fallback_plan(goal)
            has_llm = bool(reply) and has_llm
        return {
            "ok": True,
            "目标": goal,
            "约束": constraints,
            "步骤": steps,
            "llm": has_llm,
            "警告": [] if has_llm else ["LLM 不可用或输出无法解析，使用通用模板"],
        }

    def plan_to_workflow(self, goal, name="", run=False,
                         overwrite=False):
        goal = str(goal or "").strip()
        if not goal:
            return self._failure("PLUGIN_MISSING_ARG", "缺少 goal（目标）")
        planned = self.plan(goal)
        if not planned.get("ok"):
            return planned
        safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(name or "").strip())
        safe = safe.strip("_")[:40]
        if not safe:
            safe = "agent_plan_" + time.strftime("%Y%m%d_%H%M%S")
        steps = self._workflow_steps(planned["步骤"])
        base = getattr(self.trunk, "base", None) if self.trunk else None
        if not base:
            # 不依赖当前工作目录：modules/installed -> modules -> 项目根
            base = os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
        folder = os.path.join(base, "data", "workflows")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, safe + ".yaml")
        if os.path.exists(path) and not self._truthy(overwrite):
            return self._failure(
                "PLUGIN_BAD_INPUT",
                "工作流 %s 已存在；如要覆盖请把 overwrite 设为 true" % safe)
        payload = {
            "name": safe,
            "title": goal[:60],
            "desc": "由策划专家生成",
            "steps": steps,
        }
        try:
            try:
                import yaml
            except ImportError:
                yaml = None
            if yaml is not None:
                text = yaml.safe_dump(payload, allow_unicode=True,
                                      sort_keys=False)
            else:
                path = os.path.join(folder, safe + ".json")
                if os.path.exists(path) and not self._truthy(overwrite):
                    return self._failure(
                        "PLUGIN_BAD_INPUT",
                        "工作流 %s 已存在；如要覆盖请把 overwrite 设为 true" % safe)
                text = json.dumps(payload, ensure_ascii=False, indent=2)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
        except Exception as e:
            self._last_error = "写工作流失败: %s" % str(e)[:120]
            return self._failure("PLUGIN_INTERNAL_ERROR", "工作流写入失败")
        started = False
        if self._truthy(run):
            runner = self._module("workflow_runner")
            if runner and hasattr(runner, "start_async"):
                result = runner.start_async(safe, {"input": goal})
                started = bool(result.get("ok"))
        return {
            "ok": True,
            "目标": goal,
            "工作流": safe,
            "文件": path,
            "步骤": len(steps),
            "已启动": started,
            "计划": planned["步骤"],
        }

    def next_steps(self, steps, done=""):
        if isinstance(steps, str):
            try:
                steps = self._parse_json(steps)
            except Exception as e:
                return self._failure("PLUGIN_BAD_INPUT",
                                     "steps 不是合法 JSON: %s" % str(e)[:100])
        if not isinstance(steps, list):
            return self._failure("PLUGIN_BAD_INPUT", "steps 必须是列表")
        if isinstance(done, str):
            done_set = {x.strip() for x in done.split(",") if x.strip()}
        elif isinstance(done, list):
            done_set = {str(x) for x in done}
        else:
            done_set = set()
        ready, blocked, remaining = [], [], []
        ids = {str(step.get("id")) for step in steps if isinstance(step, dict)}
        for step in steps:
            if not isinstance(step, dict):
                continue
            sid = str(step.get("id") or "")
            if not sid or sid in done_set:
                continue
            depends = step.get("depends_on") or []
            if not isinstance(depends, list):
                depends = [depends]
            depends = [str(d) for d in depends if str(d) in ids]
            if all(dep in done_set for dep in depends):
                ready.append(sid)
            else:
                blocked.append(sid)
            remaining.append(sid)
        return {"ok": True, "可执行": ready, "阻塞": blocked,
                "剩余": remaining, "已完成": sorted(done_set)}

    def _workflow_steps(self, plan_steps):
        """把计划项摊平成 workflow_runner 能读的字段。"""
        id_to_title = {str(step.get("id")): str(step.get("title") or "")
                       for step in plan_steps}
        out = []
        for step in plan_steps:
            action = str(step.get("action") or "llm")
            args = step.get("args") if isinstance(step.get("args"), dict) else {}
            title = str(step.get("title") or "步骤")[:80]
            row = {"name": title, "action": action}
            if action == "search":
                row["query"] = args.get("query") or title
            elif action == "llm":
                row["prompt"] = args.get("prompt") or title
            elif action == "code":
                row["code"] = args.get("code") or ""
            elif action == "set":
                row["value"] = args.get("value") or title
            elif action == "wait":
                row["seconds"] = args.get("seconds", 0)
            depends = step.get("depends_on") or []
            if len(depends) == 1:
                dep = str(depends[0])
                if id_to_title.get(dep):
                    row["when"] = id_to_title[dep]
            out.append(row)
        return out

    @staticmethod
    def _failure(code, message, **extra):
        out = {"ok": False}
        out.update(make_error(code, message, module="agent_planner"))
        out.update(extra)
        return out
