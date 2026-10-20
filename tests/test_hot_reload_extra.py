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