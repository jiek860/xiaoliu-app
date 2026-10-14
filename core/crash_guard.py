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


def _thread_count():
    try:
        import threading
        return threading.active_count()
    except Exception:
        return -1


def status():
    """当前状态（给"深度自检"用）"""
    return {
        "已开启": _ENABLED,
        "日志": _LOG_PATH,
        "线程数": _thread_count(),
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
    _ENABLED = False
    _LOG_PATH = ""
    _FILE_OBJ = None
