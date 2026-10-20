# -*- coding: utf-8 -*-
"""数据 schema 真实迁移测试。"""
import json
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import data_schema  # noqa: E402
from core.data_migrations import migrate_all  # noqa: E402


def test_migrate_v1_data_to_v2(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "_schema.json").write_text(json.dumps({
        "data_schema": 1,
        "files": {
            "memory_cards.jsonl": 1,
            "dreams.jsonl": 1,
            "personality.json": 1,
            "config.json": 1,
            "chats.db": 1,
            "memory.json": 1,
        },
    }), encoding="utf-8")
    (data / "memory_cards.jsonl").write_text(
        '{"facts":"喜欢Python","time":1}\nBAD_LINE\n', encoding="utf-8")
    (data / "dreams.jsonl").write_text('{"dream":"看星星"}\n', encoding="utf-8")
    (data / "personality.json").write_text('{"mood":"开心"}', encoding="utf-8")
    (data / "memory.json").write_text(
        '{"default":[{"u":"hi","a":"hello"}],"bad":"x"}', encoding="utf-8")
    (data / "config.json").write_text('{"model_mode":"本地路由"}', encoding="utf-8")
    conn = sqlite3.connect(data / "chats.db")
    conn.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, username TEXT, role TEXT, text TEXT)")
    conn.execute("INSERT INTO messages(username,role,text) VALUES('u','user','hi')")
    conn.commit()
    conn.close()

    r = migrate_all(str(tmp_path))
    assert r["ok"] is True, r
    assert len(r["migrated"]) >= 5
    assert r["backups"]

    reg = data_schema.load(str(tmp_path))
    assert reg["data_schema"] == 2
    assert all(v == 2 for v in reg["files"].values())

    cards = (data / "memory_cards.jsonl").read_text(encoding="utf-8").strip().splitlines()
    rec = json.loads(cards[0])
    assert rec["facts"] == ["喜欢Python"]
    assert rec["schema_version"] == 2
    assert (data / "memory_cards.jsonl.bad_lines").exists()

    personality = json.loads((data / "personality.json").read_text(encoding="utf-8"))
    assert "birth_time" in personality and personality["schema_version"] == 2

    memory = json.loads((data / "memory.json").read_text(encoding="utf-8"))
    assert isinstance(memory["default"], list)
    assert memory["bad"] == []

    conn = sqlite3.connect(data / "chats.db")
    cols = {x[1] for x in conn.execute("PRAGMA table_info(messages)")}
    version = conn.execute("SELECT value FROM x6_meta WHERE key='schema_version'").fetchone()[0]
    conn.close()
    assert "session_id" in cols and "ts" in cols
    assert version == "2"


def test_migrate_is_idempotent(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "_schema.json").write_text(
        json.dumps({"data_schema": 2, "files": {"memory.json": 2}}), encoding="utf-8")
    (data / "memory.json").write_text('{"default":[]}', encoding="utf-8")
    r = migrate_all(str(tmp_path))
    assert r["ok"] is True
    assert not r["migrated"]


def test_missing_registry_entry_runs_v0_then_v1_then_v2(tmp_path):
    """v0 旧数据必须按 v0->v1->v2 两级迁移，不能直接冒充 v2。"""
    data = tmp_path / "data"
    data.mkdir()
    (data / "memory_cards.jsonl").write_text(
        '"喜欢咖啡"\n{"fact":"喜欢猫","time":1}\n', encoding="utf-8")
    (data / "dreams.jsonl").write_text('"梦见下雨"\n', encoding="utf-8")
    (data / "memory.json").write_text(
        '["旧记忆"]', encoding="utf-8")  # v0 顶层甚至不是 dict
    (data / "_schema.json").write_text(
        json.dumps({"data_schema": 1, "files": {}}), encoding="utf-8")

    r = migrate_all(str(tmp_path))
    assert r["ok"] is True, r
    by_file = {x["file"]: x for x in r["migrated"]}
    assert by_file["memory_cards.jsonl"]["steps"] == ["v0->v1", "v1->v2"]
    assert by_file["dreams.jsonl"]["steps"] == ["v0->v1", "v1->v2"]
    assert by_file["memory.json"]["steps"] == ["v0->v1", "v1->v2"]

    cards = [json.loads(x) for x in
             (data / "memory_cards.jsonl").read_text(encoding="utf-8").splitlines()]
    assert cards[0]["facts"] == ["喜欢咖啡"]
    assert cards[1]["facts"] == ["喜欢猫"]
    assert all(c["schema_version"] == 2 for c in cards)

    dreams = json.loads((data / "dreams.jsonl").read_text(encoding="utf-8").strip())
    assert dreams["dream"] == "梦见下雨"
    assert dreams["schema_version"] == 2

    memory = json.loads((data / "memory.json").read_text(encoding="utf-8"))
    assert memory["default"][0]["a"] == "旧记忆"
    assert memory["_schema_version"] == 2


def test_dry_run_reports_steps_without_touching_files(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    p = data / "memory.json"
    original = '{"default":[]}'
    p.write_text(original, encoding="utf-8")
    (data / "_schema.json").write_text(
        json.dumps({"data_schema": 1, "files": {"memory.json": 0}}),
        encoding="utf-8")

    r = migrate_all(str(tmp_path), dry_run=True)
    assert r["ok"] is True, r
    item = [x for x in r["migrated"] if x["file"] == "memory.json"][0]
    assert item["steps"] == ["v0->v1", "v1->v2"]
    assert p.read_text(encoding="utf-8") == original
