# -*- coding: utf-8 -*-
"""低覆盖模块补测：记忆闭环、学习闭环、调度器、深度搜索、多模态。"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.memory_loop import MemoryPipeline  # noqa: E402
from modules.installed.learning_loop import LearningPipeline  # noqa: E402
from modules.installed.scheduler import Scheduler  # noqa: E402
from modules.installed.deep_search import DeepSearch  # noqa: E402
from modules.installed.multimodal import Multimodal  # noqa: E402


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {}
        self.modules = {}
        self.logs = []
        self.calls = []

    def _log(self, msg):
        self.logs.append(msg)

    def rule(self, _name, default=True):
        return default

    def call(self, module, method, *args, **kwargs):
        self.calls.append((module, method, args, kwargs))
        if module == "memory_cards":
            return {"已总结": True}
        if module == "forgetting_curve" and method == "due_review":
            return {"项目": ["key1"]}
        if module == "vector_store" and method == "search":
            return [{"text": "相关记忆"}]
        if module == "vector_store" and method == "add":
            return {"ok": True}
        if module == "deep_search" and method == "search":
            return {"结果": [{"标题": "T", "链接": "http://x", "摘要": "S"}]}
        return {"ok": True}

    def kb_add(self, *_a, **_k):
        return {"ok": True}


def test_memory_loop_full_cycle(tmp_path):
    m = MemoryPipeline(_Trunk(tmp_path))
    assert m._scene("python 报错") == "编程"
    assert m._scene("今天天气") == "闲聊"
    assert m._scene("普通") == "日常"
    scene = m.remember_scene("python 代码", "好的")
    assert scene == "编程"
    assert m.episodic(scene="编程")
    assert m.recall("Python")
    r = m.run("我喜欢 Python", "好的")
    assert r["ok"] and r["本次复习"] == 1 and r["检索增强"] == 1
    assert m.compress_old_memories(0)["压缩数"] >= 1
    assert m.recall_from_month_ago("Python")["找到"] >= 1
    assert "串联" in m.link_memories("Python")
    assert m.forget_old_memories(0)["遗忘后"] >= 0
    assert m._age_days("bad") == 0.0


def test_learning_loop_cycle_and_control(tmp_path, monkeypatch):
    t = _Trunk(tmp_path)
    lp = LearningPipeline(t)
    d, topic = lp.collect_gap()
    assert d and topic
    assert lp.fetch("Python")[0]["标题"] == "T"
    n = lp.store(d, topic, lp.fetch("Python"))
    assert n == 1
    rep = lp.report(d, topic, n)
    assert rep["入库条数"] == 1
    assert lp.run("Python 测试")["ok"] is True
    assert lp.status()["连续学习运行中"] is False
    monkeypatch.setattr(
        "threading.Thread",
        lambda *a, **k: type("T", (), {"start": lambda self: None})())
    assert "启动" in lp.start_continuous(interval=0)
    lp.stop_continuous()
    assert isinstance(lp.recommend(), str)
    assert lp.feedback("Python", True)["已记录"] == "正面反馈"


def test_scheduler_basics(tmp_path):
    t = _Trunk(tmp_path)
    s = Scheduler(t)
    assert "运行中" in s.status()
    ran = []
    s._safe_run("test", lambda: ran.append(1))
    assert ran == [1]
    assert isinstance(s.run(), dict)
    s.start()
    assert s.running is True
    s.stop()
    assert s.running is False
    assert s._safe_run("失败", lambda: (_ for _ in ()).throw(RuntimeError("x"))) is False


def test_deep_search_parsers_and_search(tmp_path, monkeypatch):
    t = _Trunk(tmp_path)
    ds = DeepSearch(t)
    assert ds._clean("<b>a</b>&amp;") == "a&amp;"
    assert ds._is_code_query("Python 报错 stacktrace")
    html = '<li class="b_algo"><h2><a href="http://a">标题</a></h2><p>摘要</p></li>'
    monkeypatch.setattr(ds, "_get", lambda *a, **k: html)
    assert isinstance(ds._bing("q"), list)
    assert isinstance(ds._sogou("q"), list)
    assert isinstance(ds._ddg("q"), list)
    assert ds._github("q") is None or isinstance(ds._github("q"), list)
    r = ds.search("Python 报错")
    assert isinstance(r, dict)
    assert ds.run("test") is not None


def test_multimodal_missing_files_and_stats(tmp_path):
    t = _Trunk(tmp_path)
    mm = Multimodal(t)
    assert mm.describe_image(str(tmp_path / "missing.png"))["错误"] == "图片不存在"
    assert mm.transcribe_audio(str(tmp_path / "missing.wav"))["错误"] == "音频文件不存在"
    assert mm.describe_video(str(tmp_path / "missing.mp4"))["错误"]
    assert mm.capture_camera(str(tmp_path / "x.jpg"))["错误"]
    assert mm.find_object("cat")["错误"]
    mm.history.append({"x": 1})
    assert isinstance(mm.get_history(), list)
    mm.clear_history()
    assert mm.stats()["历史记录数"] == 0
    assert "图片描述次数" in mm.run()

def test_forgetting_curve_migrates_legacy_list(tmp_path):
    """旧版 forgetting.json 是 list，不能让 remember/due_review 崩。"""
    import json
    from modules.installed.forgetting_curve import ForgettingCurve

    p = tmp_path / "data" / "forgetting.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([
        {"text": "旧记忆", "time": 1, "imp": 0.5, "review": 2},
        {"text": "旧记忆", "time": 2, "imp": 0.5, "review": 1},
    ], ensure_ascii=False), encoding="utf-8")
    fc = ForgettingCurve(_Trunk(tmp_path))
    assert isinstance(fc.memory, dict)
    assert len(fc.memory) == 2
    assert fc.remember("新记忆", "内容")["记住"] == "新记忆"
    assert fc.due_review()["待复习"] >= 1
    assert isinstance(json.loads(p.read_text(encoding="utf-8")), dict)
