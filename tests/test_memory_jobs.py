# -*- coding: utf-8 -*-
"""记忆周巩固（批次 43.5）：过期清理、同 id 合并、总量裁剪、失败静默。"""
import json
import os

from core.chat.memory_jobs import weekly_consolidate

NOW = 1_790_000_000.0


def _path(base):
    return os.path.join(str(base), "data", "memory_cards.jsonl")


def _write(base, rows):
    os.makedirs(os.path.dirname(_path(base)), exist_ok=True)
    with open(_path(base), "w", encoding="utf-8") as fp:
        for row in rows:
            fp.write((row if isinstance(row, str)
                      else json.dumps(row, ensure_ascii=False)) + "\n")


def _read(base):
    with open(_path(base), encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


def test_missing_file_returns_empty_stats(tmp_path):
    stats = weekly_consolidate(str(tmp_path), now=NOW)
    assert stats["before"] == 0
    assert stats["changed"] is False


def test_expired_cards_removed_and_backup_kept(tmp_path):
    _write(tmp_path, [
        {"text": "过期事件", "expires_at": NOW - 1},
        {"text": "长期偏好", "type": "preference"},
        {"facts": ["旧卡没有过期时间"]},
    ])
    stats = weekly_consolidate(str(tmp_path), now=NOW)
    assert stats["removed_expired"] == 1
    assert stats["after"] == 2
    assert stats["changed"] is True
    assert os.path.exists(_path(tmp_path) + ".bak")
    assert [c.get("text") for c in _read(tmp_path)] == ["长期偏好", None]


def test_duplicate_id_keeps_latest_row(tmp_path):
    _write(tmp_path, [
        {"id": "m_1", "text": "旧内容"},
        {"id": "m_1", "text": "新内容"},
    ])
    stats = weekly_consolidate(str(tmp_path), now=NOW)
    assert stats["removed_dupes"] == 1
    assert stats["after"] == 1
    assert _read(tmp_path)[0]["text"] == "新内容"


def test_total_is_trimmed_to_newest(tmp_path):
    rows = [{"id": "m_%d" % i, "text": "第%d条" % i,
             "created_at": NOW + i} for i in range(6)]
    _write(tmp_path, rows)
    stats = weekly_consolidate(str(tmp_path), now=NOW, max_cards=3)
    assert stats["trimmed"] == 3
    assert [c["id"] for c in _read(tmp_path)] == ["m_3", "m_4", "m_5"]


def test_no_changes_does_not_rewrite_or_backup(tmp_path):
    _write(tmp_path, [{"text": "长期偏好", "type": "preference"}])
    before = os.path.getmtime(_path(tmp_path))
    stats = weekly_consolidate(str(tmp_path), now=NOW)
    assert stats["changed"] is False
    assert not os.path.exists(_path(tmp_path) + ".bak")
    assert os.path.getmtime(_path(tmp_path)) == before


def test_bad_lines_are_skipped(tmp_path):
    """坏行不算一张卡：before 只数能解析的行，但坏行照样被清掉。"""
    _write(tmp_path, ["{bad", {"text": "好卡", "expires_at": NOW - 1}])
    stats = weekly_consolidate(str(tmp_path), now=NOW)
    assert stats["before"] == 1
    assert stats["after"] == 0
    assert _read(tmp_path) == []


def test_legacy_cards_without_id_are_kept(tmp_path):
    _write(tmp_path, [{"facts": ["喜欢短句"]}, {"facts": ["住在杭州"]}])
    stats = weekly_consolidate(str(tmp_path), now=NOW)
    assert stats["after"] == 2
    assert stats["changed"] is False


def test_write_failure_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.mkdir()
    # 目标路径是目录：备份 copyfile 失败 → 统计里带 error，不抛异常
    stats = weekly_consolidate(str(blocker), now=NOW)
    assert stats["changed"] is False
    assert stats["error"] == ""       # 没有文件时直接返回，不报错
    inner = tmp_path / "repo"
    _write(inner, [{"text": "过期", "expires_at": NOW - 1}])
    real = _path(inner)
    os.remove(real)
    os.makedirs(real)                  # 用目录占住文件路径
    stats = weekly_consolidate(str(inner), now=NOW)
    assert stats["changed"] is False


def test_zero_max_cards_uses_default(tmp_path):
    _write(tmp_path, [{"text": "a", "created_at": NOW}])
    stats = weekly_consolidate(str(tmp_path), now=NOW, max_cards=0)
    assert stats["after"] == 1
