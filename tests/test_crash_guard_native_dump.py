# -*- coding: utf-8 -*-
"""内置原生 dump（core/crash_guard.install_native_dump）的测试。

背景：procdump 常驻在本机不可靠（进程被回收、计划任务注册被拒），
277 次异常一份 .dmp 都没抓到。改成程序自己写 minidump。
这里用假 API 注入，验证"注册 / 命名 / 关掉开关 / 找人"这几件事，
**不会真的制造崩溃**。
"""
import os
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import crash_guard as cg  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    """每条用例前后都把 dump 状态清空。

    ⚠️ 为什么必须这么做：`_DUMP_INSTALLED/_DUMP_DIR` 是**模块级**的，
    别的测试文件（test_crash_guard.py）里会调 `enable()` 把它们设成
    真实目录，结果这里的 install/status 断言全被污染。
    """
    cg.reset_for_test()
    yield
    cg.reset_for_test()


class FakeApi:
    """假 kernel32/dbghelp：WriteDump 往传入的 fd 里写 4 个字节

    注意 `__getitem__`：`write_minidump/install_native_dump` 是按 dict
    取值（`api["to_handle"]`）的，少了它就抛 TypeError 被静默吞成 ""。
    """

    def __init__(self, ok=True):
        self.ok = ok
        self.dump_type = 2
        self.filter_type = lambda fn: fn
        self.to_handle = lambda fd: fd
        self.GetCurrentProcess = lambda: 0x1234
        self.GetCurrentProcessId = lambda: 4321
        self.SetFilter = self._set_filter
        self.WriteDump = self._write
        self.filter_installed = False

    def __getitem__(self, key):
        return getattr(self, key)

    def _set_filter(self, handle):
        self.filter_installed = True
        return 0

    def _write(self, proc, pid, handle, dump_type, a, b, c):
        assert (proc, pid, dump_type) == (0x1234, 4321, 2)
        if self.ok:
            os.write(handle, b"MDMP")
        return 1 if self.ok else 0


def test_write_minidump_creates_file(tmp_path):
    api = FakeApi()
    path = cg.write_minidump(str(tmp_path), apis=api)
    assert path.endswith(".dmp")
    assert os.path.getsize(path) == 4


def test_write_minidump_reports_failure_without_raising(tmp_path):
    api = FakeApi(ok=False)
    assert cg.write_minidump(str(tmp_path), apis=api) == ""


def test_install_marks_installed_and_registers_filter(tmp_path):
    api = FakeApi()
    res = cg.install_native_dump(str(tmp_path), apis=api)
    assert res["已安装"] is True
    assert res["目录"] == str(tmp_path)
    assert api.filter_installed is True
    # 第二次调用直接返回，不重复注册
    assert cg.install_native_dump(str(tmp_path), apis=api)["已安装"] is True


def test_install_respects_env_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("X6_NO_NATIVE_DUMP", "1")
    res = cg.install_native_dump(str(tmp_path), apis=FakeApi())
    assert res["已安装"] is False
    assert "X6_NO_NATIVE_DUMP" in res["原因"]


def test_install_reports_reason_when_apis_unavailable(tmp_path, monkeypatch):
    def boom():
        raise OSError("只有 Windows 支持 MiniDumpWriteDump")

    monkeypatch.setattr(cg, "_load_apis", boom)
    res = cg.install_native_dump(str(tmp_path))
    assert res["已安装"] is False
    assert "Windows" in res["原因"]


def test_last_dump_returns_newest(tmp_path):
    old = tmp_path / "crash_old_1.dmp"
    new = tmp_path / "crash_new_2.dmp"
    old.write_bytes(b"a")
    new.write_bytes(b"b")
    os.utime(str(old), (1, 1))
    os.utime(str(new), (2, 2))
    assert cg.last_dump(str(tmp_path)) == str(new)


def test_last_dump_empty_when_dir_missing(tmp_path):
    assert cg.last_dump(str(tmp_path / "nope")) == ""


def test_status_reports_dump_fields(tmp_path):
    cg.reset_for_test()
    cg.install_native_dump(str(tmp_path), apis=FakeApi())
    st = cg.status()
    assert st["内置dump"] is True
    assert st["dump方式"] == "handler"
    assert st["dump目录"] == str(tmp_path)
    assert st["最近dump"] == ""


