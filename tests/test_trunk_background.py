# -*- coding: utf-8 -*-
"""core/trunk_background.py 的同名测试：启动预热、备份、后台队列和退出。

用假躯干（只实现 mixin 依赖的属性）离线验证，不连网、不起服务。
"""
import os
import queue
import threading
import time

import pytest

from core.trunk_background import TrunkBackgroundMixin


class FakeLLM:
    def __init__(self):
        self.started = False
        self.warmed = False

    def start_background_workers(self):
        self.started = True

    def _warmup(self):
        self.warmed = True


class FakeHost(TrunkBackgroundMixin):
    def __init__(self, base, modules=None, config=None):
        self.base = str(base)
        self.modules = dict(modules or {})
        self.config = dict(config or {})
        self.logs = []
        self.warns = []
        self.called = []
        self.saved = {}
        self._reply_n = 0
        self._private_mode = False
        self._last_use = {}
        self._lazy = {}
        self._pipeline = None
        self._use_pipeline = False
        self._bg_queue = queue.Queue()
        self._idle_queue = queue.Queue()

    def _log(self, msg):
        self.logs.append(str(msg))

    def _warn_user(self, msg, err=None):
        self.warns.append((msg, err))

    def call(self, name, action, *args, **kwargs):
        self.called.append((name, action))
        return {"ok": True}

    def _load_lazy(self, name):
        return self.modules.get(name)

    def save_config(self):
        self.saved["config"] = True

    def save_memory(self):
        self.saved["memory"] = True

    def _chat_busy(self):
        return False


class LoopHost(FakeHost):
    """只把 _bg（真实的后处理）换成记录，便于验证队列消费顺序。"""

    def _bg(self, user_input, answer):
        self.saved.setdefault("bg", []).append((user_input, answer))


class _Registry:
    def start_run(self, *a, **k):
        return None

    def finish_run(self, *a, **k):
        return None


@pytest.fixture(autouse=True)
def _no_registry(monkeypatch):
    monkeypatch.setattr("core.agent_harness.get_run_registry",
                        lambda: _Registry())


def test_start_llm_workers_later_runs_in_timer(tmp_path):
    llm = FakeLLM()
    host = FakeHost(tmp_path, modules={"llm": llm})
    host._start_llm_workers_later(delay=0)
    deadline = time.time() + 2
    while time.time() < deadline and not (llm.started and llm.warmed):
        time.sleep(0.02)
    assert llm.started and llm.warmed


def test_start_llm_workers_without_llm_is_noop(tmp_path):
    host = FakeHost(tmp_path)
    host._start_llm_workers_later(delay=0)
    time.sleep(0.1)
    assert host.modules == {}


def test_init_pipeline_success(tmp_path, monkeypatch):
    class DummyPipeline:
        def __init__(self, trunk):
            self.trunk = trunk

    monkeypatch.setattr("core.pipeline.ReplyPipeline", DummyPipeline)
    host = FakeHost(tmp_path)
    host._init_pipeline()
    assert host._use_pipeline is True
    assert host._pipeline is not None
    assert "躯干启动" in host.logs


def test_init_pipeline_falls_back_on_error(tmp_path, monkeypatch):
    class BrokenPipeline:
        def __init__(self, trunk):
            raise RuntimeError("坏了")

    monkeypatch.setattr("core.pipeline.ReplyPipeline", BrokenPipeline)
    host = FakeHost(tmp_path)
    host._init_pipeline()
    assert host._use_pipeline is False
    assert host._pipeline is None
    assert any("Pipeline 初始化失败" in x for x in host.logs)


def test_warmup_skips_ollama_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("core.trunk_background.time.sleep", lambda s: None)

    def boom(*a, **k):
        raise OSError("连不上")

    monkeypatch.setattr("requests.post", boom)
    host = FakeHost(tmp_path)
    host._warmup()
    assert any("Ollama warmup skip" in x for x in host.logs)


def test_warmup_loads_vector_store(tmp_path, monkeypatch):
    monkeypatch.setattr("core.trunk_background.time.sleep", lambda s: None)
    monkeypatch.setattr("requests.post", lambda *a, **k: None)
    host = FakeHost(tmp_path, modules={"vector_store": object()})
    host._warmup()
    assert any("Vector store warmup done" in x for x in host.logs)


def test_auto_backup_runs_when_no_recent(tmp_path, monkeypatch):
    calls = []

    class FakeBackup:
        def __init__(self, trunk):
            self.trunk = trunk

        def _last_backup_path(self):
            return ""

        def backup_now(self, **kw):
            calls.append(kw)
            return {"成功": True, "备份到": "backups/b1", "增量": True}

    monkeypatch.setattr("core.backup.Backup", FakeBackup)
    # conftest 默认设了 X6_NO_AUTO_BACKUP=1（测试不写真实备份），
    # 这几条要验备份流程本身，得先把它摘掉
    monkeypatch.delenv("X6_NO_AUTO_BACKUP", raising=False)
    host = FakeHost(tmp_path)
    host._auto_backup()
    # 必须把节流参数交给 backup_now —— 判断要在它的锁内做
    assert calls == [{"force": False,
                      "min_gap_h": host._AUTO_BACKUP_MIN_GAP_H}]
    assert any("启动备份完成" in x for x in host.logs)


