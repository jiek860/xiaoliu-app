# -*- coding: utf-8 -*-
"""体检 / 修复向量库里的"脏向量"（维度不对的记录）

背景（2026-10-27 实测）
-----------------------
`data/vectors.db` 有 1756 条记录，其中 **41 条 embedding 长度不对**：
30 条 12 字节、11 条 4 字节，而正常记录是 3072 字节（768 维 float32）。

它们不会让程序崩 —— `core/vector_store.py` 加载时按第一条合法向量定维度，
长度不符的直接跳过（否则 numpy 会因 "inhomogeneous shape" 把整库读崩）。
但代价是：
  · 每次启动都重复报一次"向量库有 N 条记录向量维度异常"，日志噪音
  · 那 41 条**永远检索不到**，等于死数据还占着 id 名额

本工具做两件事
--------------
  ① 体检（默认，**不写库**）：统计正常/异常条数、按长度分组、列出样本
  ② 修复（`--apply`）：先备份 `vectors.db`，再用 nomic-embed-text 重算；
     文本为空 / 嵌入返回空的记录直接删掉（它本来也检索不到）

⚠️ 为什么"没重算成功就删"是安全的：embedding 只是记忆的索引，
   记忆正文在 memory.json / chats.db 里，删索引不删正文。
   但**只**在这条记录的文本真的为空、或模型对这段文本返回空向量时才删；
   如果是 Ollama 连不上 / 模型换了导致长度整体不符，会整体回滚不写库。

用法
----
    py -3 tools\\repair_vectors.py                 # 只体检
    py -3 tools\\repair_vectors.py --apply         # 备份后修复
    py -3 tools\\repair_vectors.py --apply --url http://192.168.1.2:11434
"""
import argparse
import array
import json
import os
import shutil
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BASE, "data", "vectors.db")
DEFAULT_MODEL = "nomic-embed-text"
_TEXT_LIMIT = 500          # 和 core/vector_store._embed() 的截断保持一致


