# -*- coding: utf-8 -*-
"""gui/mixins/background_tasks_mixin.py 的行为测试。

这些方法从 dialog_mixin.py 原样搬出，之前只有"导出存在"的契约测试，
搬出来的每一行都算新增改动行，所以这里按真实调用路径覆盖：
后台回调、任务闭环、学习闭环、备份导出、自更新、模块按钮、组件安装。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import gui.mixins.background_tasks_mixin as bt


class FakeSignal:
    def __init__(self):
        self.cb = None

    def connect(self, cb):
        self.cb = cb

    def emit(self, value):
        self.cb(value)


class FakeWorker:
    instances = []

    def __init__(self, *args):
        self.args = args
        self.done = FakeSignal()
        FakeWorker.instances.append(self)

    def start(self):
        pass


class FakeTrunk:
    def __init__(self, modules=None):
        self.modules = dict(modules or {})
        self.calls = []

    def call(self, module, action):
        self.calls.append((module, action))
        return {"ok": True, "值": 1}


class FakeResult:
    def __init__(self):
        self.text = ""

    def setPlainText(self, text):
        self.text = text


class Host(bt.BackgroundTaskMixin):
    def __init__(self, trunk=None, base="."):
        self.trunk = trunk
        self.base = base


class FakeLabel:
    def __init__(self):
        self.text = ""
        self.enabled = True

    def setText(self, text):
        self.text = text

    def setStyleSheet(self, _style):
        pass

    def setEnabled(self, enabled):
        self.enabled = enabled


def _patch_workers(monkeypatch):
    FakeWorker.instances = []
    monkeypatch.setattr(bt, "BgWorker", FakeWorker)
    monkeypatch.setattr(bt, "TaskWorker", FakeWorker)
    monkeypatch.setattr(bt, "LearnWorker", FakeWorker)


def _last_worker():
    return FakeWorker.instances[-1]


def test_bg_call_starts_worker_and_writes_result(monkeypatch):
    _patch_workers(monkeypatch)
    result = FakeResult()
    Host()._bg_call(result, lambda: "done", "导出")
    assert "▶ 导出中" in result.text
    _last_worker().done.emit("done")
    assert result.text == "done"


def test_run_task_goal_cancel(monkeypatch):
    _patch_workers(monkeypatch)
    monkeypatch.setattr(bt.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("  ", True)))
    result = FakeResult()
    Host(FakeTrunk())._run_task_goal(result)
    assert result.text == "已取消"
    assert not FakeWorker.instances


def test_run_task_goal_formats_success_and_failure(monkeypatch):
    _patch_workers(monkeypatch)
    monkeypatch.setattr(bt.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("写个脚本", True)))
    host = Host(FakeTrunk())
    result = FakeResult()
    host._run_task_goal(result)
    assert "任务闭环开始" in result.text
    worker = _last_worker()
    worker.done.emit({"ok": True, "步骤数": 2, "评分": 9,
                      "明细": [{"步骤": "a" * 30, "agent": "g", "验证": "v"}]})
    assert "✔ 任务完成" in result.text
    assert "步骤数: 2" in result.text
    assert "a" * 25 in result.text

    worker.done.emit({"ok": False, "原因": "超时"})
    assert "✖ 未完成: 超时" in result.text

    worker.done.emit("boom")
    assert result.text == "返回异常: boom"


def test_run_learn_one_formats_both_branches(monkeypatch):
    _patch_workers(monkeypatch)
    host = Host(FakeTrunk())
    result = FakeResult()
    host._run_learn_one(result)
    worker = _last_worker()
    assert "学习闭环开始" in result.text
    worker.done.emit({"ok": True, "方向": "x", "主题": "y",
                      "入库条数": 3, "累计轮次": 5})
    assert "✔ 学习完成" in result.text
    assert "入库: 3 条" in result.text
    worker.done.emit({"ok": False, "原因": "没网"})
    assert "✖ 未完成: 没网" in result.text
    worker.done.emit(None)
    assert result.text == "返回异常: None"


def test_export_backup_cancel_and_confirm(monkeypatch):
    _patch_workers(monkeypatch)
    monkeypatch.setattr(bt.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))
    host = Host(FakeTrunk())
    result = FakeResult()
    host._export_backup_ui(result)
    assert result.text == "已取消"

    monkeypatch.setattr(bt.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: "D:/backup"))
    host._export_backup_ui(result)
    assert "导出备份中" in result.text
    _last_worker().done.emit("ok")
    assert host.trunk.calls == []


def test_run_auto_update_lazy_load_and_result(monkeypatch):
    _patch_workers(monkeypatch)

    class Au:
        def run_auto_update(self):
            return {"ok": True, "日志": ["a"], "目标": "t", "备份": "C:/b/x.zip"}

    trunk = FakeTrunk()
    host = Host(trunk)

    def fake_call(module, action):
        trunk.calls.append((module, action))
        trunk.modules["auto_updater"] = Au()
        return {"ok": True}

    trunk.call = fake_call
    result = FakeResult()
    host._run_auto_update_ui(result)
    worker = _last_worker()
    worker.done.emit(worker.args[0]())
    assert "闭环完成" in result.text
    assert "x.zip" in result.text
    assert trunk.calls == [("auto_updater", "run")]


def test_run_auto_update_reports_load_failure(monkeypatch):
    _patch_workers(monkeypatch)
    host = Host(FakeTrunk())
    result = FakeResult()
    host._run_auto_update_ui(result)
    worker = _last_worker()
    worker.done.emit(worker.args[0]())
    assert "auto_updater 加载失败" in result.text
    worker.done.emit({"ok": False, "原因": "沙盒未通过"})
    assert "✖ 未完成: 沙盒未通过" in result.text
    worker.done.emit("plain")
    assert result.text == "plain"


def test_module_button_gui_action(monkeypatch):
    _patch_workers(monkeypatch)
    shown = []
    monkeypatch.setattr(bt.QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a)))
    host = Host(FakeTrunk())
    called = []
    host.do_something = lambda: called.append(True)

    host._module_button_clicked("m", "gui:do_something")
    assert called == [True]

    host._module_button_clicked("m", "gui:missing")
    assert "本地面板未找到" in shown[-1][2]


def test_module_button_dict_and_plain_results(monkeypatch):
    _patch_workers(monkeypatch)
    shown = []
    monkeypatch.setattr(bt.QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a[2])))

    class FailingTrunk(FakeTrunk):
        def call(self, module, action):
            return {"ok": False, "error": "e" * 300}

    Host(FailingTrunk())._module_button_clicked("m", "act")
    assert "运行失败" in shown[-1]
    assert len(shown[-1]) <= 2020

    class SuccessTrunk(FakeTrunk):
        def call(self, module, action):
            return {"ok": True, "结果": 1}

    Host(SuccessTrunk())._module_button_clicked("m", "act")
    assert "结果: 1" in shown[-1]

    class PlainTrunk(FakeTrunk):
        def call(self, module, action):
            return "raw"

    Host(PlainTrunk())._module_button_clicked("m", "act")
    assert shown[-1] == "raw"


def test_install_component_success(monkeypatch, tmp_path):
    import pip._internal.cli.main as pip_main
    monkeypatch.setattr(pip_main, "main", lambda argv: 0)
    label, btn = FakeLabel(), FakeLabel()
    Host(base=str(tmp_path))._install_component("base64", "base64", label, btn)
    assert label.text == "✅ 已装"
    assert btn.text == "已安装"
    assert btn.enabled is True


def test_install_component_pip_failure(monkeypatch, tmp_path):
    import pip._internal.cli.main as pip_main
    monkeypatch.setattr(pip_main, "main", lambda argv: 2)
    label, btn = FakeLabel(), FakeLabel()
    Host(base=str(tmp_path))._install_component("base64", "base64", label, btn)
    assert label.text == "⚠ 安装失败(code=2)"
    assert btn.text == "重试"


def test_install_component_exception(monkeypatch, tmp_path):
    import pip._internal.cli.main as pip_main

    def boom(argv):
        raise RuntimeError("network down")

    monkeypatch.setattr(pip_main, "main", boom)
    label, btn = FakeLabel(), FakeLabel()
    Host(base=str(tmp_path))._install_component("base64", "base64", label, btn)
    assert "network down" in label.text
    assert btn.text == "重试"
    assert btn.enabled is True