def test_auto_backup_skips_when_recent(tmp_path, monkeypatch):
    recent = tmp_path / "last.bak"
    recent.write_text("x", encoding="utf-8")

    class FakeBackup:
        def __init__(self, trunk):
            pass

        def _last_backup_path(self):
            return str(recent)

        def backup_now(self, **kw):
            raise AssertionError("不该再备份")

    monkeypatch.setattr("core.backup.Backup", FakeBackup)
    monkeypatch.delenv("X6_NO_AUTO_BACKUP", raising=False)
    host = FakeHost(tmp_path)
    host._auto_backup()
    assert host.logs == []


def test_auto_backup_respects_env_switch(tmp_path, monkeypatch):
    """X6_NO_AUTO_BACKUP=1 时连 Backup 都不该建（测试/CI 不写真实磁盘）"""
    monkeypatch.setenv("X6_NO_AUTO_BACKUP", "1")

    class FakeBackup:
        def __init__(self, trunk):
            raise AssertionError("不该建 Backup")

    monkeypatch.setattr("core.backup.Backup", FakeBackup)
    host = FakeHost(tmp_path)
    host._auto_backup()
    assert host.logs == []


def test_auto_backup_handles_throttle_skip(tmp_path, monkeypatch):
    """backup_now 自己判断"太近了"时不写"启动备份未完成"的错误日志"""
    class FakeBackup:
        def __init__(self, trunk):
            pass

        def _last_backup_path(self):
            return ""

        def backup_now(self, **kw):
            return {"成功": False, "跳过": True, "原因": "太近了"}

    monkeypatch.setattr("core.backup.Backup", FakeBackup)
    monkeypatch.delenv("X6_NO_AUTO_BACKUP", raising=False)
    host = FakeHost(tmp_path)
    host._auto_backup()
    assert host.logs == []


def test_backup_is_recent_threshold(tmp_path):
    p = tmp_path / "b.bak"
    p.write_text("x", encoding="utf-8")
    host = FakeHost(tmp_path)
    assert host._backup_is_recent(str(p)) is True
    old = time.time() - (host._AUTO_BACKUP_MIN_GAP_H + 1) * 3600
    os.utime(str(p), (old, old))
    assert host._backup_is_recent(str(p)) is False
    assert host._backup_is_recent(str(tmp_path / "missing.bak")) is False


def test_defer_to_idle_puts_task(tmp_path):
    host = FakeHost(tmp_path)
    host._defer_to_idle(lambda: None)
    assert host._idle_queue.qsize() == 1


def test_defer_to_idle_warns_when_backlog(tmp_path):
    class FullQueue:
        def qsize(self):
            return 201

        def put(self, item):
            raise AssertionError("积压时不该再入队")

    host = FakeHost(tmp_path)
    host._idle_queue = FullQueue()
    host._defer_to_idle(lambda: None)
    assert host.warns and "积压" in host.warns[0][0]


def test_idle_worker_runs_task_then_exits(tmp_path):
    host = FakeHost(tmp_path)
    done = []
    host._idle_queue.put(lambda: done.append(1))
    host._idle_queue.put(None)
    host._idle_worker()
    assert done == [1]


def test_bg_respects_private_mode(tmp_path):
    class VS:
        def add(self, *a):
            raise AssertionError("隐私模式不该写向量")

    host = FakeHost(tmp_path, modules={"vector_store": VS()})
    host._private_mode = True
    host._bg("你好", "在")
    assert host.saved.get("bg") is None
    assert any("隐私模式" in x for x in host.logs)


def test_bg_writes_vector_and_graph(tmp_path):
    class VS:
        def __init__(self):
            self.added = []

        def add(self, u, a):
            self.added.append((u, a))

    class KG:
        def __init__(self):
            self.dialogs = []

        def add_dialog(self, u, a):
            self.dialogs.append((u, a))

    vs, kg = VS(), KG()
    host = FakeHost(tmp_path, modules={"vector_store": vs,
                                       "knowledge_graph": kg})
    host._bg("今天好累", "先歇会儿")
    assert vs.added == [("今天好累", "先歇会儿")]
    assert kg.dialogs == [("今天好累", "先歇会儿")]


def test_bg_loop_processes_then_stops(tmp_path):
    host = LoopHost(tmp_path)
    host._bg_queue.put(("hi", "yo"))
    host._bg_queue.put(None)
    host._bg_loop()
    assert host.saved.get("bg") == [("hi", "yo")]


def test_shutdown_saves_and_stops_services(tmp_path):
    class VS:
        def __init__(self):
            self.saved = False

        def save(self):
            self.saved = True

    class MC:
        def stop(self):
            return "ok"

    class MS:
        def __init__(self):
            self.stopped = False

        def stop_http(self):
            self.stopped = True

    vs, ms = VS(), MS()
    host = FakeHost(tmp_path, modules={"vector_store": vs,
                                       "mcp_client": MC(),
                                       "mcp_server": ms})
    host.shutdown()
    assert host.saved.get("config") and host.saved.get("memory")
    assert vs.saved and ms.stopped
    assert any("退出完成" in x for x in host.logs)
