# -*- coding: utf-8 -*-
"""批次 48.3：事件驱动主动搭话。

覆盖：off 不发、shadow 只记录、on 每天一条、免打扰/预算、
接受率统计（30 分钟内回话）、长沉默兜底。
"""
import os
import sys
import time
from datetime import datetime

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.personality import PersonalityEngine   # noqa: E402


class FakeTrunk:
    def __init__(self, base, rules=None):
        self.base = str(base)
        self.config = {}
        self.modules = {}
        self.rules = dict(rules or {})
        self.logs = []

    def call(self, *a, **k):
        return {}

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def _log(self, msg, level="INFO"):
        self.logs.append((level, msg))


@pytest.fixture
def pe(tmp_path, request):
    e = PersonalityEngine(FakeTrunk(tmp_path))
    e.base = str(tmp_path)
    e.path = os.path.join(str(tmp_path), "data", "personality.json")
    os.makedirs(os.path.dirname(e.path), exist_ok=True)
    e.data["last_active"] = time.time()
    return e


def _at(hour):
    return time.mktime((2026, 10, 29, hour, 0, 0, 0, 0, -1))


def test_off_mode_never_sends(pe):
    pe.trunk.rules["主动.事件驱动"] = "off"
    assert pe.queue_proactive("task_done") is False
    assert pe.consume_proactive() is None


def test_shadow_records_without_sending(pe):
    pe.trunk.rules["主动.事件驱动"] = "shadow"
    assert pe.queue_proactive("task_done", now=_at(10)) is True
    assert pe.consume_proactive(now=_at(10)) is None
    stats = pe.proactive_stats()
    assert stats["shadow"] >= 1
    assert pe.data["last_proactive_date"] == ""


def test_on_sends_once_per_day(pe):
    pe.trunk.rules["主动.事件驱动"] = "on"
    assert pe.queue_proactive("task_done", now=_at(10)) is True
    line = pe.consume_proactive(now=_at(10))
    assert line and "任务" in line
    assert pe.consume_proactive(now=_at(11)) is None      # 当天预算已用


def test_quiet_hours_suppressed(pe):
    pe.trunk.rules["主动.事件驱动"] = "on"
    assert pe.queue_proactive("task_done", now=_at(23)) is False
    stats = pe.proactive_stats()
    assert stats["suppressed"] >= 1


def test_acceptance_rate(pe):
    pe.trunk.rules["主动.事件驱动"] = "on"
    pe.queue_proactive("task_done", now=_at(10))
    assert pe.consume_proactive(now=_at(10)) is not None
    assert pe.note_user_reply("好呀", now=_at(10) + 10 * 60) is True
    stats = pe.proactive_stats()
    assert stats["sent"] == 1 and stats["accepted"] == 1
    assert stats["rate"] == 1.0
    assert pe.note_user_reply("再说一遍", now=_at(10) + 20 * 60) is False


def test_long_silence_fallback(pe):
    pe.trunk.rules.update({"主动.事件驱动": "on", "主动.沉默分钟": 30})
    pe.data["last_active"] = _at(9)
    line = pe.consume_proactive(now=_at(10))
    assert "在忙吗" in line


def test_commitment_detail(pe):
    pe.trunk.rules["主动.事件驱动"] = "on"
    pe.data["last_active"] = _at(10)
    pe.queue_proactive("commitment", "明天我要去面试", now=_at(10))
    assert pe.consume_proactive(now=_at(10)) == "你之前说的「明天我要去面试」，后来咋样了？"
