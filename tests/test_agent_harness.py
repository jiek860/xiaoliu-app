# -*- coding: utf-8 -*-
"""Agent Harness / 活动注册表 / 统一错误信封测试。"""
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.agent_harness import (  # noqa: E402
    RunRegistry, get_run_registry, normalize_error, reset_run_registry,
    TERMINAL_STATUSES,
)

from PyQt5.QtCore import QUrl  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
_app = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("text,code", [
    ("模型未配置，请去设置", "MODEL_NOT_CONFIGURED"),
    ("权限被拒绝：未授权", "PERMISSION_DENIED"),
    ("网络策略拒绝 network denied", "NETWORK_DENIED"),
    ("工具不存在 not found", "TOOL_NOT_FOUND"),
    ("任务超时 timeout", "TASK_TIMEOUT"),
    ("测试失败 AssertionError", "TEST_FAILED"),
    ("文件已被修改 hash 冲突", "FILE_CONFLICT"),
    ("普通失败 failed", "TASK_FAILED"),
])
def test_normalize_error_has_single_next_action(text, code):
    env = normalize_error(text)
    assert env["ok"] is False
    assert env["code"] == code
    assert env["title"]
    assert env["message"]
    assert env["next_action"]["id"]
    assert env["next_action"]["label"]
    assert env["technical_detail"]


def test_run_registry_lifecycle_and_subscriber():
    reg = RunRegistry()
    events = []
    reg.subscribe(lambda run, event: events.append((event, run.get("run_id"))))
    run = reg.start_run("job", "测试活动", run_id="r1", budget={"max_seconds": 60})
    assert reg.active_count() == 1
    reg.update_run("r1", current_step="执行中", progress=0.5)
    reg.finish_run("r1", "completed")
    assert reg.active_count() == 0
    assert reg.get_run("r1")["status"] == "completed"
    assert [e for e, _ in events] == ["started", "updated", "updated"]


def test_registry_upsert_task_has_progress_and_error():
    reg = RunRegistry()
    task = {
        "id": "t1", "goal": "整理资料", "status": "failed",
        "trace_id": "trace_t1", "budget": {"max_seconds": 300},
        "usage": {"tool_calls": 2}, "error": "权限被拒绝",
        "steps": [
            {"id": "s1", "title": "读取", "status": "done"},
            {"id": "s2", "title": "写入", "status": "failed"},
        ],
    }
    run = reg.upsert_task(task, "step_failed", "写入")
    assert run["run_id"] == "task:t1"
    assert run["task_id"] == "t1"
    assert run["progress"] == 0.5
    assert run["error"] == "权限被拒绝"
    assert run["finished_at"] > 0


def test_task_runtime_emits_into_registry():
    from tests.conftest import make_trunk
    reset_run_registry()
    trunk = make_trunk()
    rt = trunk.get_task_runtime()
    task = rt.create("注册表任务")
    run = get_run_registry().get_run("task:" + task["id"])
    assert run is not None
    assert run["title"] == "注册表任务"
    assert run["status"] in ("pending", "planning", "running")


def test_activity_center_dialog_constructs():
    from tests.conftest import make_trunk
    from gui.activity_center_dialog import ActivityCenterDialog
    reset_run_registry()
    trunk = make_trunk()
    trunk.get_task_runtime().create("活动中心测试")
    w = ActivityCenterDialog(trunk)
    try:
        assert w.windowTitle()
        assert w.list.count() >= 1
    finally:
        w.close()


def _worker_trunk(tmp_path, task_loop=None, learning_loop=None, tts=None):
    class _Trunk:
        base = str(tmp_path)

        def __init__(self):
            self.modules = {}
            self.config = {}

        def call(self, *_a, **_k):
            return None

        def _log(self, *_a, **_k):
            return None

        def _load_lazy(self, name):
            if name == "tts":
                return tts
            return None

    t = _Trunk()
    if task_loop is not None:
        t.modules["task_loop"] = task_loop
    if learning_loop is not None:
        t.modules["learning_loop"] = learning_loop
    return t


