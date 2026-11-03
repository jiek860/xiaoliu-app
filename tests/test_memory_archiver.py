# -*- coding: utf-8 -*-
"""memory_archiver 完整版测试：归档 / 坏行保留 / 恢复 / 自动触发"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.memory_archiver import MemoryArchiver     # noqa: E402


class _T:
    def __init__(self, base):
        self.base = base


def _mk(tmp, lines):
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    p = os.path.join(tmp, "data", "memory_cards.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
    return MemoryArchiver(_T(tmp)), p


def _card(facts, date):
    return json.dumps({"facts": facts, "date": date}, ensure_ascii=False)


def test_archive_moves_old_keeps_new(tmp_path):
    old = _card(["旧事"], "2020-01-01")
    new = _card(["新事"], "2099-01-01")
    ma, p = _mk(str(tmp_path), [old, new])
    r = ma.archive_old(days=30)
    assert r["ok"] and r["归档数"] == 1 and r["剩余"] == 1
    assert open(p, encoding="utf-8").read().splitlines() == [new]


def test_bad_line_survives_and_does_not_crash(tmp_path):
    # 回归：旧实现 except 里 new.append(c)，c 未定义 -> NameError 直接崩
    good_old = _card(["旧事"], "2020-01-01")
    bad = "{不是合法 json"
    ma, p = _mk(str(tmp_path), [good_old, bad])
    r = ma.archive_old(days=30)
    assert r["ok"]
    assert r["坏行"] == 1
    assert bad in open(p, encoding="utf-8").read().splitlines()


def test_card_without_date_is_kept(tmp_path):
    no_date = json.dumps({"facts": ["没日期"]}, ensure_ascii=False)
    ma, p = _mk(str(tmp_path), [no_date])
    r = ma.archive_old(days=0)
    assert r["ok"] and r["归档数"] == 0
    assert no_date in open(p, encoding="utf-8").read()


def test_missing_file_returns_not_ok(tmp_path):
    r = MemoryArchiver(_T(str(tmp_path))).archive_old()
    assert r["ok"] is False


def test_restore_roundtrip(tmp_path):
    old = _card(["旧事"], "2020-01-01")
    ma, p = _mk(str(tmp_path), [old])
    r = ma.archive_old(days=30)
    name = r["归档文件"]
    assert ma.restore(name)["恢复数"] == 1
    assert old in open(p, encoding="utf-8").read()
    assert ma.restore(name)["ok"] is False      # 归档已删


def test_restore_is_idempotent(tmp_path):
    old = _card(["旧事"], "2020-01-01")
    ma, p = _mk(str(tmp_path), [old])
    r = ma.archive_old(days=30)
    name = r["归档文件"]
    assert ma.restore(name, remove=False)["恢复数"] == 1
    assert ma.restore(name, remove=False)["恢复数"] == 0


def test_auto_archive_respects_interval(tmp_path):
    old = _card(["旧事"], "2020-01-01")
    ma, p = _mk(str(tmp_path), [old])
    first = ma.auto_archive_if_due(days=30, min_interval_days=7)
    assert first["ok"] and first.get("归档数") == 1
    second = ma.auto_archive_if_due(days=30, min_interval_days=7)
    assert second.get("跳过")                 # 周期内不再动


def test_run_reports_archive_count(tmp_path):
    ma = MemoryArchiver(_T(str(tmp_path)))
    assert ma.run()["归档文件"] == 0