def _connect(db_path):
    c = sqlite3.connect(db_path, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _blob_len(raw):
    return len(raw) if isinstance(raw, (bytes, bytearray)) else 0


def _scan_rows(db_path):
    """读出 (id, text, embedding)；库不存在/没表返回 None"""
    if not os.path.exists(db_path):
        return None
    try:
        c = _connect(db_path)
    except sqlite3.DatabaseError:
        return None
    try:
        return c.execute("SELECT id, text, embedding FROM vectors "
                         "ORDER BY id").fetchall()
    except sqlite3.DatabaseError:
        return None
    finally:
        c.close()


def _expected_bytes(rows):
    """正常记录的长度（字节）—— 取出现次数最多的那个长度

    不能只信第一条：库里第一条也可能恰好事坏的。
    """
    from collections import Counter
    sizes = Counter(_blob_len(r["embedding"]) for r in rows if r["embedding"])
    if not sizes:
        return 0
    return sizes.most_common(1)[0][0]


def scan(db_path=DEFAULT_DB):
    """体检：只读，不改库"""
    rows = _scan_rows(db_path)
    if rows is None:
        return {"ok": False, "错误": "打不开向量库：%s" % db_path}
    from collections import Counter
    good_len = _expected_bytes(rows)
    dist = Counter(_blob_len(r["embedding"]) for r in rows)
    bad = [r for r in rows if _blob_len(r["embedding"]) != good_len]
    return {
        "ok": True,
        "库": db_path,
        "总条数": len(rows),
        "正常": len(rows) - len(bad),
        "异常": len(bad),
        "维度字节": good_len,
        "维度": good_len // 4,
        "长度分布": sorted(dist.items()),
        "样本": [{"id": r["id"], "文本": (r["text"] or "")[:24],
                  "字节": _blob_len(r["embedding"])}
                 for r in bad[:10]],
    }


def _bad_rows(db_path, good_len):
    rows = _scan_rows(db_path) or []
    return [r for r in rows if _blob_len(r["embedding"]) != good_len]


def _backup_db(db_path):
    """先 checkpoint 再拷：WAL 模式下只拷主文件会漏掉刚写入的记录"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = db_path + ".bak_" + stamp
    try:
        c = sqlite3.connect(db_path, timeout=10)
        try:
            c.execute("PRAGMA wal_checkpoint(FULL)")
        finally:
            c.close()
    except sqlite3.DatabaseError:
        pass
    shutil.copy2(db_path, dst)
    return dst


def _embed_via_ollama(url, model, text, timeout=20):
    """调 Ollama 的 /api/embeddings（和 core/vector_store.py 用同一个接口）"""
    import requests
    r = requests.post(str(url).rstrip("/") + "/api/embeddings",
                      json={"model": model, "prompt": text},
                      timeout=timeout)
    r.raise_for_status()
    return r.json().get("embedding", []) or []


def _to_blob(emb):
    """float 列表 -> float32 字节（和 numpy.tobytes 等价，免依赖 numpy）"""
    a = array.array("f", [float(x) for x in emb])
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def repair(db_path=DEFAULT_DB, ollama_url="http://localhost:11434",
           model=DEFAULT_MODEL, apply=False, embed=None, backup=True):
    """修复维度不对的记录；`apply=False` 时只出计划、不写库"""
    info = scan(db_path)
    if not info.get("ok"):
        return info
    plan = {"ok": True, "库": db_path, "总条数": info["总条数"],
            "维度": info["维度"], "异常": info["异常"],
            "修复": 0, "删除": 0, "已写入": False}
    if not info["异常"]:
        plan["说明"] = "没有维度异常的记录，不需要修"
        return plan
    if not info["维度"]:
        plan.update({"ok": False, "错误": "库里没有一条合法向量，定不出维度；"
                                        "请直接重建向量库"})
        return plan
    if not apply:
        plan["说明"] = "体检模式（未写库）；加 --apply 才会重算/删除"
        plan["待处理"] = info["样本"]
        return plan

    good_len = info["维度字节"]
    bad = _bad_rows(db_path, good_len)
    if backup:
        plan["备份"] = _backup_db(db_path)
    emb_fn = embed or (lambda t: _embed_via_ollama(ollama_url, model, t))
    c = _connect(db_path)
    try:
        for row in bad:
            text = (row["text"] or "").strip()[:_TEXT_LIMIT]
            emb = []
            if text:
                try:
                    emb = emb_fn(text) or []
                except Exception as e:
                    c.rollback()
                    plan.update({"ok": False,
                                 "错误": "重算 embedding 失败，已回滚（库未改）："
                                         "%s: %s" % (type(e).__name__, str(e)[:70])})
                    return plan
            blob = _to_blob(emb) if emb else b""
            if blob and len(blob) == good_len:
                c.execute("UPDATE vectors SET embedding=? WHERE id=?",
                          (blob, row["id"]))
                plan["修复"] += 1
            elif not blob:
                # 文本为空 / 模型对这段文本返回空向量 → 这条本来也检索不到
                c.execute("DELETE FROM vectors WHERE id=?", (row["id"],))
                plan["删除"] += 1
            else:
                # 重算出来的长度和库里大多数不一致 —— 多半是换过 embedding
                # 模型，这时候删了就是真丢数据，整体回滚
                c.rollback()
                plan.update({"ok": False,
                             "错误": "重算得到的向量是 %d 字节，库里正常记录是 %d "
                                     "字节 —— 可能换过 embedding 模型，已回滚"
                                     % (len(blob), good_len)})
                return plan
        c.commit()
    finally:
        c.close()
    plan["已写入"] = True
    plan["说明"] = "修复 %d 条，删除 %d 条" % (plan["修复"], plan["删除"])
    return plan


def _read_ollama_url():
    try:
        with open(os.path.join(BASE, "data", "config.json"),
                  encoding="utf-8") as f:
            return (json.load(f).get("ollama_url")
                    or "http://localhost:11434")
    except Exception:
        return "http://localhost:11434"


def show(info):
    print("=" * 70)
    print("向量库体检：%s" % info.get("库"))
    print("=" * 70)
    if not info.get("ok"):
        print("  ❌ %s" % info.get("错误"))
        return 1
    print("  总条数    %d" % info["总条数"])
    print("  正常      %d（%d 字节 / %d 维）"
          % (info["正常"], info["维度字节"], info["维度"]))
    print("  异常      %d" % info["异常"])
    print("  长度分布  %s" % ", ".join("%d字节×%d" % (n, c)
                                       for n, c in info["长度分布"]))
    for s in info.get("样本", []):
        print("      id=%-6s %-3s字节  %s" % (s["id"], s["字节"], s["文本"]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="体检/修复向量库里的脏向量")
    ap.add_argument("--db", default=DEFAULT_DB, help="向量库路径")
    ap.add_argument("--apply", action="store_true",
                    help="真的写库（默认只体检）；写前自动备份")
    ap.add_argument("--url", default="", help="Ollama 地址（默认读 config.json）")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="embedding 模型")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不建议）")
    a = ap.parse_args(argv)

    if not a.apply:
        return show(scan(a.db))
    r = repair(a.db, ollama_url=a.url or _read_ollama_url(), model=a.model,
               apply=True, backup=not a.no_backup)
    print("=" * 70)
    print("向量库修复：%s" % a.db)
    print("=" * 70)
    if not r.get("ok"):
        print("  ❌ %s" % r.get("错误"))
        return 1
    if r.get("备份"):
        print("  备份      %s" % r["备份"])
    print("  %s" % r.get("说明", "完成"))
    print("  修复 %d / 删除 %d（写入：%s）"
          % (r["修复"], r["删除"], "是" if r["已写入"] else "否"))
    if r["已写入"]:
        print("\n  下次启动时向量库会按新的维度正常加载。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
