# -*- coding: utf-8 -*-
"""回归测试：PyQt5 与 torch 的 DLL 冲突修复

背景：PyQt5 自带旧版 MSVCP140.dll（14.26），import PyQt5 后它会占住这个基名，
导致 torch 的 c10.dll 初始化失败（WinError 1114）。
core/win_dll_fix.preload_msvc_runtime() 在导入 Qt 之前先加载系统新版来抢占基名。

实测：修复前 torch 导入失败；修复后成功。这条测试用子进程复现完整顺序，
一旦有人把预加载调用挪到 Qt 导入之后（或删掉），这里会立刻变红。
"""
import os
import subprocess
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPT = os.path.join(BASE, "optional_libs")

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="仅 Windows 上存在该 DLL 冲突")
pytestmark = pytest.mark.skipif(
    not os.path.isdir(os.path.join(OPT, "torch")), reason="没装可选组件 torch")
pytestmark = pytest.mark.skipif(
    not os.path.isdir(os.path.join(OPT, "cv2")), reason="optional_libs 不完整")


def _run(code):
    return subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          cwd=BASE, timeout=180)


def test_torch_loads_after_pyqt5_with_fix():
    """先 Qt 后 torch，经预加载后应当成功"""
    code = (
        "import sys, os\n"
        "sys.path.insert(0, %r)\n"
        "sys.path.insert(0, %r)\n"
        "sys.path.insert(0, %r)\n"
        "from core.win_dll_fix import preload_msvc_runtime, diagnose\n"
        "preload_msvc_runtime()\n"
        "import PyQt5.QtWidgets\n"
        "import torch\n"
        "print('TORCH_OK', torch.__version__)\n"
        "print('MSVCP', diagnose().get('MSVCP140.dll', ''))\n"
    ) % (OPT, os.path.join(BASE, "libs"), BASE)
    r = _run(code)
    assert "TORCH_OK" in (r.stdout or ""), \
        "预加载后 torch 仍无法导入:\n%s\n%s" % (r.stdout, (r.stderr or "")[-600:])


def test_diagnose_reports_system_msvcp():
    """修复生效时 MSVCP140 应来自系统目录，而不是 PyQt5 自带的那份"""
    code = (
        "import sys, os\n"
        "sys.path.insert(0, %r)\n"
        "sys.path.insert(0, %r)\n"
        "from core.win_dll_fix import preload_msvc_runtime, diagnose\n"
        "preload_msvc_runtime()\n"
        "import PyQt5.QtWidgets\n"
        "print('SRC', diagnose().get('MSVCP140.dll', ''))\n"
    ) % (OPT, os.path.join(BASE, "libs"))
    r = _run(code)
    line = [l for l in (r.stdout or "").splitlines() if l.startswith("SRC ")]
    assert line, "拿不到 MSVCP140 来源:\n%s" % (r.stdout, r.stderr)
    src = line[0][4:].strip().lower()
    assert "pyqt5" not in src, "MSVCP140 仍来自 PyQt5（预加载没生效）: %s" % src
    assert "system32" in src, "MSVCP140 不是系统版本: %s" % src


def test_preload_is_idempotent():
    """重复调用不应报错"""
    from core.win_dll_fix import preload_msvc_runtime
    a = preload_msvc_runtime()
    b = preload_msvc_runtime()
    assert isinstance(a, str) and isinstance(b, str)
