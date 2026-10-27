# -*- coding: utf-8 -*-
"""向量库脏数据修复工具（tools/repair_vectors.py）

为什么要有这个文件
------------------
2026-10-27 实测 `data/vectors.db`：1756 条里 41 条 embedding 长度不对
（30 条 12 字节、11 条 4 字节，正常是 3072 字节）。
`core/vector_store.py` 只会**跳过**它们（不跳过会把整库读崩），
但它们会一直留着：每次启动都重复报警，还永远检索不到。

这条工具要守住：
    ① 默认**不写库**（只体检）
    ② `--apply` 前必须备份
    ③ 重算成功 → 更新；文本空/嵌入空 → 删除
    ④ 重算出来的长度整体不符（换过模型）→ **回滚，绝不删**
"""
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

import repair_vectors as rv                     # noqa: E402


def _make_db(tmp_path, rows):
    """rows: [(id, text, bytes)]；建一个只有 vectors 表的最小库"""
    p = str(tmp_path / "vectors.db")
    c = sqlite3.connect(p)
    try:
        c.execute("""CREATE TABLE vectors(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT, tag TEXT, time REAL,
            hits INTEGER DEFAULT 0, embedding BLOB)""")
        for _id, text, blob in rows:
            c.execute("INSERT INTO vectors(id,text,tag,time,hits,embedding) "
                      "VALUES(?,?,?,?,?,?)",
                      (_id, text, "", 0, 0, blob))
        c.commit()
    finally:
        c.close()
    return p


GOOD = b"\x00" * 16          # 4 维 float32
BAD = b"\x00" * 8            # 2 维 —— 长度不对


def _rows():
    return [(1, "正常一", GOOD), (2, "正常二", GOOD),
            (3, "要重算", BAD), (4, "", b""), (5, "也要重算", b"\x00" * 4)]


def test_scan_counts_and_dimension(tmp_path):
    p = _make_db(tmp_path, _rows())
    info = rv.scan(p)
    assert info["ok"] is True
    assert info["总条数"] == 5
    assert info["正常"] == 2
    assert info["异常"] == 3
    assert info["维度字节"] == 16 and info["维度"] == 4
    assert {s["id"] for s in info["样本"]} == {3, 4, 5}


def test_scan_missing_db_is_reported_not_raised(tmp_path):
    info = rv.scan(str(tmp_path / "nope.db"))
    assert info["ok"] is False and "打不开" in info["错误"]


def test_dry_run_does_not_touch_db(tmp_path):
    p = _make_db(tmp_path, _rows())
    r = rv.repair(p, apply=False)
    assert r["ok"] is True and r["异常"] == 3 and r["已写入"] is False
    assert not [n for n in os.listdir(str(tmp_path)) if ".bak_" in n]
    # 再体检一次，数字没变（说明真的没写）
    assert rv.scan(p)["异常"] == 3


def test_apply_repairs_and_deletes_then_backs_up(tmp_path):
    p = _make_db(tmp_path, _rows())

    def fake_embed(text):
        return [0.5, 0.5, 0.5, 0.5]   # 4 维 = 16 字节，和正常记录一致

    r = rv.repair(p, apply=True, embed=fake_embed)
    assert r["ok"] is True, r
    assert r["修复"] == 2 and r["删除"] == 1, r
    assert r["已写入"] is True
    assert os.path.exists(r["备份"]), "写库前必须备份"

    info = rv.scan(p)
    assert info["异常"] == 0 and info["总条数"] == 4
    c = sqlite3.connect(p)
    try:
        ids = [row[0] for row in c.execute("SELECT id FROM vectors ORDER BY id")]
    finally:
        c.close()
    assert ids == [1, 2, 3, 5], ids


def test_embed_error_rolls_back(tmp_path):
    """Ollama 连不上时不能"重算失败就全删"，必须回滚"""
    p = _make_db(tmp_path, _rows())

    def broken_embed(text):
        raise ConnectionError("connection refused")

    r = rv.repair(p, apply=True, embed=broken_embed)
    assert r["ok"] is False and "已回滚" in r["错误"]
    assert rv.scan(p)["异常"] == 3, "回滚之后库必须保持原样"


def test_length_mismatch_rolls_back_instead_of_deleting(tmp_path):
    """换过 embedding 模型时，重算长度整体不符 —— 删了就是丢数据，要回滚"""
    p = _make_db(tmp_path, _rows())

    def embed_8dim(text):
        return [0.1] * 8              # 32 字节，和库里的 16 字节不符

    r = rv.repair(p, apply=True, embed=embed_8dim)
    assert r["ok"] is False and "已回滚" in r["错误"]
    assert rv.scan(p)["异常"] == 3


def test_cli_dry_run_exit_code(tmp_path, capsys):
    p = _make_db(tmp_path, _rows())
    assert rv.main(["--db", p]) == 0
    out = capsys.readouterr().out
    assert "异常      3" in out
