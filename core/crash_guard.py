# -*- coding: utf-8 -*-
"""崩溃现场捕获（faulthandler）

为什么需要这个模块
------------------
2026-10-13 跑全量测试时出现过一次 **access violation**：
进程直接死（退出码 3221225477），之后连跑 4 次全过、单独跑 5 次全过，
**没复现、没现场、没定位**，只能在 CHANGELOG 里如实记一句"没查出来"。

根因在于：**`sys.excepthook` 抓不到 C 层崩溃。**
    sys.excepthook  只能接住 **Python 层**没处理的异常
    access violation 是 **C 层**内存错误 —— 进程当场死，
    Python 解释器根本没机会跑 excepthook

`faulthandler` 是 Python 自带模块，它把"崩溃时 dump 栈"做在**信号/异常
处理层**，能在进程死之前把**所有线程的 Python 栈**写进文件。

⚠️ 一个必须说清的局限
--------------------
faulthandler 只能 dump **Python 层**的栈，**看不到 numpy / Qt / torch
的原生子帧**。所以：
    · 它能告诉你"崩在哪个 Python 函数、哪个线程"  ← 通常够用来定位
    · 它**不能**告诉你"崩在 c10.dll 的哪个偏移"     ← 那需要 WER dump

要拿到原生帧，见本模块 `WER_HINT` 里写的办法（Windows 错误报告 /
procdump）。两样配合才能真正定位。

2026-10-27 补充（批次 26）
-------------------------
procdump 这条路在本机走不通：进程会被回收（pid 2408 / 2492 先后消失），
注册计划任务被系统拒绝，277 次异常一份 .dmp 都没抓到。所以改成**程序自己
写 dump**：`enable()` 会调用 `install_native_dump()`，用
`SetUnhandledExceptionFilter` + `dbghelp!MiniDumpWriteDump` 在未处理异常
（含 access violation）时把 `data/dumps/crash_<时间>_<pid>.dmp` 写下来。
不想要可以设 `X6_NO_NATIVE_DUMP=1`。

用法
----
程序里（`run.py` 最开头，**必须在 import Qt 之前**）：
    from core.crash_guard import enable
    enable()

排查卡死时（比如界面卡住不响应）：
    from core.crash_guard import dump_now
    dump_now("界面卡住")      # 立刻把所有线程的栈写进日志
"""
import os
import sys
import time

_ENABLED = False
_LOG_PATH = ""
_FILE_OBJ = None          # ⚠️ 必须留住引用，否则被 GC 后 faulthandler 失效

# ---- 内置原生 dump（2026-10-27 批次 26）---------------------------------
# 以前只有 faulthandler（Python 层栈）+ 外部 procdump（常驻进程）。
# 但 procdump 在这台机器上活不长（pid 会被回收、计划任务注册被拒），
# 277 次异常一份 .dmp 都没抓到。所以改成**程序自己**在未处理异常时写
# minidump：SetUnhandledExceptionFilter + dbghelp!MiniDumpWriteDump。
# 这样崩溃现场不再依赖任何外部进程。
_DUMP_INSTALLED = False
_DUMP_DIR = ""
_DUMP_ERROR = ""
_LAST_ERROR = ""          # 最近一次写 dump 失败的原因（诊断用，不对外抛）
_FILTER_HANDLE = None     # ⚠️ 同上，必须留住引用
_MINIDUMP_TYPE = 0x00000002   # MiniDumpWithFullMemory（和 WER DumpType=2 一致）

WER_HINT = """
要看 C 层（numpy/Qt/torch）的原生栈，faulthandler 不够，需要系统级 dump：

  方法一：procdump（推荐，Sysinternals 官方工具）
      procdump -e -ma -w 小6智能体.exe D:\\dumps

  方法二：Windows 错误报告（WER）本地 dump，改注册表：
      HKLM\\SOFTWARE\\Microsoft\\Windows\\Windows Error Reporting\\LocalDumps
        DumpFolder  = D:\\dumps      (REG_EXPAND_SZ)
        DumpType    = 2              (REG_DWORD，2 = 完整 dump)
        DumpCount   = 10             (REG_DWORD)

  拿到 .dmp 后用 WinDbg 打开，命令：!analyze -v
"""


