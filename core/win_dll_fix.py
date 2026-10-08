# -*- coding: utf-8 -*-
r"""Windows 兼容修复：PyQt5 自带的旧版 MSVCP140.dll 会让 torch 加载失败

现象
----
    先 import PyQt5，再 import torch：
        OSError [WinError 1114] 动态链接库(DLL)初始化例程失败。
        Error loading "...\optional_libs\torch\lib\c10.dll" or one of its dependencies.

原因
----
    PyQt5 在 site-packages\PyQt5\Qt5\bin\ 里自带一份 MSVCP140.dll（实测 14.26），
    import PyQt5 时会把它加载进进程。而 Windows 的 DLL 解析是按"基名"匹配已加载模块的，
    之后 torch 的 c10.dll 需要较新的 MSVC 运行时（实测系统里是 14.44），
    旧版无法满足它的初始化，于是 c10.dll 的 DllMain 直接失败。

修法
----
    在 import PyQt5 之前，先按全路径把系统目录里较新的
    MSVCP140.dll / VCRUNTIME140.dll / VCRUNTIME140_1.dll 加载进进程，抢占基名。
    之后 PyQt5 请求 MSVCP140.dll 时会直接复用系统新版，不再加载它自带的旧版。
    MSVC 运行时是向后兼容的（新版能满足按旧版编译的程序），所以 Qt 用新版没问题，
    这也是安装新版 VC++ 可再发行组件的正常效果。

实测结果
--------
    修复前：MSVCP140 来自 PyQt5\Qt5\bin（14.26），torch 导入失败
    修复后：MSVCP140 来自 C:\Windows\System32（14.44），torch 2.14.1 导入成功、张量运算正常

调用位置
--------
    run.py / run_server.py / gui/app_pyqt.py 的**最前面**，且必须在任何 Qt 导入之前。
    重复调用无副作用。
"""
import os
import sys

_DONE = False

_RUNTIME_DLLS = ("MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll")


def preload_msvc_runtime():
    """抢占 MSVC 运行时基名。返回一句说明，便于日志与测试断言。

    必须在任何 Qt / torch 导入之前调用。非 Windows 或调用失败都不抛异常，
    最坏情况就是退回到原来的行为（torch 加载不了，但程序照常运行）。
    """
    global _DONE
    if _DONE:
        return "MSVC 运行时已预加载（重复调用）"
    _DONE = True

    if not sys.platform.startswith("win"):
        return "非 Windows，跳过 MSVC 预加载"

    try:
        import ctypes
    except Exception as e:
        return "MSVC 预加载跳过（ctypes 不可用: %s）" % str(e)[:40]

    sysroot = os.environ.get("SystemRoot") or r"C:\Windows"
    sys32 = os.path.join(sysroot, "System32")
    done, failed, absent = [], [], []

    for name in _RUNTIME_DLLS:
        path = os.path.join(sys32, name)
        if not os.path.exists(path):
            absent.append(name)
            continue
        try:
            ctypes.WinDLL(path)          # 按全路径加载 -> 占据该基名
            done.append(name)
        except Exception as e:
            failed.append("%s(%s)" % (name, str(e)[:30]))

    msg = "MSVC 预加载: " + (", ".join(done) if done else "无")
    if failed:
        msg += " | 失败: " + ", ".join(failed)
    if absent:
        msg += " | 系统目录缺少: " + ", ".join(absent)
    return msg


def diagnose():
    """返回当前进程里 MSVC 运行时的实际来源，用于排查。"""
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi")
    fn = psapi.GetModuleFileNameExW
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    h = k32.GetCurrentProcess()
    out = {}
    for name in _RUNTIME_DLLS:
        hm = k32.GetModuleHandleW(name)
        if not hm:
            out[name] = "(未加载)"
            continue
        buf = ctypes.create_unicode_buffer(1024)
        fn(h, hm, buf, 1024)
        out[name] = buf.value
    return out
