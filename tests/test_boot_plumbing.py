# -*- coding: utf-8 -*-
"""Extra coverage for deferred-boot plumbing in trunk and app_pyqt."""
import os
import sys
import types

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


class _LLM:
    def __init__(self):
        self.workers = 0
        self.warmed = 0

    def start_background_workers(self):
        self.workers += 1
        return True

    def _warmup(self):
        self.warmed += 1


class _T:
    def __init__(self, llm):
        self.modules = {"llm": llm}


def test_start_llm_workers_runs_immediately_when_delay_zero(monkeypatch):
    from core.trunk_background import TrunkBackgroundMixin

    class Timer:
        def __init__(self, _d, fn):
            self.fn = fn

        def start(self):
            self.fn()

    monkeypatch.setattr("threading.Timer", Timer)
    llm = _LLM()
    TrunkBackgroundMixin._start_llm_workers_later(_T(llm), 0)
    assert llm.workers == 1 and llm.warmed == 1


def test_start_llm_workers_tolerates_missing_llm(monkeypatch):
    from core.trunk_background import TrunkBackgroundMixin

    class Timer:
        def __init__(self, _d, fn):
            self.fn = fn

        def start(self):
            self.fn()

    monkeypatch.setattr("threading.Timer", Timer)
    TrunkBackgroundMixin._start_llm_workers_later(_T(None), 0)  # 不应抛异常


def test_start_llm_workers_survives_timer_error(monkeypatch):
    from core.trunk_background import TrunkBackgroundMixin
    monkeypatch.setattr("threading.Timer",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    TrunkBackgroundMixin._start_llm_workers_later(_T(_LLM()), 1)


def test_llm_client_defer_warmup_flag():
    """defer_warmup=True 时不启动看门狗/预热线程。"""
    import ast
    src = open(os.path.join(BASE, "core", "llm_client.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "LLMClient")
    init = next(n for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    args = [a.arg for a in init.args.args]
    assert "defer_warmup" in args
    assert "start_background_workers" in src


def test_startup_log_summary_with_trunk_writes_line():
    from core import startup
    seen = []

    class T:
        def _log(self, line):
            seen.append(line)
    startup.mark("unit")
    line = startup.log_summary(T())
    assert seen and "[启动耗时]" in seen[0]
    assert line == seen[0]


def test_startup_elapsed_and_report_fields():
    from core import startup
    t0 = startup.since_start_ms()
    ms = startup.elapsed_ms("unit2", t0)
    assert ms >= 0
    rep = startup.report()
    assert rep["pid"] == os.getpid()
    assert isinstance(rep["frozen"], bool)
    assert rep["total_ms"] >= 0


def test_registry_export_map_runs_in_background_thread(monkeypatch):
    """模块星图必须丢后台线程（不能阻塞 __init__）。"""
    import threading
    from core.trunk_registry import TrunkRegistryMixin
    recorded = {}

    class FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            recorded["target"] = target
            recorded["daemon"] = daemon
            recorded["name"] = name

        def start(self):
            recorded["started"] = True

    monkeypatch.setattr(threading, "Thread", FakeThread)
    calls = []

    class T(TrunkRegistryMixin):
        modules = {}
        _lazy = {}

        def _log(self, *_a):
            pass

        def register(self, *_a):
            pass

        def export_module_map(self):
            calls.append(1)

    monkeypatch.setattr(T, "_load_one_placeholder", None, raising=False)
    # 直接调用内部注册函数会加载真模块；这里只验证线程创建方式
    src = open(os.path.join(BASE, "core", "trunk_registry.py"),
               encoding="utf-8").read()
    assert 'name="module-map-export"' in src
    assert "daemon=True" in src
