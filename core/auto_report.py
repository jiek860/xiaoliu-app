# -*- coding: utf-8 -*-
"""崩溃 / 闪退自动上报（尽力而为）

两条路
------
A. Python 层异常（含 Qt 槽里抛的）
     sys.excepthook / threading.excepthook 里**立刻**发一份摘要，
     带 4 秒超时（发不出去就算了，绝不卡住退出）。

B. 原生崩溃（access violation / 被强杀 / 闪退）
     进程当场就死，Python 跑不了任何代码  所以只能"下次启动补发"：
       启动时写 data/.running 标记
       正常退出时删掉
       下次启动发现标记还在 -> 上次没退干净 -> 补发 faulthandler 现场 + 错误行

隐私
----
只发 core/log_digest 的摘要：系统信息 + 错误行 + 崩溃现场 + 日志路径。
不整包、不含聊天内容、密钥已脱敏。
config.json 里 "auto_report_crash": false 可整体关闭。
"""
import atexit
import json
import os
import sys
import threading
import time

from core.secret_store import decrypt_config

MARKER = ".running"
STAMP = ".last_autoreport"
MIN_INTERVAL = 600          # 10 分钟内不重复上报（防崩溃循环刷屏）
SEND_TIMEOUT = 4
MAX_CHARS = 4500

_STARTED = False
_LOCK = threading.Lock()


def _warn(msg):
    """GUI 模式下 sys.__stderr__ 可能是 None  写不出去就算了"""
    s = getattr(sys, "__stderr__", None)
    if s is None:
        return
    try:
        s.write(msg)
    except (OSError, ValueError):
        pass


def _data_dir(base):
    return os.path.join(base, "data")


def _marker(base):
    return os.path.join(_data_dir(base), MARKER)


def _stamp(base):
    return os.path.join(_data_dir(base), STAMP)


def _config(base):
    try:
        with open(os.path.join(_data_dir(base), "config.json"),
                  encoding="utf-8") as f:
            d = json.load(f)
        return decrypt_config(d) if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def enabled(base):
    """默认开启；config 里 auto_report_crash=false 可关"""
    return bool(_config(base).get("auto_report_crash", True))


def _version():
    try:
        from core.version import __version__
        return __version__
    except ImportError:
        return "?"


def _can_report(base):
    """同一台机器 10 分钟内只报一次"""
    now = time.time()
    p = _stamp(base)
    try:
        last = float(open(p, encoding="utf-8").read().strip() or 0)
    except (OSError, ValueError):
        last = 0.0
    if now - last < MIN_INTERVAL:
        return False
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(str(now))
    except OSError:
        return True
    return True


def report(base, title, detail=""):
    """发一条自动上报，返回 (ok, err)。不抛异常。"""
    if not enabled(base):
        return False, "已关闭自动上报"
    if not _can_report(base):
        return False, "刚报过，10 分钟内不重复"
    from core import log_digest
    from core.notifier import Notifier
    cfg = _config(base)
    try:
        n = Notifier(cfg)
        if not n.channel():
            return False, "通知通道未配置"
        digest = log_digest.collect(base)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:80])
    text = "%s\n%s\n\n%s" % (title, detail, digest["text"])
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n（已截断）"
    return n.send(text, timeout=SEND_TIMEOUT)


# ---------------- 钩子 ----------------
def install(base):
    """装 sys.excepthook / threading.excepthook（保留原来的钩子）"""
    prev = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            report(base, "【小6 崩溃自动上报】",
                   "异常: %s: %s" % (exc_type.__name__, str(exc)[:300]))
        except Exception as e:
            _warn("auto_report: %s\n" % str(e)[:100])
        prev(exc_type, exc, tb)      # 原来的崩溃写盘逻辑照常执行

    sys.excepthook = hook

    prev_t = getattr(threading, "excepthook", None)
    if prev_t is not None:
        def thook(args):
            try:
                report(base, "【小6 线程崩溃自动上报】",
                       "线程: %s\n异常: %s: %s"
                       % (getattr(args.thread, "name", "?"),
                          getattr(args.exc_type, "__name__", "?"),
                          str(args.exc_value)[:200]))
            except Exception as e:
                _warn("auto_report: %s\n" % str(e)[:100])
            prev_t(args)

        threading.excepthook = thook


# ---------------- 运行标记 ----------------
def mark_running(base):
    p = _marker(base)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(),
                       "start": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "version": _version()}, f, ensure_ascii=False)
        return True
    except OSError:
        return False


def mark_clean_exit(base):
    try:
        os.remove(_marker(base))
        return True
    except OSError:
        return False


def _read_running_info(base):
    """读取上一次运行留下的 .running；没有 / 坏了返回空 dict。"""
    p = _marker(base)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


def _pid_alive(pid):
    """跨平台判断进程是否还活着。

    这个检查很重要：如果上一个进程仍然在运行（比如用户同时开了两个实例），
    .running 还在并不代表它崩溃了。此时不能上报"上次异常退出"。
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _take_crashed_marker(base):
    """拿走"确认已经死亡"的旧 .running，返回其内容。

    必须在 mark_running() **之前**调用。否则刚写进去的当前进程标记
    会被当成"上次异常退出"，这正是旧实现每次启动都误报的根因。
    """
    info = _read_running_info(base)
    if not info:
        return {}
    if _pid_alive(info.get("pid")):
        # 另一个实例还活着：不报、也不删它的标记。
        return {}
    try:
        os.remove(_marker(base))
    except OSError:
        pass
    return info


def _report_previous(base, info):
    """根据已经确认的旧运行标记发一次补报。"""
    detail = ("上次启动: %s（pid %s，版本 %s）\n"
              "这次启动时发现它没正常退出（闪退 / 被强杀 / 原生崩溃）"
              % (info.get("start", "?"), info.get("pid", "?"),
                 info.get("version", "?")))
    ok, err = report(base, "【小6 上次异常退出，自动补报】", detail)
    if not ok:
        _warn("auto_report 补报未发出: %s\n" % err)
    return ok


def check_previous_crash(base):
    """检查并补报上次异常退出。

    直接调用时也做 pid 存活判断：当前进程自己写的标记、或另一个仍在运行的
    实例都不会被误报。
    """
    info = _take_crashed_marker(base)
    if not info:
        return False
    return _report_previous(base, info)


def start(base):
    """入口：先快照旧标记，再写当前标记 + 钩子 + 后台补报上次。

    顺序不能反：
        旧实现的 start() 先 mark_running()，后台线程再 check_previous_crash()，
        读到的其实是**当前进程自己**刚写的标记，于是每次启动都会误报一次
        "上次异常退出"。现在改为启动前快照旧标记，后台只补报快照。
    """
    global _STARTED
    with _LOCK:
        if _STARTED:
            return False
        _STARTED = True

    # 关键：必须先处理旧标记，再写当前进程的 .running
    previous = _take_crashed_marker(base)
    mark_running(base)
    install(base)
    atexit.register(mark_clean_exit, base)

    # 看门狗：主进程被强杀 / 原生崩溃时，由它补发（见 core/crash_watchdog）
    try:
        from core import crash_watchdog
        crash_watchdog.spawn(base)
    except Exception as e:
        _warn("auto_report 看门狗启动失败: %s\n" % str(e)[:100])

    def _bg():
        try:
            if previous:
                _report_previous(base, previous)
        except Exception as e:
            _warn("auto_report 补报失败: %s\n" % str(e)[:100])

    threading.Thread(target=_bg, daemon=True).start()
    return True
