# -*- coding: utf-8 -*-
"""闪退看门狗：主进程死后由**独立子进程**补发日志

为什么需要它
------------
原生崩溃（access violation / 被强杀）时主进程当场就死，Python 一行代码
都跑不了  只能等"下次启动补发"。可如果用户闪退后**再也不打开程序**，
那次日志就永远发不出去。

看门狗就是 Crashpad 的核心思路，但用 Python 轻量实现：
    主程序启动时拉起一个**独立小进程**（同一个 exe，带 --watchdog 参数）
    它只做一件事：等主进程退出 -> 看退出是否干净 -> 不干净就发日志

它不 import PyQt、不 import Trunk，只依赖 stdlib + psutil。

判定"是否干净退出"
------------------
复用 core/auto_report 的 data/.running 标记：
    启动写 .running(pid/时间/版本)
    正常退出删 .running
    看门狗发现父进程没了、.running 还在且 pid 对得上 -> 说明是异常退出
"""
import json
import os
import subprocess
import sys
import time

from core.secret_store import decrypt_config

WATCH_DELAY = 1.0          # 父进程退出后等 1 秒，让日志/标记落盘
POLL_INTERVAL = 2.0


def _data_dir(base):
    return os.path.join(base, "data")


def _running_path(base):
    return os.path.join(_data_dir(base), ".running")


def _config(base):
    try:
        with open(os.path.join(_data_dir(base), "config.json"),
                  encoding="utf-8") as f:
            d = json.load(f)
        return decrypt_config(d) if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _enabled(base):
    """config 里 crash_watchdog 默认 True"""
    return bool(_config(base).get("crash_watchdog", True))


def _read_running(base):
    try:
        with open(_running_path(base), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _remove_running(base):
    try:
        os.remove(_running_path(base))
        return True
    except OSError:
        return False


# ---------------- 进程存活判断 ----------------
def _pid_alive(pid):
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _wait_parent(pid):
    """阻塞到父进程退出"""
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            psutil.Process(int(pid)).wait(timeout=None)
            return True
        except psutil.NoSuchProcess:
            return True
        except (psutil.AccessDenied, ValueError):
            pass          # 拿不到句柄就退回轮询
    while _pid_alive(pid):
        time.sleep(POLL_INTERVAL)
    return True


# ---------------- 主逻辑 ----------------
def _handle_exit(pid, base):
    """父进程退出后调用：判断是否异常退出，是就补发"""
    info = _read_running(base)
    try:
        same_pid = int(info.get("pid", -1)) == int(pid)
    except (TypeError, ValueError):
        same_pid = False
    if not same_pid:
        # 正常退出（.running 已被删），或被另一个实例覆盖  都不报
        return True
    from core import auto_report
    detail = ("主进程 %s 已异常退出（由看门狗在进程死后 %.1f 秒补发）\n"
              "启动时间: %s\n版本: %s"
              % (pid, WATCH_DELAY, info.get("start", "?"),
                 info.get("version", "?")))
    ok, err = auto_report.report(base, "【小6 闪退自动上报（看门狗）】", detail)
    _remove_running(base)          # 报过就清掉，避免下次启动重复补发
    if not ok:
        # 发不出去也把标记留着  让下次启动的 check_previous_crash 再试一次
        try:
            with open(_running_path(base), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False)
        except OSError:
            pass
    return ok


def parse_args(argv):
    """从命令行解析 --watchdog <pid>；不是看门狗模式返回 None"""
    if not argv or "--watchdog" not in argv:
        return None
    i = argv.index("--watchdog")
    if i + 1 >= len(argv):
        return None
    try:
        return int(argv[i + 1])
    except ValueError:
        return None


def main(argv=None):
    """看门狗进程入口。返回进程退出码。"""
    argv = list(sys.argv if argv is None else argv)
    pid = parse_args(argv)
    if pid is None:
        return 2
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _wait_parent(pid)
    time.sleep(WATCH_DELAY)
    ok = _handle_exit(pid, base)
    return 0 if ok else 1


# ---------------- 主程序侧：拉起看门狗 ----------------
def _is_frozen():
    if getattr(sys, "frozen", False):
        return True
    exe = os.path.basename(sys.executable).lower()
    return exe not in ("python.exe", "pythonw.exe", "py.exe", "python", "py")


def _spawn_cmd():
    pid = os.getpid()
    if _is_frozen():
        return [sys.executable, "--watchdog", str(pid)]
    entry = os.path.abspath(sys.argv[0]) if sys.argv else ""
    if not entry or not os.path.exists(entry):
        return None
    return [sys.executable, entry, "--watchdog", str(pid)]


def spawn(base):
    """主程序启动时调用：拉起看门狗（失败不影响程序）"""
    if not _enabled(base):
        return False
    cmd = _spawn_cmd()
    if not cmd:
        return False
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            cmd,
            close_fds=True,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, ValueError):
        return False