def enable(log_path=None, all_threads=True):
    """开启 faulthandler 崩溃捕获

    参数
        log_path     日志文件路径；默认 <项目>/data/logs/faulthandler.log
        all_threads  True = 崩溃时 dump **所有**线程的栈
                     ⚠️ 一定要 True：那次崩溃和线程数有关
                     （v25.2.10 定位到"40 个线程同时存在"是诱因），
                     只看主线程等于什么都没看到。

    返回日志路径；失败返回 ""（**不抛异常** —— 这是个保护措施，
    它自己坏掉不该拦住程序启动）。
    """
    global _ENABLED, _LOG_PATH, _FILE_OBJ
    if _ENABLED:
        return _LOG_PATH
    try:
        import faulthandler
    except ImportError:
        return ""

    try:
        if not log_path:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_path = os.path.join(base, "data", "logs", "faulthandler.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        # 每次启动都写一行分隔 —— 否则多次崩溃的栈混在一起分不清
        _FILE_OBJ = open(log_path, "a", encoding="utf-8", errors="replace")
        _FILE_OBJ.write("\n" + "=" * 70 + "\n")
        _FILE_OBJ.write("启动 %s  pid=%d  python=%s\n"
                        % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(),
                           sys.version.split()[0]))
        _FILE_OBJ.write("工作目录 %s\n" % os.getcwd())
        _FILE_OBJ.write("=" * 70 + "\n")
        _FILE_OBJ.flush()

        faulthandler.enable(_FILE_OBJ, all_threads=all_threads)
        _ENABLED = True
        _LOG_PATH = log_path
        # 顺带装内置原生 dump（失败也不影响启动，见 install_native_dump）；
        # dump 目录放在日志目录的兄弟位置：data/logs/xx.log -> data/dumps
        _log_dir = os.path.dirname(log_path)
        _dump_dir = (os.path.join(os.path.dirname(_log_dir), "dumps")
                     if _log_dir else _default_dump_dir())
        install_native_dump(_dump_dir)
        return log_path
    # 静默是故意的：崩溃捕获**自己**出问题不该拦住程序启动 ——
    # 它是保护措施，不是功能。失败就退化成"和以前一样没有现场"，
    # 但不能因为装不上它就打不开程序
    except Exception:
        return ""


def dump_now(reason="", log_path=None):
    """**立刻**把所有线程的栈写进日志（不崩溃也能用）

    用途：界面卡住、功能一直不返回时，手动写一次现场。
    卡死往往比崩溃更难查（没有崩溃点，只有一个"不动"的现象）。

    返回日志路径；失败返回 ""。
    """
    try:
        import faulthandler
    except ImportError:
        return ""
    path = log_path or _LOG_PATH
    if not path:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "data", "logs", "faulthandler.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write("\n" + "-" * 70 + "\n")
            f.write("[手动 dump] %s  %s\n"
                    % (time.strftime("%Y-%m-%d %H:%M:%S"),
                       reason or "（未说明原因）"))
            f.write("-" * 70 + "\n")
            f.flush()
            faulthandler.dump_traceback(file=f, all_threads=True)
            f.write("线程数 %d\n" % _thread_count())
            f.write("-" * 70 + "\n")
        return path
    # 静默是故意的：同上 —— 抓现场失败不该引发新的问题
    except Exception:
        return ""


def _default_dump_dir():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "dumps")


def _load_apis():
    """取 Windows 的原生 dump 接口（可注入，便于离线测试）"""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    if sys.platform != "win32":
        raise OSError("只有 Windows 支持 MiniDumpWriteDump")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.GetCurrentProcessId.argtypes = []
    kernel32.SetUnhandledExceptionFilter.restype = ctypes.c_void_p
    kernel32.SetUnhandledExceptionFilter.argtypes = [ctypes.c_void_p]
    dbghelp.MiniDumpWriteDump.restype = wintypes.BOOL
    dbghelp.MiniDumpWriteDump.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    return {
        "dump_type": _MINIDUMP_TYPE,
        "filter_type": ctypes.WINFUNCTYPE(wintypes.LONG),
        "to_handle": msvcrt.get_osfhandle,
        "GetCurrentProcess": kernel32.GetCurrentProcess,
        "GetCurrentProcessId": kernel32.GetCurrentProcessId,
        "SetFilter": kernel32.SetUnhandledExceptionFilter,
        "WriteDump": dbghelp.MiniDumpWriteDump,
    }


def _winerr():
    """取 Windows 最近一次错误码（拿不到就返回 ?）；只用于日志，不抛"""
    try:
        import ctypes
        return ctypes.get_last_error() or 0
    # 静默是故意的：诊断信息拿不到只是少个数字
    except Exception:
        return "?"


def write_minidump(dump_dir=None, apis=None, reason=""):
    """写一份 minidump，返回路径；失败返回 ""（不抛异常，崩溃现场不能因为它更糟）"""
    global _LAST_ERROR
    api = apis or _load_apis()
    target = dump_dir or _DUMP_DIR or _default_dump_dir()
    try:
        os.makedirs(target, exist_ok=True)
        path = os.path.join(target, "crash_%s_%d.dmp"
                            % (time.strftime("%Y%m%d_%H%M%S"), os.getpid()))
        with open(path, "wb") as f:
            handle = api["to_handle"](f.fileno())
            ok = api["WriteDump"](api["GetCurrentProcess"](),
                                  api["GetCurrentProcessId"](), handle,
                                  api["dump_type"], None, None, None)
        if ok:
            _LAST_ERROR = ""
            _append_log("[原生 dump] %s  %s"
                        % (path, reason or "未处理异常"))
            return path
        _LAST_ERROR = "MiniDumpWriteDump 返回失败（err=%s）" % _winerr()
        return ""
    # 静默是故意的：写 dump 本身失败时不能再抛 —— 崩溃处理里抛异常会把
    # 原始现场彻底盖掉，宁可只留一条日志
    except Exception as exc:
        _LAST_ERROR = "%s: %s" % (type(exc).__name__, str(exc)[:140])
        _append_log("[原生 dump 失败] %s" % _LAST_ERROR)
        return ""