class FakeReg:
    """假 winreg：只记录写进注册表的键和值"""

    HKEY_CURRENT_USER = 1
    REG_EXPAND_SZ = 2
    REG_DWORD = 4

    def __init__(self):
        self.key = ""
        self.values = {}

    def CreateKey(self, root, key):
        self.key = key
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def SetValueEx(self, k, name, reserved, typ, value):
        self.values[name] = value
        return 0


def test_install_local_dumps_writes_registry_values(tmp_path):
    """LocalDumps 是系统层机制：键路径/目录/类型/份数都要对"""
    reg = FakeReg()
    res = cg.install_local_dumps(app_name="小6智能体.exe", dump_dir=str(tmp_path),
                                 count=3, _winreg=reg)
    assert res["已注册"] is True
    assert res["目录"] == str(tmp_path)
    assert reg.key.endswith("LocalDumps\\小6智能体.exe")
    assert reg.values["DumpFolder"] == str(tmp_path)
    assert reg.values["DumpType"] == 2        # 2 = 完整内存
    assert reg.values["DumpCount"] == 3
    assert cg.status()["dump方式"] == "LocalDumps"


def test_install_local_dumps_respects_env_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("X6_NO_NATIVE_DUMP", "1")
    reg = FakeReg()
    res = cg.install_local_dumps(dump_dir=str(tmp_path), _winreg=reg)
    assert res["已注册"] is False
    assert reg.values == {}


def test_enable_registers_local_dumps_only_when_frozen(tmp_path, monkeypatch):
    """打包版才注册 LocalDumps；源码版不碰注册表（python.exe 是全机共用的）"""
    cg.reset_for_test()
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"已注册": True, "目录": kw.get("dump_dir", ""), "原因": ""}

    monkeypatch.setattr(cg, "install_local_dumps", fake)
    log = tmp_path / "data" / "logs" / "faulthandler.log"
    assert cg.enable(str(log)) == str(log)
    assert "dump_dir" not in seen, "源码版不该注册 LocalDumps"
    cg.reset_for_test()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert cg.enable(str(log)) == str(log)
    assert seen["dump_dir"] == str(tmp_path / "data" / "dumps")
    cg.reset_for_test()


def test_enable_handler_mode_still_available(tmp_path, monkeypatch):
    """X6_DUMP_MODE=handler 时才装 ctypes 回调（单线程调试用）"""
    cg.reset_for_test()
    monkeypatch.setenv("X6_DUMP_MODE", "handler")
    monkeypatch.setattr(cg, "install_native_dump", lambda d=None: {"已安装": True})
    log = tmp_path / "data" / "logs" / "faulthandler.log"
    assert cg.enable(str(log)) == str(log)
    assert cg.status()["日志"] == str(log)
    cg.reset_for_test()


def test_registered_filter_writes_dump_when_called(tmp_path):
    """模拟系统回调：handler 被调用时要真的写 dump，并返回 1（EXCEPTION_EXECUTE_HANDLER）

    2026-10-28 实测发现：`WINFUNCTYPE` 少写了参数，系统回调进来直接抛
    "missing 1 required positional argument: '_exception_pointer'"，
    真实崩溃时一份 dump 都写不出来。这条用例盯住"回调能被调用"这件事。
    """
    api = FakeApi()
    handlers = []
    api.SetFilter = lambda handle: handlers.append(handle)
    assert cg.install_native_dump(str(tmp_path), apis=api)["已安装"] is True
    assert handlers, "SetUnhandledExceptionFilter 没被调用"
    assert handlers[0](None) == 1          # 系统会传 EXCEPTION_POINTERS*
    assert len(list(tmp_path.glob("crash_*.dmp"))) == 1


def test_real_filter_prototype_takes_exception_pointer():
    """真实 API 的回调原型必须带 1 个参数，否则崩溃时 dump 写不出来"""
    if sys.platform != "win32":
        pytest.skip("只有 Windows 有 SetUnhandledExceptionFilter")
    api = cg._load_apis()
    assert len(api["filter_type"]._argtypes_) == 1
