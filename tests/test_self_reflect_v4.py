# -*- coding: utf-8 -*-
"""批次 48.1/48.2：多维反思、失败库、建议晋升。

重点不是"函数能跑"，而是：
* 开关 off 必须完全回到 v2.1 行为（不写维度、不写失败库）；
* shadow 不改旧分数语义，但会记录维度/失败样本；
* 低分样本去重、复查、可统计复现率；
* 同类建议 ≥3 才出候选，确认才生效，撤销即恢复，全程有审计。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.self_reflect import ReflectEngine   # noqa: E402
from core.chat.persona_card import PersonaCard             # noqa: E402
from core.chat.critic import ResponseCritic                # noqa: E402


class FakeTrunk:
    def __init__(self, base, rules=None, llm=None):
        self.base = str(base)
        self.modules = {"llm": llm} if llm else {}
        self.rules = dict(rules or {})
        self.logs = []

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def _log(self, msg, level="INFO"):
        self.logs.append((level, msg))


def _engine(tmp_path, rules=None, llm=None):
    return ReflectEngine(FakeTrunk(tmp_path, rules, llm))


def test_off_mode_is_exact_legacy(tmp_path):
    e = _engine(tmp_path, {"反思.多维评分": "off"})
    out = e.quick_eval("怎么学 Python", "作为AI，希望对你有所帮助。")
    assert set(out) == {"分数", "问题"}
    assert "维度" not in out
    assert not os.path.exists(os.path.join(str(tmp_path), "data",
                                           "chat_failures.jsonl"))


def test_shadow_records_dims_without_changing_score(tmp_path):
    e = _engine(tmp_path)
    out = e.quick_eval("怎么学 Python", "作为AI，希望对你有所帮助。")
    assert out["维度"]["人格"] <= 3
    assert out["分数"] is None                  # 影子模式沿用旧粗筛语义（不评分）
    assert out["总分"] < 3.0
    assert e.history[-1]["影子"] is True
    assert e.failure_stats()["总数"] >= 1


def test_on_mode_uses_dimension_score(tmp_path):
    e = _engine(tmp_path, {"反思.多维评分": "on"})
    out = e.quick_eval("今天好累", "辛苦啦，先歇会儿，别硬扛。")
    assert out["分数"] == out["总分"] * 2
    assert out["维度"]["有用"] >= 3


def test_failure_dedupe_and_recheck(tmp_path):
    e = _engine(tmp_path)
    for _ in range(2):
        e.record_failure("怎么学 Python", "作为AI，希望对你有所帮助。",
                         category="banned", suggestion="别说客服腔")
    rows = e.failures(status="")
    assert len(rows) == 1
    assert rows[0]["seen"] == 2
    r = e.recheck_failures()
    assert r["checked"] == 1
    assert "复现率" in r


def test_candidate_requires_manual_confirm_and_can_be_revoked(tmp_path):
    e = _engine(tmp_path, {"反思.晋升阈值": 3})
    for _ in range(3):
        e.record_failure("怎么学 Python", "作为AI，希望对你有所帮助。",
                         category="banned", suggestion="别说客服腔")
    promoted = e.promote_candidates()
    assert promoted["created"] == 1
    cid = promoted["candidates"][0]["id"]
    assert e.active_rules() == []              # 没确认前不生效

    ok = e.confirm_candidate(cid, by="tester")
    assert ok["ok"] is True
    assert len(e.active_rules()) == 1
    card = PersonaCard.load(str(tmp_path))
    assert card.promoted_avoids()
    assert "作为AI" in card.banned_words()
    critic = ResponseCritic(FakeTrunk(tmp_path))
    out = critic.check("作为AI，这个很简单。", user_text="怎么学 Python")
    assert "banned" in out["issues"]

    assert e.revoke_candidate(cid)["ok"] is True
    assert e.active_rules() == []
    actions = [row["action"] for row in e.audit_log()]
    assert actions == ["confirm", "revoke"]


def test_advice_ignores_expired_suggestions(tmp_path):
    e = _engine(tmp_path, {"反思.多维评分": "shadow"})
    e.history = [
        {"用户": "旧问题", "回答": "旧回答", "分数": 3, "建议": "别列点",
         "时间": "01-01 10:00", "ts": 1},
        {"用户": "新问题", "回答": "新回答", "分数": 3, "建议": "短一点",
         "时间": "10-29 10:00", "ts": 1793286260},
    ]
    advice = e.get_advice()
    assert "别列点" not in advice


def test_weekly_report(tmp_path):
    e = _engine(tmp_path)
    e.record_failure("怎么学 Python", "作为AI，希望对你有所帮助。",
                     category="banned")
    report = e.weekly_report()
    assert report["失败样本"] >= 1
    assert report["失败类别"]["banned"] == 1
    assert os.path.exists(e.weekly_path)