def test_four_worker_types_register_start_and_finish(tmp_path):
    """四类 worker 启动/完成都进同一个活动注册表（活动中心数据源）。"""
    from gui.workers import BgWorker, LearnWorker, TaskWorker, TTSWorker

    class _TaskLoop:
        def run(self, goal):
            return {"ok": True}

    class _LearnLoop:
        def run(self):
            return {"ok": True}

    class _TTS:
        def speak(self, text):
            return True

    reset_run_registry()
    trunk = _worker_trunk(tmp_path, _TaskLoop(), _LearnLoop(), _TTS())
    TaskWorker(trunk, "整理资料").run()
    LearnWorker(trunk).run()
    BgWorker(lambda: 1, "索引重建", trunk=trunk).run()
    TTSWorker(trunk, "你好").run()

    runs = get_run_registry().list_runs(limit=50)
    kinds = {r["kind"] for r in runs}
    assert {"task_loop", "learning", "background", "tts"} <= kinds
    assert all(r["status"] == "completed" for r in runs)
    assert all(r["metadata"].get("log_path") for r in runs)
    # 同类 worker 连开两次不能互相覆盖
    TaskWorker(trunk, "再整理一次").run()
    assert len(get_run_registry().list_runs(limit=50)) == 5


def test_four_worker_types_record_failure_reason(tmp_path):
    """四类 worker 失败时都写入 status=failed 和失败原因。"""
    from gui.workers import BgWorker, LearnWorker, TaskWorker, TTSWorker

    class _TaskLoop:
        def run(self, goal):
            raise RuntimeError("任务炸了")

    class _LearnLoop:
        def run(self):
            raise RuntimeError("学习炸了")

    class _TTS:
        def speak(self, text):
            raise RuntimeError("语音炸了")

    def _boom():
        raise RuntimeError("后台炸了")

    reset_run_registry()
    trunk = _worker_trunk(tmp_path, _TaskLoop(), _LearnLoop(), _TTS())
    TaskWorker(trunk, "整理资料").run()
    LearnWorker(trunk).run()
    BgWorker(_boom, "索引重建", trunk=trunk).run()
    TTSWorker(trunk, "你好").run()

    runs = get_run_registry().list_runs(limit=50)
    assert len(runs) == 4
    assert all(r["status"] == "failed" for r in runs)
    assert all(r["error"] for r in runs)


def test_registry_retention_keeps_recent_terminal_only():
    """保留策略：只淘汰已结束的旧记录，运行中的不淘汰。"""
    reg = RunRegistry(max_runs=25)
    reg.start_run("job", "活跃活动", run_id="keep-active")
    for i in range(30):
        reg.start_run("job", "活动%d" % i, run_id="r%d" % i)
        reg.finish_run("r%d" % i, "completed")
    runs = reg.list_runs(limit=100)
    assert len(runs) <= 25
    assert reg.get_run("keep-active") is not None
    assert reg.get_run("r0") is None          # 最旧的已结束记录被回收
    assert reg.get_run("r29") is not None     # 最近完成记录还在


def test_activity_center_groups_and_shows_failure_log(tmp_path):
    """活动中心分组展示 运行中 / 失败原因 / 最近完成，并能查看日志。"""
    from gui.activity_center_dialog import ActivityCenterDialog

    class _FakeRuntime:
        def list_tasks(self):
            return []

        def pause(self, task_id):
            return {"ok": True}

        def resume(self, task_id):
            return {"ok": True}

        def cancel(self, task_id):
            return {"ok": True}

    class _FakeTrunk:
        base = str(tmp_path)

        def get_task_runtime(self):
            return _FakeRuntime()

    reset_run_registry()
    log = tmp_path / "app.log"
    log.write_text("ERROR 网络被拒绝\nboom-detail", encoding="utf-8")
    reg = get_run_registry()
    reg.start_run("chat", "正在聊天", run_id="run-active")
    reg.start_run("background", "索引重建", run_id="run-fail",
                  metadata={"log_path": str(log)})
    reg.finish_run("run-fail", "failed", "网络被拒绝")
    reg.start_run("learning", "学习闭环", run_id="run-ok")
    reg.finish_run("run-ok", "completed")

    w = ActivityCenterDialog(_FakeTrunk())
    try:
        texts = [w.list.item(i).text() for i in range(w.list.count())]
        assert any(t.startswith("运行中（") for t in texts)
        assert any(t.startswith("失败（") for t in texts)
        assert any(t.startswith("最近完成（") for t in texts)
        assert any("失败原因：" in t for t in texts)
        w._show_log("run-fail")
        assert "boom-detail" in w.detail.toPlainText()
        w._on_anchor(QUrl("activity://detail?run=run-fail"))
        assert "失败原因" in w.detail.toPlainText() or "错误" in w.detail.toPlainText()
    finally:
        w.close()