def _append_log(text):
    """往 faulthandler 日志追加一行（失败就算了，不抛）"""
    path = _LOG_PATH
    if not path:
        return False
    try:
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(text + "\n")
        return True
    # 静默是故意的：日志写不进去也只能放弃
    except Exception:
        return False


def install_native_dump(dump_dir=None, apis=None):
    """注册"未处理异常就写 minidump"。

    返回 {"已安装": bool, "目录": str, "原因": str}。
    失败**不抛异常** —— 崩溃捕获是保护措施，不能拦住程序启动。

    可关：环境变量 X6_NO_NATIVE_DUMP=1（排查"它自己把程序搞挂"时用）。
    """
    global _DUMP_INSTALLED, _DUMP_DIR, _DUMP_ERROR, _FILTER_HANDLE, _LAST_ERROR
    if _DUMP_INSTALLED:
        return {"已安装": True, "目录": _DUMP_DIR, "原因": ""}
    if os.environ.get("X6_NO_NATIVE_DUMP", "").strip().lower() not in (
            "", "0", "false", "no"):
        return {"已安装": False, "目录": "", "原因": "X6_NO_NATIVE_DUMP 已开启"}
    try:
        api = apis or _load_apis()
        _DUMP_DIR = dump_dir or _default_dump_dir()
        os.makedirs(_DUMP_DIR, exist_ok=True)

        def _handler(_exception_pointer):
            # 1 = EXCEPTION_EXECUTE_HANDLER：写完 dump 就让进程照常终止
            write_minidump(_DUMP_DIR, api, "未处理异常（原生 dump）")
            return 1

        _FILTER_HANDLE = api["filter_type"](_handler)
        api["SetFilter"](_FILTER_HANDLE)
        _DUMP_INSTALLED = True
        _DUMP_ERROR = ""
        _LAST_ERROR = ""
        return {"已安装": True, "目录": _DUMP_DIR, "原因": ""}
    # 静默是故意的：同上 —— 装不上就退化成"只有 faulthandler 现场"
    except Exception as exc:
        _DUMP_ERROR = str(exc)[:160]
        _LAST_ERROR = _DUMP_ERROR
        return {"已安装": False, "目录": "", "原因": _DUMP_ERROR}


def last_dump(dump_dir=None):
    """最近一份 .dmp 的路径；没有返回 ""（给"深度自检"用）"""
    target = dump_dir or _DUMP_DIR or _default_dump_dir()
    try:
        names = [os.path.join(target, n) for n in os.listdir(target)
                 if n.lower().endswith(".dmp")]
        return max(names, key=os.path.getmtime) if names else ""
    # 静默是故意的：目录不存在/没权限时只是"没有 dump"
    except Exception:
        return ""


def _thread_count():
    try:
        import threading
        return threading.active_count()
    except Exception:
        return -1


def status():
    """当前状态（给"深度自检"用）"""
    dump = last_dump()
    return {
        "已开启": _ENABLED,
        "日志": _LOG_PATH,
        "线程数": _thread_count(),
        "内置dump": _DUMP_INSTALLED,
        "dump目录": _DUMP_DIR or _default_dump_dir(),
        "最近dump": dump,
        "说明": ("崩溃时会自动把所有线程的栈写进日志" if _ENABLED
                 else "未开启 —— 崩溃时不会有现场"),
    }


def recent_crashes(lines=40, log_path=None):
    """读日志末尾（给"查看崩溃记录"用）；没有返回空字符串"""
    path = log_path or _LOG_PATH
    if not path:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "data", "logs", "faulthandler.log")
    if not os.path.exists(path):
        return ""
    try:
        from collections import deque
        with open(path, encoding="utf-8", errors="replace") as f:
            tail = list(deque(f, maxlen=lines))
        return "".join(tail)
    except Exception:
        return ""


def reset_for_test():
    """只给测试用：把模块状态清回未开启"""
    global _ENABLED, _LOG_PATH, _FILE_OBJ
    global _DUMP_INSTALLED, _DUMP_DIR, _DUMP_ERROR, _FILTER_HANDLE, _LAST_ERROR
    _ENABLED = False
    _LOG_PATH = ""
    _FILE_OBJ = None
    _DUMP_INSTALLED = False
    _DUMP_DIR = ""
    _DUMP_ERROR = ""
    _LAST_ERROR = ""
    _FILTER_HANDLE = None
