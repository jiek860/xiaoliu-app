# -*- coding: utf-8 -*-
"""代码 Agent 沙箱命令、测试/lint 探测和执行。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from core.agent_permissions import authorize_agent_action
from core import command_policy
from core.sandbox import run_command as sandbox_command

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class CodeCommandRunnerMixin:
    def _authorize_command(self, cmd, sandboxed=False):
        """命令执行前统一过白名单、权限中心和审计。"""
        ok, reason, token = command_policy.check_command(str(cmd))
        if not ok:
            return False, reason
        action = {
            "type": "shell",
            "risk": "high",
            "args": {"cmd": str(cmd)},
            "reason": "代码 Agent %s命令" % ("沙箱" if sandboxed else ""),
        }
        gate = authorize_agent_action(
            getattr(self, "trunk", None), "code_agent", action,
            title="代码 Agent 请求运行命令", detail=str(cmd))
        try:
            from core.permission_center import get_permission_center
            pc = get_permission_center(getattr(self, "trunk", None))
            pc.audit.append({
                "subject": "code_agent.shell",
                "decision": "allow" if gate.get("allow") else "deny",
                "result": "authorized" if gate.get("allow") else "blocked",
                "reason": str(gate.get("reason", ""))[:200],
                "command_preview": command_policy.command_preview(str(cmd)),
                "command_hash": command_policy.command_hash(str(cmd)),
            })
        except Exception as e:  # 静默是故意的 - 审计失败不改变权限判定
            _x6_swallowed(__name__, e, "write command audit")
        if not gate.get("allow"):
            return False, gate.get("reason", "命令被权限中心拒绝")
        return True, token

    def _run_command(self, cmd, timeout=300, sandboxed=False):
        self._check_control()
        allowed, why = self._authorize_command(cmd, sandboxed=sandboxed)
        if not allowed:
            return {"ok": False, "exit_code": -3, "output": why,
                    "command": str(cmd), "duration": 0,
                    "timed_out": False, "cancelled": False}
        if sandboxed:
            from core.sandbox import run_command as sandbox_command
            r = sandbox_command(
                cmd, timeout=timeout, cwd=self.root,
                cancel_event=self._cancel, control=self._check_control,
                max_memory_mb=1024, max_output=20000,
                approval_cb=lambda _command: True)
            r["ok"] = bool(r.get("ok"))
            r["timed_out"] = bool(r.get("timed_out"))
            return r
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        t0 = time.time()
        try:
            proc = subprocess.Popen(
                command_policy.build_exec_argv(str(cmd))[0],
                shell=False, cwd=self.root, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", env=env, creationflags=flags)
        except Exception as e:
            return {"ok": False, "exit_code": -2, "output": str(e)[:2000],
                    "command": cmd, "duration": 0}
        with self._proc_lock:
            self._active_proc = proc
        out = err = ""
        timed_out = False
        cancelled = False
        try:
            while True:
                try:
                    out, err = proc.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if self._cancel.is_set():
                        cancelled = True
                        self._kill_active_proc()
                        try:
                            out, err = proc.communicate(timeout=2)
                        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                            _x6_swallowed(__name__, e, "best-effort fallback")
                        break
                    if time.time() - t0 > max(1, int(timeout)):
                        timed_out = True
                        self._kill_active_proc()
                        try:
                            out, err = proc.communicate(timeout=2)
                        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                            _x6_swallowed(__name__, e, "best-effort fallback")
                        break
                    self._check_control()
        finally:
            with self._proc_lock:
                if self._active_proc is proc:
                    self._active_proc = None
        merged = ((out or "") + (("\n[stderr]\n" + err) if err else "")).strip()
        return {
            "ok": (not timed_out and not cancelled and proc.returncode == 0),
            "exit_code": proc.returncode,
            "output": merged[:20000],
            "command": cmd,
            "duration": round(time.time() - t0, 2),
            "timed_out": timed_out,
            "cancelled": cancelled,
        }

    def _run_argv(self, argv, timeout=60, cwd=None):
        """无 shell 的参数数组执行，避免分支名/提交信息注入命令。"""
        self._check_control()
        try:
            r = subprocess.run(
                [str(x) for x in argv], cwd=cwd or self.root,
                capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace", shell=False)
            out = ((r.stdout or "") + (("\n[stderr]\n" + r.stderr)
                                      if r.stderr else "")).strip()
            return {"ok": r.returncode == 0, "exit_code": r.returncode,
                    "output": out[:12000], "command": argv}
        except subprocess.TimeoutExpired:
            return {"ok": False, "exit_code": -1, "output": "命令超时",
                    "command": argv}
        except Exception as e:
            return {"ok": False, "exit_code": -2, "output": str(e)[:1000],
                    "command": argv}

    def _exists(self, name):
        return os.path.exists(os.path.join(self.root, name))

    def _read_cfg(self, name):
        try:
            return open(os.path.join(self.root, name), encoding="utf-8",
                        errors="replace").read()
        except OSError:
            return ""

    def detect_test_commands(self):
        cmds = []
        pyproject = self._read_cfg("pyproject.toml")
        has_py_tests = self._exists("tests") or self._exists("pytest.ini") or \
            "pytest" in pyproject or self._exists("tox.ini")
        if has_py_tests:
            cmds.append('"%s" -m pytest -q' % sys.executable)
        pkg = self._read_cfg("package.json")
        if pkg:
            try:
                data = json.loads(pkg)
                if (data.get("scripts") or {}).get("test"):
                    cmds.append("npm test")
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
        if self._exists("Cargo.toml"):
            cmds.append("cargo test")
        if self._exists("go.mod"):
            cmds.append("go test ./...")
        return cmds

    def detect_lint_commands(self):
        cmds = []
        pyproject = self._read_cfg("pyproject.toml")
        has_dot_ruff = (os.path.isdir(self.root)
                        and ".ruff.toml" in os.listdir(self.root))
        if self._exists("ruff.toml") or has_dot_ruff:
            cmds.append('"%s" -m ruff check .' % sys.executable)
        elif "[tool.ruff" in pyproject:
            cmds.append('"%s" -m ruff check .' % sys.executable)
        pkg = self._read_cfg("package.json")
        if pkg:
            try:
                data = json.loads(pkg)
                if (data.get("scripts") or {}).get("lint"):
                    cmds.append("npm run lint")
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
        if self._exists("Cargo.toml"):
            cmds.append("cargo clippy -- -D warnings")
        if self._exists("go.mod"):
            cmds.append("gofmt -l .")
        return cmds

    # 批次 D9：Python 项目的附加静态检查（已装才跑，未装记为 skipped）
    _PY_LINT_EXTRAS = (
        ("ruff", '"%s" -m ruff check --output-format=concise .'),
        ("mypy", '"%s" -m mypy --ignore-missing-imports --show-error-codes .'),
    )

    def _python_project(self):
        for name in ("pyproject.toml", "setup.py", "setup.cfg",
                     "requirements.txt", "pytest.ini", "tox.ini"):
            if self._exists(name):
                return True
        return bool(self._exists("tests"))

    @staticmethod
    def _module_installed(name):
        try:
            import importlib.util
            return importlib.util.find_spec(str(name)) is not None
        except Exception as e:  # 静默是故意的 - 探测失败按未安装处理
            _x6_swallowed(__name__, e, "probe lint module")
            return False

    def run_lint(self, commands=None):
        """跑 lint；批次 D9 起在自动模式追加 ruff/mypy（``code.lint_extra``）。

        shadow（默认）只把附加检查的输出记进结果、不参与 ``ok``，避免历史
        类型问题把每一轮都卡成"未完成"；``on`` 才真正挡完成；``off`` 不跑。
        """
        explicit = bool(commands or getattr(self, "lint_commands", None))
        cmds = list(commands or self.lint_commands or self.detect_lint_commands())
        extras, skipped = [], []
        mode = "off"
        if not explicit:
            try:
                from core.patch_protocol import lint_extra_mode
                mode = lint_extra_mode(getattr(self, "trunk", None))
            except Exception as e:  # 静默是故意的 - 读不到开关就不加检查
                _x6_swallowed(__name__, e, "lint extra mode")
                mode = "off"
            for module, cmd in self._PY_LINT_EXTRAS:
                if mode == "off" or not self._python_project() or \
                        not self._module_installed(module):
                    skipped.append(module)
                    continue
                formatted = cmd % sys.executable
                if formatted not in cmds:
                    extras.append(formatted)
            cmds.extend(extras)
        if not cmds:
            return {"ok": True, "results": [], "skipped": True,
                    "skipped_modules": skipped}
        results = []
        for cmd in cmds:
            self._check_control()
            r = self._run_command(cmd, timeout=180, sandboxed=True)
            item = {"command": cmd, "ok": r["ok"],
                    "exit_code": r["exit_code"],
                    "output": r["output"][:12000]}
            if cmd in extras and mode != "on":
                # shadow：附加检查只记录，不改变任务是否算完成
                item["advisory"] = True
            results.append(item)
        return {"ok": all(x["ok"] for x in results
                          if not x.get("advisory")),
                "results": results, "skipped_modules": skipped}

    def run_tests(self, commands=None, changed_files=None):
        cmds = list(commands or self.test_commands or self.detect_test_commands())
        if changed_files:
            # 批次 46.4：影响面选测（默认 off，关掉就是全量）。
            picked = self._verify_commands(changed_files)
            if picked:
                cmds = picked
        if not cmds:
            return {"ok": True, "results": [], "skipped": True,
                    "reason": "未发现测试命令；请配置或添加 pytest/npm/cargo/go 测试"}
        results = []
        for cmd in cmds:
            self._check_control()
            r = self._run_command(cmd, timeout=300, sandboxed=True)
            results.append({
                "command": cmd, "ok": r["ok"],
                "exit_code": r["exit_code"],
                "output": r["output"][:16000],
                "failures": self.parse_test_failures(r["output"]),
                "duration": r.get("duration", 0),
                "timed_out": r.get("timed_out", False),
            })
        return {"ok": all(x["ok"] for x in results), "results": results}

    def _verify_commands(self, changed_files):
        """按改动文件选 pytest 目标；任何失败都返回空 = 退回全量。"""
        try:
            from core.code.verify import selected_commands
            return selected_commands(self, changed_files) or []
        except Exception as e:  # 静默是故意的 - 选测失败不能挡住测试
            _x6_swallowed(__name__, e, "verify selected commands")
            return []

    @staticmethod
    def parse_test_failures(output):
        text = str(output or "")
        failures = []
        for m in re.finditer(
                r"FAILED\s+([^\s:]+)::([^\s]+)(?:\s+-\s+(.*))?", text):
            failures.append({"file": m.group(1), "test": m.group(2),
                             "line": 0, "message": (m.group(3) or "")[:300]})
        for m in re.finditer(
                r'File "([^"]+)", line (\d+)(?:, in ([^\n]+))?', text):
            failures.append({"file": m.group(1), "line": int(m.group(2)),
                             "test": m.group(3) or "", "message": ""})
        seen, out = set(), []
        for f in failures:
            key = (f["file"], f["line"], f["test"])
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out[:30]