def test_update_check_registers_run(tmp_path):
    """检查更新失败也会进活动中心数据源，并带失败原因。"""
    from gui.update_dialog import UpdateDialog

    class _Updater:
        def check_update(self, url):
            raise AssertionError("没有配置更新源时不应发起请求")

    class _Trunk:
        base = str(tmp_path)
        config = {}

        def _load_lazy(self, name):
            return _Updater() if name == "auto_updater" else None

    reset_run_registry()
    dlg = UpdateDialog(_Trunk())
    try:
        dlg._check_update()
    finally:
        dlg.close()
    runs = get_run_registry().list_runs(limit=20)
    assert len(runs) == 1
    assert runs[0]["kind"] == "update_check"
    assert runs[0]["status"] == "failed"
    assert "update_manifest_url" in runs[0]["error"]


def test_theme_manager_persists_appearance(tmp_path):
    from gui.theme_manager import ThemeManager
    base = str(tmp_path)
    tm = ThemeManager(base)
    assert tm.appearance["theme"] == "system"
    tm.set_options(theme="dark", font_size=16, density="compact")
    tm2 = ThemeManager(base)
    assert tm2.appearance["theme"] == "dark"
    assert tm2.appearance["font_size"] == 16
    assert tm2.appearance["density"] == "compact"
    assert tm2.stylesheet()


def test_window_state_roundtrip(tmp_path):
    from PyQt5.QtWidgets import QWidget
    from gui.window_state import WindowStateManager
    base = str(tmp_path)
    w = QWidget()
    w.resize(1111, 777)
    mgr = WindowStateManager(base)
    mgr.save(w)
    w2 = QWidget()
    mgr2 = WindowStateManager(base)
    assert mgr2.restore(w2) is True
    assert w2.size().width() >= 800
    assert w2.size().height() >= 600
    w.close()
    w2.close()


def test_feedback_state_components_construct():
    from gui.feedback_states import LoadingWidget, EmptyStateWidget, ErrorCardWidget
    loading = LoadingWidget("加载中")
    empty = EmptyStateWidget("暂无内容", "下一步", "开始", lambda: None)
    error = ErrorCardWidget("权限被拒绝")
    try:
        assert loading.label.text() == "加载中"
        assert error.env["code"] == "PERMISSION_DENIED"
    finally:
        for w in (loading, empty, error):
            w.close()


# ──────────────────────────────────────────────────────────────
# 语音合成 / 更新回滚入口
# ──────────────────────────────────────────────────────────────
def test_tts_worker_emits_synthesized_path(tmp_path):
    """TTSWorker.done 原来从来没 emit，接到播放器上等于没有声音。"""
    from gui.workers import TTSWorker

    class _TTS:
        def speak(self, text, autoplay=False):
            assert autoplay is False, "应由调用方播放，避免双重播放"
            return {"ok": True, "path": "/tmp/朗读.mp3"}

    reset_run_registry()
    got = []
    w = TTSWorker(_worker_trunk(tmp_path, tts=_TTS()), "你好")
    w.done.connect(got.append)
    w.run()
    assert got == ["/tmp/朗读.mp3"]
    assert get_run_registry().list_runs(limit=5)[0]["status"] == "completed"


def test_tts_worker_old_signature_and_failure_are_honest(tmp_path):
    from gui.workers import TTSWorker

    class _OldTTS:
        def speak(self, text):
            return {"ok": False, "error": "没装 edge-tts"}

    reset_run_registry()
    got = []
    w = TTSWorker(_worker_trunk(tmp_path, tts=_OldTTS()), "你好")
    w.done.connect(got.append)
    w.run()
    assert got == [""], "合成失败要发空路径，调用方据此降级成文字"
    run = get_run_registry().list_runs(limit=5)[0]
    assert run["status"] == "failed" and "edge-tts" in run["error"]


def test_update_dialog_history_shows_rollback_state(tmp_path):
    """更新历史要带备份目录，界面才能判断"可回滚 / 备份已清理"。"""
    import json
    import os
    from gui.update_dialog import UpdateDialog

    base = str(tmp_path)
    os.makedirs(os.path.join(base, "updates"), exist_ok=True)
    bk = os.path.join(base, "backups", "backup_1")
    os.makedirs(bk)
    hist = os.path.join(base, "updates", "update_history.jsonl")
    with open(hist, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": "2026-10-20 10:00:00", "from": "v0",
                            "to": "v1", "files": 2}) + "\n")
        f.write(json.dumps({"time": "2026-10-26 10:00:00", "from": "v1",
                            "to": "v2", "files": 3, "backup": bk}) + "\n")

    class T:
        pass

    trunk = T()
    trunk.base = base
    trunk.config = {}
    trunk._load_lazy = lambda name: None
    d = UpdateDialog(trunk)
    try:
        assert len(d._entries) == 2
        assert "可回滚" in d.history_list.item(0).text()
        assert "无备份记录" in d.history_list.item(1).text()
    finally:
        d.close()

