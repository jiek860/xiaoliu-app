# -*- coding: utf-8 -*-
""""跳过坏数据"类能力的可观测性测试

背景
----
方向 2 的审计发现：一批能力在读用户数据时 `except: pass` **跳过坏行**。
跳过本身是对的（一行坏了不该让整份报告读不出来），
**但不报跳过数就是错的** —— 用户看到"最近 7 天 0 条记录"，
分不清"真的没有"还是"文件坏了全被我跳过了"。

本文件守住这个区分：**结果里要能看到"跳过了多少"**。

另有 2 处经审计判定"该忍"（不是漏洞），也在这里钉住，防止被误改：
    gpu_detector.detect        没有 N 卡是正常结果
    crash_export 写提示文件     尽力而为，信息已在返回值里
"""
import json
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))


class _T:
    def __init__(self, base):
        self.base = base


# ── growth_report：读不到数据 vs 真的没数据 ──
def test_growth_report_distinguishes_read_failure_from_no_data():
    """读坏了要说"这是默认值"，不能让人以为"真的刚认识" """
    from core.growth_report import GrowthReport
    tmp = tempfile.mkdtemp(prefix="x6gr_")
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    p = os.path.join(tmp, "data", "personality.json")

    gr = GrowthReport(_T(tmp))
    r1 = gr.report()                      # 文件不存在
    assert "还没有人格数据" in str(r1.get("说明", "")), r1

    open(p, "w", encoding="utf-8").write("{坏掉的JSON")   # 文件坏了
    r2 = gr.report()
    assert r2.get("数据读取失败"), "读坏了却没报：%s" % r2
    assert "默认值" in str(r2.get("说明", "")), r2


# ── startup_optimizer：编译失败要报 ──
def test_startup_precompile_reports_failures():
    """编不过的文件要报出来，不能只报"成功 N 个" """
    from core.startup_optimizer import StartupOptimizer
    tmp = tempfile.mkdtemp(prefix="x6su_")
    for d in ("core", "gui", "modules/installed"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    # 一个能编的 + 一个编不过的
    open(os.path.join(tmp, "core", "ok.py"), "w", encoding="utf-8").write("x=1\n")
    open(os.path.join(tmp, "core", "bad.py"), "w",
         encoding="utf-8").write("def broken(:\n")

    so = StartupOptimizer(_T(tmp))
    r = so.precompile()
    assert r.get("预编译文件", 0) >= 1, r
    assert r.get("失败"), "编不过的文件没被报出来：%s" % r
    assert "bad.py" in str(r.get("失败明细")), r


# ── dream_system：坏行要报数 ──
def test_dream_recent_reports_skipped_lines():
    from core.dream_system import DreamSystem
    tmp = tempfile.mkdtemp(prefix="x6dr_")
    ds = DreamSystem(_T(tmp))
    os.makedirs(os.path.dirname(ds.path), exist_ok=True)
    with open(ds.path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"梦": "好梦"}, ensure_ascii=False) + "\n")
        f.write("坏行\n")
    out = ds.get_recent_dreams(10)
    assert any("读不出来" in str(d.get("说明", "")) for d in out
               if isinstance(d, dict)), "坏行没被报出来：%s" % out


# ── mood_report：日期坏了要报数 ──
def test_mood_report_reports_bad_dates():
    from core.mood_report import MoodReport
    tmp = tempfile.mkdtemp(prefix="x6mr_")
    mr = MoodReport(_T(tmp))
    os.makedirs(os.path.dirname(mr.path), exist_ok=True)
    with open(mr.path, "w", encoding="utf-8") as f:
        json.dump([{"date": "不是日期", "情绪": "开心"}], f, ensure_ascii=False)
    r = mr.report()
    assert r.get("日期异常") == 1, "坏日期没被报出来：%s" % r


# ── memory_organizer.check_conflicts：跳过数要报 ──
def test_check_conflicts_reports_skipped():
    from core.memory_organizer import MemoryOrganizer
    tmp = tempfile.mkdtemp(prefix="x6mc_")
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    p = os.path.join(tmp, "data", "memory_cards.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"facts": ["偏好:音乐 喜欢古典"]},
                           ensure_ascii=False) + "\n")
        f.write("坏行\n")
    org = MemoryOrganizer(_T(tmp))
    r = org.check_conflicts()
    assert r.get("跳过") == 1, "跳过数没报：%s" % r
    assert "冲突数" in r


# ── knowledge_qa：读不了的文档要报 ──
def test_knowledge_qa_search_reports_unreadable():
    from modules.installed.knowledge_qa import KnowledgeQnA
    tmp = tempfile.mkdtemp(prefix="x6kq_")
    qa = KnowledgeQnA(_T(tmp))
    # 造一个读不了的文件（用目录冒充文件，open 会失败）
    os.makedirs(os.path.join(qa.docs_dir, "假装是文档.txt"), exist_ok=True)
    r = qa.search_doc("随便")
    assert r.get("读不了") == 1, "读不了的文档没报：%s" % r


# ── 两处"该忍"的，钉住不让人误改 ──
def test_gpu_detect_silent_is_intentional():
    """没有 N 卡是正常结果 —— 不该因为"静默"就给它加告警"""
    from core.gpu_detector import GPUDetector
    tmp = tempfile.mkdtemp(prefix="x6gpu_")
    info = GPUDetector(_T(tmp)).detect()
    assert isinstance(info, dict), info
    assert "NVIDIA" in info, "返回值里要能看出有没有卡：%s" % info
    # 关键：不管有没有卡，都**不该抛异常**（原来静默就是为了这个）
