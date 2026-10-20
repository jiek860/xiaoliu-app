# -*- coding: utf-8 -*-
"""Golden migration fixtures: synthetic v0/v1 -> v2 snapshots."""
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.data_migrations import migrate_all  # noqa: E402

FIXTURES = os.path.join(BASE, "tests", "fixtures", "migrations")
VOLATILE = {"time", "birth_time", "last_active", "date", "t", "created_at", "updated"}


def _normalize(value):
    if isinstance(value, dict):
        return {k: ("<dynamic>" if k in VOLATILE else _normalize(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _snapshot(path):
    if path.endswith(".jsonl"):
        return [_normalize(json.loads(line)) for line in
                open(path, encoding="utf-8").read().splitlines() if line.strip()]
    return _normalize(json.load(open(path, encoding="utf-8")))


def _assert_golden(src_name, expected_name, tmp_path):
    src = tmp_path / "data"
    shutil.copytree(os.path.join(FIXTURES, src_name), src)
    r = migrate_all(str(tmp_path))
    assert r["ok"] is True, r
    assert r["backups"], "migration must create a backup"
    expected_dir = os.path.join(FIXTURES, expected_name)
    for name in ("memory_cards.jsonl", "dreams.jsonl", "memory.json",
                 "personality.json", "config.json", "_schema.json"):
        actual_path = str(src / name)
        expected_path = os.path.join(expected_dir, name)
        if not os.path.exists(expected_path):
            continue
        assert os.path.exists(actual_path), name
        if name.endswith(".jsonl"):
            assert _snapshot(actual_path) == _snapshot(expected_path), name
        else:
            actual = _snapshot(actual_path)
            expected = _snapshot(expected_path)
            if name == "config.json":
                # Full default config may evolve; the migration contract is the
                # preserved user values plus the target schema version.
                assert actual.get("model_mode") == expected.get("model_mode")
                assert actual.get("config_schema") == 2
            else:
                assert actual == expected, name
    return r


def test_v0_golden_migration(tmp_path):
    _assert_golden("v0", "expected_v2", tmp_path)


def test_v1_golden_migration(tmp_path):
    _assert_golden("v1", "expected_v2_from_v1", tmp_path)


def test_golden_migration_is_idempotent(tmp_path):
    _assert_golden("v0", "expected_v2", tmp_path)
    r2 = migrate_all(str(tmp_path))
    assert r2["ok"] is True
    assert r2["migrated"] == []
