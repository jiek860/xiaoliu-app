# -*- coding: utf-8 -*-
"""B4：报告 / 统计组（mood_report / growth_report / stats_report）

守住三件事
----------
1. 「**真的 0 条**」和「**读不出来**」必须能区分（这是本组的核心改造）。
2. 报告类能力只读：``report()`` 不许写盘（能力表里标的 readonly=True）。
3. 参数越界要夹回合理范围，不能让 days=0 / count=0 变成「返回全部」。
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))


class _T:
    def __init__(self, base):
        self.base = str(base)


@pytest.fixture
def tmp_base(tmp_path):
    (tmp_path / "data").mkdir()
    return tmp_path


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# mood_report
# ══════════════════════════════════════════════════════════════
def test_mood_report_empty_is_zero_not_failure(tmp_base):
    from core.mood_report import MoodReport
    r = MoodReport(_T(tmp_base)).report()
    assert r["ok"] is True
    assert r["记录数"] == 0
    assert "数据读取失败" not in r


def test_mood_report_read_failure_is_reported(tmp_base):
    from core.mood_report import MoodReport
    (tmp_base / "data" / "mood_history.json").write_text("{坏的", encoding="utf-8")
    r = MoodReport(_T(tmp_base)).report()
    assert r.get("数据读取失败"), "读坏了却报成没数据：%s" % r
    assert "数据读不出来" in r.get("说明", "")


def test_mood_report_counts_recent_and_clamps_days(tmp_base):
    from core.mood_report import MoodReport
    today = datetime.now().strftime("%Y-%m-%d")
    old = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    _write_json(tmp_base / "data" / "mood_history.json", [
        {"date": today, "time": "09:00", "情绪": "开心"},
        {"date": today, "time": "15:00", "情绪": "开心"},
        {"date": old, "情绪": "难过"},
    ])
    mr = MoodReport(_T(tmp_base))
    r = mr.report(days=7)
    assert r["记录数"] == 2, r
    assert r["主导情绪"][0]["情绪"] == "开心"
    assert r["主导情绪"][0]["次数"] == 2
    # days 越界要夹回，不炸
    assert mr.report(days=0)["天数"] == 1
    assert mr.report(days="abc")["天数"] == 7
    assert mr.report(days=99999)["天数"] == 365


def test_mood_report_falls_back_to_personality_history(tmp_base):
    """老数据只在 personality.json 的 mood_history 里（只有 HH:MM）"""
    from core.mood_report import MoodReport
    _write_json(tmp_base / "data" / "personality.json", {
        "mood_history": [{"情绪": "平静", "时间": "09:30"}],
    })
    r = MoodReport(_T(tmp_base)).report()
    assert r["记录数"] == 1, r
    assert r["主导情绪"][0]["情绪"] == "平静"


def test_mood_report_reports_bad_dates(tmp_base):
    from core.mood_report import MoodReport
    _write_json(tmp_base / "data" / "mood_history.json",
                [{"date": "不是日期", "情绪": "开心"}])
    r = MoodReport(_T(tmp_base)).report()
    assert r["日期异常"] == 1, r


def test_mood_report_export_md(tmp_base):
    from core.mood_report import MoodReport
    _write_json(tmp_base / "data" / "mood_history.json",
                [{"date": datetime.now().strftime("%Y-%m-%d"), "情绪": "开心"}])
    mr = MoodReport(_T(tmp_base))
    out = tmp_base / "mood.md"
    res = mr.export_md(7, str(out))
    assert res["ok"] is True
    assert "情绪日报" in out.read_text(encoding="utf-8")


def test_mood_report_is_readonly(tmp_base):
    """report() 不许写盘（否则能力表的 readonly 标注就是假的）"""
    from core.mood_report import MoodReport
    MoodReport(_T(tmp_base)).report()
    assert not (tmp_base / "data" / "mood_history.json").exists()


# ── 写入侧接线：log_mood 必须写进 MoodReport 读的那个文件 ──
def _pers(tmp_base):
    from core.personality_state import PersonalityStateMixin

    class _Pers(PersonalityStateMixin):
        def __init__(self, path):
            self.path = path
            self.data = self._load()

    return _Pers(str(tmp_base / "data" / "personality.json"))


def test_log_mood_writes_dated_file(tmp_base):
    pers = _pers(tmp_base)
    assert pers.log_mood("开心") == "开心"
    rows = json.loads((tmp_base / "data" / "mood_history.json")
                      .read_text(encoding="utf-8"))
    assert rows[-1]["date"] == datetime.now().strftime("%Y-%m-%d")
    assert rows[-1]["情绪"] == "开心"


def test_update_emotion_logs_only_when_mood_changes(tmp_base):
    pers = _pers(tmp_base)
    pers.update_emotion("")
    first = json.loads((tmp_base / "data" / "mood_history.json")
                       .read_text(encoding="utf-8"))
    assert len(first) == 1, "第一次算情绪就该记一条"
    pers.update_emotion("")        # 同一时段、同样的输入：心情没变
    again = json.loads((tmp_base / "data" / "mood_history.json")
                       .read_text(encoding="utf-8"))
    assert len(again) == 1, "心情没变不该重复记"


def test_mood_report_reads_what_log_mood_writes(tmp_base):
    from core.mood_report import MoodReport
    _pers(tmp_base).log_mood("焦虑")
    r = MoodReport(_T(tmp_base)).report()
    assert r["记录数"] == 1, r
    assert r["主导情绪"][0]["情绪"] == "焦虑"


# ══════════════════════════════════════════════════════════════
# growth_report
# ══════════════════════════════════════════════════════════════
def test_growth_report_no_data_vs_read_failure(tmp_base):
    from core.growth_report import GrowthReport
    gr = GrowthReport(_T(tmp_base))
    r1 = gr.report()
    assert "还没有人格数据" in r1["说明"]

    (tmp_base / "data" / "personality.json").write_text("{坏的", encoding="utf-8")
    r2 = gr.report()
    assert r2.get("数据读取失败")
    assert "默认值" in r2["说明"]


def test_growth_report_is_readonly_but_checkpoint_writes(tmp_base):
    from core.growth_report import GrowthReport
    _write_json(tmp_base / "data" / "personality.json", {
        "birth_time": time.time() - 100 * 86400,
        "relation_stage": 2,
        "memory_count": 50,
    })
    gr = GrowthReport(_T(tmp_base))
    gr.report()
    assert not (tmp_base / "data" / "growth_history.json").exists(), \
        "report() 不该写盘"

    assert gr.checkpoint()["ok"] is True
    rows = json.loads((tmp_base / "data" / "growth_history.json")
                      .read_text(encoding="utf-8"))
    assert len(rows) == 1 and rows[0]["关系阶段"] == 2
    # 同一天再存一次只更新，不叠加
    gr.checkpoint()
    rows = json.loads((tmp_base / "data" / "growth_history.json")
                      .read_text(encoding="utf-8"))
    assert len(rows) == 1, rows


def test_growth_trend_compares_with_baseline(tmp_base):
    from core.growth_report import GrowthReport
    old_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    _write_json(tmp_base / "data" / "growth_history.json", [{
        "date": old_date, "认识天数": 60, "关系阶段": 1, "记忆数": 10,
    }])
    _write_json(tmp_base / "data" / "personality.json", {
        "birth_time": time.time() - 100 * 86400,
        "relation_stage": 2,
        "memory_count": 40,
    })
    tr = GrowthReport(_T(tmp_base)).trend(30)
    assert tr["基准日期"] == old_date
    assert tr["关系阶段"]["变化"] == 1
    assert tr["记忆数"]["变化"] == 30


def test_growth_trend_says_not_enough_history(tmp_base):
    from core.growth_report import GrowthReport
    tr = GrowthReport(_T(tmp_base)).trend(30)
    assert "不足" in tr["说明"]


def test_growth_export_md(tmp_base):
    from core.growth_report import GrowthReport
    _write_json(tmp_base / "data" / "personality.json", {
        "birth_time": time.time() - 30 * 86400, "relation_stage": 1,
        "memory_count": 12,
    })
    gr = GrowthReport(_T(tmp_base))
    out = tmp_base / "growth.md"
    assert gr.export_md(30, str(out))["ok"] is True
    text = out.read_text(encoding="utf-8")
    assert "成长报告" in text and "认识天数" in text


# ══════════════════════════════════════════════════════════════
# stats_report
# ══════════════════════════════════════════════════════════════
def _make_chats(db, rows):
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, username TEXT,"
                 " session_id TEXT, role TEXT, text TEXT, ts REAL)")
    conn.executemany(
        "INSERT INTO messages (username, session_id, role, text, ts)"
        " VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_stats_reports_missing_not_zero(tmp_base):
    from core.stats_report import StatsReport
    r = StatsReport(_T(tmp_base)).generate()
    assert r["ok"] is True
    for name in ("聊天消息", "记忆卡", "日历事件"):
        assert r["统计"][name]["状态"] == "缺失", r
        assert r["统计"][name]["值"] == 0


def test_stats_reports_failure_separately(tmp_base):
    from core.stats_report import StatsReport
    (tmp_base / "data" / "memory_cards.jsonl").write_text(
        json.dumps({"facts": ["a"]}) + "\n坏行\n", encoding="utf-8")
    (tmp_base / "data" / "calendar.json").write_text("{坏的", encoding="utf-8")
    r = StatsReport(_T(tmp_base)).generate()
    assert r["统计"]["记忆卡"]["状态"] == "ok"
    assert r["统计"]["记忆卡"]["值"] == 1
    assert "没法解析" in r["统计"]["记忆卡"].get("说明", "")
    assert r["统计"]["日历事件"]["状态"] == "失败"
    assert r["ok"] is False
    assert "读不出来" in r["说明"]


def test_stats_period_filters_chats(tmp_base):
    from core.stats_report import StatsReport
    now = time.time()
    _make_chats(tmp_base / "data" / "chats.db", [
        ("u", "s", "user", "老消息", now - 10 * 86400),
        ("u", "s", "user", "新消息", now),
    ])
    sr = StatsReport(_T(tmp_base))
    assert sr.generate("全部")["统计"]["聊天消息"]["值"] == 2
    assert sr.generate("今天")["统计"]["聊天消息"]["值"] == 1
    assert sr.generate(3)["统计"]["聊天消息"]["值"] == 1
    assert sr.generate(3)["范围"] == "最近 3 天"


def test_stats_markdown_marks_failure(tmp_base):
    from core.stats_report import StatsReport
    (tmp_base / "data" / "calendar.json").write_text("{坏的", encoding="utf-8")
    md = StatsReport(_T(tmp_base)).to_markdown()
    assert "小6使用统计" in md
    assert "读取失败" in md
