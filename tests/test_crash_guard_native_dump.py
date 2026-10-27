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
    assert st["dump目录"] == str(tmp_path)
    assert st["最近dump"] == ""


def test_dump_dir_follows_log_dir(tmp_path, monkeypatch):
    """enable() 里 dump 目录 = 日志目录的兄弟位置（data/logs -> data/dumps）"""
    cg.reset_for_test()
    monkeypatch.setattr(cg, "_load_apis", lambda: FakeApi())
    log = tmp_path / "data" / "logs" / "faulthandler.log"
    path = cg.enable(str(log))
    assert path == str(log)
    assert cg.status()["dump目录"] == str(tmp_path / "data" / "dumps")
    cg.reset_for_test()
