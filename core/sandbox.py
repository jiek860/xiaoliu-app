# -*- coding: utf-8 -*-
"""进程级代码执行沙箱。

边界说明：
- 这是进程级沙箱，不是内核级安全边界；
- 每次执行使用独立临时目录和清理过的环境变量；
- Windows 下用 taskkill /T 清理进程树；
- 需要强隔离时，可切换到 Windows Sandbox / WSL2 / 容器（后续可选）。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import shutil
import subprocess
from core import command_policy
import sys
import tempfile
import threading
import time

_SAFE_ENV_KEYS = (
    "PATH", "Path", "PATHEXT", "SystemRoot", "WINDIR", "TEMP", "TMP",
    "PYTHONIOENCODING", "PYTHONUTF8", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS", "COMSPEC", "SYSTEMDRIVE",
    "HOMEDRIVE", "HOMEPATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
    "NODE_PATH", "NPM_CONFIG_PREFIX", "CARGO_HOME", "RUSTUP_HOME",
    "GOROOT", "GOPATH", "JAVA_HOME", "PLAYWRIGHT_BROWSERS_PATH",
)


def clean_env():
    env = {}
    for k in _SAFE_ENV_KEYS:
        if k in os.environ:
            env[k] = os.environ[k]
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def kill_tree(pid):
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            try:
                import psutil
                p = psutil.Process(pid)
                for c in p.children(recursive=True):
                    try:
                        c.kill()
                    except Exception as e:
                        _x6_swallowed(__name__, e)
                        pass
                p.kill()
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass


def _watch_limits(proc, max_memory_mb, max_cpu_seconds, state, stop):
    """监控内存和 CPU；超限时杀掉整棵进程树。"""
    try:
        import psutil
        p = psutil.Process(proc.pid)
    except Exception:  # 静默是故意的 - psutil 不可用则不做资源监控
        return
    while not stop.is_set():
        try:
            if proc.poll() is not None:
                return
            if max_memory_mb and p.memory_info().rss > max_memory_mb * 1024 * 1024:
                state["oom"] = True
                kill_tree(proc.pid)
                return
            if max_cpu_seconds:
                t = p.cpu_times()
                if (t.user + t.system) > max_cpu_seconds:
                    state["cpu_exceeded"] = True
                    kill_tree(proc.pid)
                    return
        except Exception:  # 静默是故意的 - 进程已退出/权限变化时结束监控
            return
        stop.wait(0.25)


def run_command(cmd, timeout=300, cwd=None, max_output=50000,
                max_memory_mb=1024, max_cpu_seconds=None,
                cancel_event=None, control=None, env=None,
                approval_cb=None):
    """在清理过环境变量的子进程中运行一条测试/lint 命令。

    这不是内核级网络隔离，但会：
    * 清理 API Key / Token / Cookie / 代理等敏感环境变量；
    * 独立监控内存和 CPU；
    * 超时、取消时杀掉整个进程树；
    * 限制输出大小并记录耗时。
    """
    started = time.time()
    state = {"oom": False, "cpu_exceeded": False}
    stop = threading.Event()
    safe_env = clean_env()
    for k, v in (env or {}).items():
        if k not in safe_env and "KEY" not in k.upper() and                 "TOKEN" not in k.upper() and "SECRET" not in k.upper():
            safe_env[str(k)] = str(v)
    safe_env["X6_SANDBOX"] = "1"
    safe_env.setdefault("HTTP_PROXY", "http://127.0.0.1:9")
    safe_env.setdefault("HTTPS_PROXY", "http://127.0.0.1:9")
    safe_env.setdefault("ALL_PROXY", "http://127.0.0.1:9")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    if isinstance(cmd, (list, tuple)):
        argv = [str(x) for x in cmd]
    else:
        # 字符串命令必须满足白名单；真实应用调用方（代码 Agent）
        # 还会在调用本函数前经过 PermissionCenter 和用户确认。
        ok, reason, _token = command_policy.check_command(str(cmd))
        if not ok:
            return {"ok": False, "exit_code": -3, "output": reason,
                    "command": str(cmd), "duration": 0,
                    "timed_out": False, "cancelled": False,
                    "sandboxed": True}
        if approval_cb is not None:
            try:
                if not approval_cb(str(cmd)):
                    return {"ok": False, "exit_code": -3,
                            "output": "命令未获授权", "command": str(cmd),
                            "duration": 0, "timed_out": False,
                            "cancelled": False, "sandboxed": True}
            except Exception as e:
                return {"ok": False, "exit_code": -3,
                        "output": "命令授权检查异常: " + str(e)[:120],
                        "command": str(cmd), "duration": 0,
                        "timed_out": False, "cancelled": False,
                        "sandboxed": True}
        argv, used_shell = command_policy.build_exec_argv(str(cmd))
        if used_shell and approval_cb is None:
            return {"ok": False, "exit_code": -3,
                    "output": "该命令需要 shell 包装，必须提供 approval_cb",
                    "command": str(cmd), "duration": 0,
                    "timed_out": False, "cancelled": False,
                    "sandboxed": True}
    try:
        proc = subprocess.Popen(
            argv, shell=False, cwd=cwd or os.getcwd(), env=safe_env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", creationflags=flags)
    except Exception as e:
        return {"ok": False, "exit_code": -2, "output": str(e)[:2000],
                "command": str(cmd), "duration": 0, "timed_out": False,
                "cancelled": False, "sandboxed": True}
    monitor = threading.Thread(
        target=_watch_limits,
        args=(proc, max_memory_mb, max_cpu_seconds or timeout, state, stop),
        daemon=True, name="command-sandbox-limits")
    monitor.start()
    out = err = ""
    timed_out = cancelled = False
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    kill_tree(proc.pid)
                    try:
                        out, err = proc.communicate(timeout=2)
                    except Exception as e:
                        _x6_swallowed(__name__, e)
                        pass
                    break
                if time.time() - started > max(1, int(timeout)):
                    timed_out = True
                    kill_tree(proc.pid)
                    try:
                        out, err = proc.communicate(timeout=2)
                    except Exception as e:
                        _x6_swallowed(__name__, e)
                        pass
                    break
                if callable(control):
                    control()
    finally:
        stop.set()
    merged = ((out or "") + (("\n[stderr]\n" + err) if err else "")).strip()
    if state["oom"]:
        merged = (merged + "\n[sandbox] 超过内存上限 %dMB，已终止"
                  % max_memory_mb).strip()
    if state["cpu_exceeded"]:
        merged = (merged + "\n[sandbox] 超过 CPU 时间上限，已终止").strip()
    return {
        "ok": (not timed_out and not cancelled and not state["oom"]
               and not state["cpu_exceeded"] and proc.returncode == 0),
        "exit_code": proc.returncode,
        "output": merged[:max_output],
        "command": str(cmd),
        "duration": round(time.time() - started, 2),
        "timed_out": timed_out,
        "cancelled": cancelled,
        "sandboxed": True,
        "oom": state["oom"],
        "cpu_exceeded": state["cpu_exceeded"],
    }


def run_python(code, timeout=10, max_output=50000, cwd=None,
               max_memory_mb=512, max_cpu_seconds=None):
    """在独立临时目录中执行 Python 代码，返回结构化结果。"""
    started = time.time()
    state = {"oom": False, "cpu_exceeded": False}
    stop = threading.Event()
    workdir = tempfile.mkdtemp(prefix="x6sandbox_")
    script = os.path.join(workdir, "main.py")
    try:
        with open(script, "w", encoding="utf-8") as f:
            f.write(str(code or ""))
        proc = subprocess.Popen(
            [sys.executable, "-I", script],
            cwd=cwd or workdir,
            env=clean_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        monitor = threading.Thread(
            target=_watch_limits,
            args=(proc, max_memory_mb, max_cpu_seconds or timeout, state, stop),
            daemon=True, name="sandbox-limits")
        monitor.start()
        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(proc.pid)
            try:
                out, err = proc.communicate(timeout=3)
            except Exception:
                out, err = "", ""
        stop.set()
        out = (out or "")[:max_output]
        err = (err or "")[:max_output]
        if state["oom"]:
            err = (err + "\n[sandbox] 超过内存上限 %dMB，已终止" % max_memory_mb)[:max_output]
        if state["cpu_exceeded"]:
            err = (err + "\n[sandbox] 超过 CPU 时间上限，已终止")[:max_output]
        return {
            "ok": (not timed_out and not state["oom"] and not state["cpu_exceeded"]
                   and proc.returncode == 0),
            "stdout": out,
            "stderr": err,
            "returncode": proc.returncode,
            "timed_out": timed_out,
            "oom": state["oom"],
            "cpu_exceeded": state["cpu_exceeded"],
            "duration": round(time.time() - started, 3),
            "workdir": workdir,
        }
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)[:300],
                "returncode": None, "timed_out": False,
                "duration": round(time.time() - started, 3),
                "workdir": workdir}
    finally:
        stop.set()
        shutil.rmtree(workdir, ignore_errors=True)
