# -*- coding: utf-8 -*-
"""HotReload：变化检测、沙盒验证、重载、回滚和自动检查。"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.hot_reload import HotReload  # noqa: E402


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.modules = {}
        self.logs = []

    def _log(self, msg):
        self.logs.append(msg)


def _setup(tmp_path):
    (tmp_path / "modules" / "installed").mkdir(parents=True)
    (tmp_path / "modules_repo").mkdir()
    (tmp_path / "core").mkdir()
    sample = tmp_path / "modules" / "installed" / "sample.py"
    sample.write_text("class Sample:\n    pass\n", encoding="utf-8")
    core_file = tmp_path / "core" / "x.py"
    core_file.write_text("X = 1\n", encoding="utf-8")
    tr = _Trunk(tmp_path)
    hr = HotReload(tr)
    return hr, tr, sample, core_file


def test_hot_reload_detects_changes(tmp_path):
    hr, _tr, sample, core_file = _setup(tmp_path)
    hr.check_changes()
    sample.write_text("class Sample:\n    value = 2\n", encoding="utf-8")
    os.utime(sample, (time.time() + 10, time.time() + 10))
    assert "sample" in hr.check_changes()

    hr.check_core_changes()
    core_file.write_text("X = 2\n", encoding="utf-8")
    os.utime(core_file, (time.time() + 10, time.time() + 10))
    changed = hr.check_core_changes()
    assert changed == ["x.py"]


def test_hot_reload_sandbox_good_and_bad(tmp_path):
    hr, _tr, sample, _core = _setup(tmp_path)
    assert hr.sandbox_test("sample") is True
    sample.write_text("def broken(:\n", encoding="utf-8")
    assert hr.sandbox_test("sample") is False


def test_hot_reload_reload_and_rollback(tmp_path, monkeypatch):
    hr, tr, sample, _core = _setup(tmp_path)
    monkeypatch.setattr(hr, "sandbox_test", lambda name: True)
    ok, msg = hr.reload_module("sample")
    assert ok is True, msg
    assert "sample" in tr.modules
    assert hr.reload_count == 1
    # 触发构造失败回滚路径
    sample.write_text("class Broken:\n    def __init__(self):\n        raise RuntimeError('bad')\n",
                      encoding="utf-8")
    tr.modules = {"sample": type("Old", (), {})}
    ok2, msg2 = hr.reload_module("sample")
    assert ok2 is False
    assert "回滚" in msg2
    ok3, msg3 = hr.reload_module("missing")
    assert ok3 is False
    assert "找不到" in msg3


def test_hot_reload_core_and_auto_reload(tmp_path, monkeypatch):
    hr, _tr, _sample, _core = _setup(tmp_path)
    monkeypatch.setattr(hr, "_sandbox_core_pkg", lambda: True)
    monkeypatch.setattr(hr, "_restart_program", lambda: None)
    assert hr.reload_core()["ok"] is True

    monkeypatch.setattr(hr, "check_changes", lambda: ["sample"])
    monkeypatch.setattr(hr, "reload_module", lambda name: (True, "ok:" + name))
    monkeypatch.setattr(hr, "check_core_changes", lambda: ["x.py"])
    monkeypatch.setattr(hr, "reload_core", lambda: {"ok": True})
    r = hr.auto_reload()
    assert r["检测到变化"] == 2
    hr.reload_count = 1
    assert hr.run()["已重载次数"] >= 1

def test_restart_program_spawns_successor_then_exits(tmp_path, monkeypatch):
    """先拉起新进程、再做优雅退出（不能直接 os._exit 把旧进程硬杀）"""
    hr, _tr, _sample, _core = _setup(tmp_path)
    seen = {}

    class FakeProc:
        pass

    def fake_popen(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr("modules.installed.hot_reload.subprocess.Popen",
                        fake_popen)
    monkeypatch.setattr(hr, "_graceful_exit", lambda: seen.setdefault("exit", 1))
    hr._restart_program()
    assert seen["exit"] == 1
    assert isinstance(hr._child, FakeProc)
    assert seen["args"][1].endswith("app_pyqt.py")


def test_graceful_exit_shuts_down_flushes_and_exits(tmp_path, monkeypatch):
    hr, tr, _sample, _core = _setup(tmp_path)
    called = {}
    tr.shutdown = lambda: called.setdefault("shutdown", True)
    monkeypatch.setattr("modules.installed.hot_reload.os._exit",
                        lambda code: called.setdefault("exit", code))
    hr._graceful_exit()
    assert called["shutdown"] is True
    assert called["exit"] == 0


def test_stop_terminates_successor_process(tmp_path):
    hr, _tr, _sample, _core = _setup(tmp_path)

    class Child:
        def __init__(self):
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            self.killed = True

    child = Child()
    hr._child = child
    assert hr.stop() == {"状态": "已停止"}
    assert child.killed is True
    assert hr._child is None
