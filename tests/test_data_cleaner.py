# -*- coding: utf-8 -*-
"""B4：data_cleaner（干跑 / 备份回滚 / 坏行保留）

背景
----
清洗类能力是**唯一会删用户数据**的一档，所以这里守三条：
1. ``dry_run=True`` 不许改动任何文件；
2. 真要清时先备份，``restore_backup()`` 能把文件整份换回来；
3. 解析失败的行不许被顺手删掉（原来 ``clean_cards`` 就是这么丢数据的）。
"""
import json
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))


class _T:
    def __init__(self, base):
        self.base = str(base)


def _cleaner(tmp_path):
    from core.data_cleaner import DataCleaner
    (tmp_path / "data").mkdir(exist_ok=True)
    return DataCleaner(_T(tmp_path))


def _card(facts):
    return json.dumps({"facts": facts}, ensure_ascii=False)


def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, username TEXT,"
                 " session_id TEXT, role TEXT, text TEXT, ts REAL)")
    conn.executemany(
        "INSERT INTO messages (username, session_id, role, text, ts)"
        " VALUES (?,?,?,?,?)",
        [(u, s, r, t, ts) for (u, s, r, t, ts) in rows])
    conn.commit()
    conn.close()


# ── 记忆卡 ──
def test_cards_dry_run_changes_nothing(tmp_path):
    dc = _cleaner(tmp_path)
    p = tmp_path / "data" / "memory_cards.jsonl"
    p.write_text(_card(["用户喜欢 Python", "用户住在杭州"]) + "\n"
                 + _card(["用户喜欢 Python", "用户住在杭州"]) + "\n",
                 encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    r = dc.clean_cards(dry_run=True, backup=False)
    assert r["干跑"] is True
    assert r["删除"] == 1
    assert p.read_text(encoding="utf-8") == before, "干跑居然改了文件"
    assert not (tmp_path / "data" / "cleaning_backup").exists()


def test_cards_clean_keeps_bad_lines_and_backs_up(tmp_path):
    dc = _cleaner(tmp_path)
    p = tmp_path / "data" / "memory_cards.jsonl"
    p.write_text(_card(["用户喜欢 Python"]) + "\n"
                 + _card(["用户喜欢 Python"]) + "\n"
                 + "这行不是 JSON\n", encoding="utf-8")
    r = dc.clean_cards(dry_run=False, backup=True)
    assert r["ok"] is True
    assert r["原始"] == 3
    assert r["删除"] == 1
    text = p.read_text(encoding="utf-8")
    assert "这行不是 JSON" in text, "坏行被删了 —— 数据丢失"
    assert r.get("备份"), r
    backups = dc.list_backups()
    assert backups and "memory_cards.jsonl" in backups[0]["文件"]


def test_restore_backup_puts_file_back(tmp_path):
    dc = _cleaner(tmp_path)
    p = tmp_path / "data" / "memory_cards.jsonl"
    p.write_text(_card(["a"]) + "\n" + _card(["a"]) + "\n", encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    dc.clean_cards(dry_run=False, backup=True)
    assert p.read_text(encoding="utf-8") != before
    res = dc.restore_backup()
    assert res["ok"] is True and "memory_cards.jsonl" in res["已恢复"]
    assert p.read_text(encoding="utf-8") == before, "回滚没恢复原内容"


# ── 知识图谱 ──
def test_graph_dedup_keeps_incomplete_entries(tmp_path):
    dc = _cleaner(tmp_path)
    p = tmp_path / "data" / "graph.json"
    data = {"三元组": [
        {"s": "小6", "p": "喜欢", "o": "音乐"},
        {"s": "小6", "p": "喜欢", "o": "音乐"},       # 重复
        {"s": "只有主语"},                            # 缺字段：不该被合并
        {"p": "缺主语"},
    ]}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = dc.clean_graph(dry_run=False, backup=True)
    assert r["删除"] == 1, r
    after = json.loads(p.read_text(encoding="utf-8"))["三元组"]
    assert len(after) == 3
    assert {"s": "只有主语"} in after and {"p": "缺主语"} in after


def test_graph_dry_run_does_not_write(tmp_path):
    dc = _cleaner(tmp_path)
    p = tmp_path / "data" / "graph.json"
    p.write_text(json.dumps({"三元组": [
        {"s": "a", "p": "b", "o": "c"}, {"s": "a", "p": "b", "o": "c"}]}),
        encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    assert dc.clean_graph(dry_run=True, backup=False)["删除"] == 1
    assert p.read_text(encoding="utf-8") == before


# ── 聊天记录 ──
def test_chats_dedup_consecutive_only(tmp_path):
    dc = _cleaner(tmp_path)
    db = tmp_path / "data" / "chats.db"
    _make_db(db, [
        ("u", "s", "user", "在吗", 1.0),
        ("u", "s", "user", "在吗", 1.1),      # 连续重复 -> 删
        ("u", "s", "ai", "在", 1.2),
        ("u", "s", "user", "在吗", 1.3),      # 不连续 -> 留
    ])
    r = dc.clean_chats(dry_run=False, backup=True)
    assert r["删除重复"] == 1 and r["剩余"] == 3, r
    conn = sqlite3.connect(str(db))
    n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    assert n == 3
    assert r.get("备份")


def test_chats_dry_run_leaves_db_untouched(tmp_path):
    dc = _cleaner(tmp_path)
    db = tmp_path / "data" / "chats.db"
    _make_db(db, [("u", "s", "user", "在吗", 1.0),
                  ("u", "s", "user", "在吗", 1.1)])
    before = db.read_bytes()
    r = dc.clean_chats(dry_run=True, backup=False)
    assert r["删除重复"] == 1 and r["干跑"] is True
    assert db.read_bytes() == before


# ── 总入口 / 参数 ──
def test_clean_all_dry_run_is_default_preview(tmp_path):
    dc = _cleaner(tmp_path)
    p = tmp_path / "data" / "memory_cards.jsonl"
    p.write_text(_card(["a"]) + "\n" + _card(["a"]) + "\n", encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    r = dc.preview()
    assert r["干跑"] is True
    assert p.read_text(encoding="utf-8") == before
    assert "没有改动" in r["说明"]


def test_flag_parses_false_string():
    from core.data_cleaner import DataCleaner
    assert DataCleaner._flag("false") is False
    assert DataCleaner._flag("true") is True
    assert DataCleaner._flag(None, True) is True
    assert DataCleaner._flag(True) is True
