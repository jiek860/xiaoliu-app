# -*- coding: utf-8 -*-
"""编程小匠：生成代码 → 代码沙箱运行 → 失败自动修 → 代码审查。

专属工具链：
  1. llm 生成/修复代码（只取代码块）
  2. code_runner 进程级沙箱执行（不直接 exec 用户代码）
  3. 失败后把 stderr 回传给模型，最多再修 2 轮
  4. review 只做语法解析 + 静态审查，不执行代码

不负责的事项：
  - 不负责模型选择与密钥管理（由 llm 模块做）
  - 不负责修改项目文件（由 coder_pro 做）
  - 不负责保证生成代码符合业务规范
  - 不负责沙箱本身的安全边界（由 code_runner 做）
"""
import re

from core.agent_generic import AgentGeneric

try:
    from core.plugin_errors import make_error
except ImportError:  # 独立加载时保持可用
    def make_error(code, message="", **_kwargs):
        return {"error": {"code": code, "message": message}}


class AgentCoder(AgentGeneric):
    """编程小匠：会写、会跑、会按报错修。"""

    NAME = "agent_coder"
    VERSION = "1.1.0"
    ROLE = "编程小匠"
    SYSTEM_PROMPT = "你是编程小匠，只回答编程/技术问题，给最小可用代码。"
    NOT_RESPONSIBLE = ("模型选择", "项目文件修改", "业务规范保证", "沙箱安全边界")
    MAX_FIX_ROUNDS = 2

    TOOLS = [
        {
            "name": "agent_code_solve",
            "method": "solve",
            "desc": "编程小匠：写代码并在沙箱运行，失败自动修",
            "args": {"task": "要实现的功能或要修的 bug",
                     "language": "语言（默认 python）",
                     "tests": "测试代码或校验脚本（可选）"},
            "readonly": False,
            "confirm": True,
            "danger": True,
            "risk": "exec",
            "hints": ["写代码并运行", "代码验证", "帮我跑一下", "修 bug"],
            "contract": {
                "params": {
                    "task": {"type": "string", "required": True},
                    "language": {"type": "string", "required": False},
                    "tests": {"type": "string", "required": False},
                },
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_NOT_AVAILABLE",
                           "PLUGIN_INTERNAL_ERROR"],
                "side_effects": ["network:llm", "process:code_runner"],
                "idempotent": False,
                "timeout_ms": 240000,
                "concurrency_safe": False,
                "description": "生成代码后用 code_runner 沙箱执行，失败最多再修 2 轮",
                "not_responsible": ["改项目文件", "保证业务正确"],
            },
        },
        {
            "name": "agent_code_run",
            "method": "run_code",
            "desc": "编程小匠：在沙箱里运行一段 Python 代码",
            "args": {"code": "要运行的 Python 代码",
                     "timeout": "超时秒数（可选，默认 10）"},
            "readonly": False,
            "confirm": True,
            "danger": True,
            "risk": "exec",
            "hints": ["运行代码", "跑 Python", "沙箱运行"],
            "contract": {
                "params": {
                    "code": {"type": "string", "required": True},
                    "timeout": {"type": "integer", "required": False},
                },
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_NOT_AVAILABLE"],
                "side_effects": ["process:code_runner"],
                "idempotent": False,
                "timeout_ms": 30000,
                "concurrency_safe": False,
                "description": "只执行、不修改文件，输出 stdout/stderr",
                "not_responsible": ["代码生成", "代码审查"],
            },
        },
        {
            "name": "agent_code_review",
            "method": "review",
            "desc": "编程小匠：审查代码（不执行）",
            "args": {"code": "要审查的代码"},
            "readonly": True,
            "hints": ["代码审查", "review 代码", "看看有没有 bug"],
            "contract": {
                "params": {"code": {"type": "string", "required": True}},
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_INTERNAL_ERROR"],
                "side_effects": ["network:llm"],
                "idempotent": False,
                "timeout_ms": 120000,
                "concurrency_safe": True,
                "description": "先用 compile 做语法检查，再让模型列问题；绝不执行代码",
                "not_responsible": ["执行代码", "修改代码"],
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
    def _extract_code(text):
        blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```",
                            str(text or ""), re.S | re.I)
        if blocks:
            return blocks[0].strip()
        return str(text or "").strip()

    def _sandbox(self, code, timeout=None):
        runner = self._module("code_runner")
        if not runner or not hasattr(runner, "run_code"):
            return None
        old_timeout = getattr(runner, "timeout", None)
        try:
            if timeout is not None:
                runner.timeout = int(timeout)
            return runner.run_code(code)
        except Exception as e:
            self._last_error = "沙箱执行失败: %s" % str(e)[:120]
            return {"成功": False, "错误": self._last_error}
        finally:
            if timeout is not None and old_timeout is not None:
                runner.timeout = old_timeout

    @staticmethod
    def _failed(result):
        return not isinstance(result, dict) or result.get("成功") is not True

    @staticmethod
    def _error_of(result):
        if not isinstance(result, dict):
            return "没有返回结果"
        return str(result.get("stderr") or result.get("错误") or "运行失败")[:400]

    def _failure(self, code, message, **extra):
        out = {"ok": False}
        out.update(make_error(code, message, module=self.NAME))
        out.update(extra)
        return out

    # ------------------------------------------------------------------ 工具
    def solve(self, task, language="python", tests=""):
        """生成代码并沙箱运行；失败时带 stderr 再修。"""
        task = str(task or "").strip()
        if not task:
            return self._failure("PLUGIN_MISSING_ARG", "缺少 task（要实现的功能）")
        lang = str(language or "python").strip().lower()
        if lang not in ("python", "py"):
            code, has_llm = self._chat(
                "请用 %s 实现：%s\n只输出代码，不要解释。" % (lang, task))
            if not has_llm:
                return self._failure("PLUGIN_NOT_AVAILABLE", "LLM 不可用")
            return {"ok": True, "任务": task, "语言": lang, "代码": code,
                    "运行成功": None, "说明": "非 Python 不在沙箱执行",
                    "修复记录": [], "llm": True}
        code = ""
        result = {}
        history = []
        fixed = False
        for attempt in range(self.MAX_FIX_ROUNDS + 1):
            if attempt == 0:
                prompt = ("请用 Python 实现：%s\n只输出一个 ```python 代码块，"
                          "不要解释，不要调用网络。") % task
            else:
                prompt = (
                    "上一版代码运行失败。请修复并只输出一个 ```python 代码块。\n"
                    "任务：%s\n上一版代码：\n%s\n错误：\n%s") % (
                        task, code[:4000], history[-1]["错误"])
            reply, has_llm = self._chat(prompt)
            if not has_llm:
                if attempt == 0:
                    return self._failure("PLUGIN_NOT_AVAILABLE", "LLM 不可用")
                break
            code = self._extract_code(reply)
            run_code = code
            if str(tests or "").strip():
                run_code = code + "\n\n" + str(tests)
            result = self._sandbox(run_code)
            if result is None:
                return self._failure("PLUGIN_NOT_AVAILABLE", "code_runner 不可用")
            failed = self._failed(result)
            history.append({
                "轮次": attempt + 1,
                "成功": not failed,
                "错误": "" if not failed else self._error_of(result),
            })
            if not failed:
                fixed = True
                break
        if not code:
            return self._failure("PLUGIN_INTERNAL_ERROR", "没有生成可运行的代码")
        return {
            "ok": True,
            "任务": task,
            "语言": "python",
            "代码": code,
            "运行": result,
            "运行成功": fixed,
            "轮次": len(history),
            "修复记录": history,
            "llm": True,
        }

    def run_code(self, code, timeout=None):
        code = str(code or "")
        if not code.strip():
            return self._failure("PLUGIN_MISSING_ARG", "缺少 code")
        result = self._sandbox(code, timeout)
        if result is None:
            return self._failure("PLUGIN_NOT_AVAILABLE", "code_runner 不可用")
        return {"ok": True, "运行": result,
                "运行成功": not self._failed(result)}

    def review(self, code):
        code = str(code or "")
        if not code.strip():
            return self._failure("PLUGIN_MISSING_ARG", "缺少 code")
        issues = []
        try:
            compile(code, "<agent_code_review>", "exec")
        except SyntaxError as e:
            issues.append("语法错误：第 %s 行 %s" % (
                e.lineno or "?", str(e.msg)[:160]))
        prompt = ("请审查下面这段代码，列出：语法/逻辑/边界/安全/可读性问题，"
                  "并给出最小修改建议。不要重写整段代码。\n代码：\n%s") % code[:5000]
        text, has_llm = self._chat(prompt)
        if not text:
            text = ("语法检查：%s\n静态审查：LLM 不可用，只做了 compile 检查。"
                    % ("有问题" if issues else "通过"))
        return {
            "ok": True,
            "问题": issues,
            "审查": text,
            "llm": has_llm,
        }
