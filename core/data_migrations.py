# -*- coding: utf-8 -*-
"""数据文件版本迁移：v0 -> v1 -> v2。

为什么要有 v0
-------------
v0 指没有版本登记、也没有 schema_version 字段的旧数据。它不能直接
按 v2 的假设去读，也不该直接标成 v2；必须按顺序跑：

    v0 -> v1：把旧格式收敛成可识别的稳定结构（只做无损/可解释的归一化）
    v1 -> v2：补齐当前字段、SQLite 列和 schema_version 标记

安全原则
--------
* 迁移前先备份到 data/_migrations/backup_*；
* 每一步先写临时文件，再原子替换；失败不覆盖原文件；
* JSONL 坏行不静默丢弃，原文写入 .bad_lines sidecar；
* SQLite 用事务和 x6_meta 版本表；
* 迁移失败会把错误写进报告，界面/自检能看到。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time

TARGET_VERSION = 2
SOURCE_VERSION = 0


def _now_tag():
    return time.strftime("%Y%m%d_%H%M%S") + "_%06d" % int(
        (time.time() % 1) * 1000000)


def _backup(base, name):
    src = os.path.join(base, "data", name)
    if not os.path.isfile(src):
        return ""
    d = os.path.join(base, "data", "_migrations", "backup_" + _now_tag())
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, name)
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        if os.path.isfile(src + suffix):
            shutil.copy2(src + suffix, dst + suffix)
    return dst


def _atomic_text(path, text):
    tmp = path + ".migrate_tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _atomic_json(path, data):
    _atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _load_json_dict(path, label):
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError("%s 顶层不是 dict" % label)
    return data


def _parse_jsonl(path):
    """读取任意 JSON 值；坏行保留原文，不在这里丢弃。"""
    values, bad = [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue
            try:
                values.append(json.loads(raw))
            except Exception as e:
                bad.append((line_no, raw, str(e)[:160]))
    return values, bad


def _write_jsonl(path, records):
    _atomic_text(path, "".join(
        json.dumps(x, ensure_ascii=False) + "\n" for x in records))


def _write_bad(path, bad):
    if not bad:
        return ""
    p = path + ".bad_lines"
    with open(p, "w", encoding="utf-8") as f:
        f.write("# 迁移时无法解析的原始行（未删除，供人工修复）\n")
        for line_no, raw, err in bad:
            f.write("line %d\t%s\t%s\n" % (line_no, raw, err))
    return p


def _as_text(value, limit=4000):
    return str(value if value is not None else "")[:limit]


# ---------------------------------------------------------------------------
# v0 -> v1：旧格式归一化
# ---------------------------------------------------------------------------

def _memory_cards_v0_v1(base, name, src):
    values, bad = _parse_jsonl(src)
    out = []
    for value in values:
        if isinstance(value, dict):
            rec = dict(value)
        elif isinstance(value, (list, tuple)):
            rec = {"facts": list(value)}
        else:
            rec = {"facts": [value]}
        facts = rec.get("facts")
        if facts is None:
            for key in ("fact", "content", "text", "memory"):
                if key in rec:
                    facts = rec[key]
                    break
        if isinstance(facts, str):
            facts = [facts]
        if not isinstance(facts, list):
            facts = [] if facts is None else [facts]
        rec["facts"] = [_as_text(x, 300) for x in facts if _as_text(x).strip()]
        if "time" not in rec:
            rec["time"] = time.time()
        rec["schema_version"] = 1
        out.append(rec)
    _write_jsonl(src, out)
    return {"records": len(out), "bad": len(bad), "bad_file": _write_bad(src, bad)}


def _dreams_v0_v1(base, name, src):
    values, bad = _parse_jsonl(src)
    out = []
    for value in values:
        if isinstance(value, dict):
            rec = dict(value)
        else:
            rec = {"text": value}
        dream = rec.get("dream")
        if dream is None:
            dream = rec.get("text") or rec.get("content") or ""
        rec["dream"] = _as_text(dream)
        rec.setdefault("date", time.strftime("%Y-%m-%d"))
        rec["schema_version"] = 1
        out.append(rec)
    _write_jsonl(src, out)
    return {"records": len(out), "bad": len(bad), "bad_file": _write_bad(src, bad)}


def _personality_v0_v1(base, name, src):
    data = _load_json_dict(src, "personality.json")
    if not isinstance(data.get("mood"), str):
        data["mood"] = "中性"
    try:
        data["energy"] = int(data.get("energy", 80))
    except (TypeError, ValueError):
        data["energy"] = 80
    data.setdefault("birth_time", time.time())
    data["schema_version"] = 1
    _atomic_json(src, data)
    return {"keys": len(data)}


def _config_v0_v1(base, name, src):
    data = _load_json_dict(src, "config.json")
    # v0 旧键名只做别名补齐，不覆盖已有值，避免把用户配置改错。
    aliases = {
        "api_key": "cloud_key",
        "api_url": "cloud_url",
        "api_model": "cloud_model",
        "ollama": "ollama_url",
    }
    for old, new in aliases.items():
        if new not in data and old in data:
            data[new] = data[old]
    data["config_schema"] = 1
    _atomic_json(src, data)
    return {"keys": len(data)}


def _memory_v0_v1(base, name, src):
    data = _load_json(src)
    if isinstance(data, list):
        data = {"default": data}
    if not isinstance(data, dict):
        raise ValueError("memory.json 顶层既不是 dict 也不是 list")
    out = {}
    for user, items in data.items():
        if user == "_schema_version":
            continue
        if isinstance(items, dict):
            # 极旧格式可能是 {"u": "...", "a": "..."} 的单条记忆
            items = [items]
        elif not isinstance(items, list):
            items = [] if items is None else [items]
        out[str(user)] = items
    out["_schema_version"] = 1
    _atomic_json(src, out)
    return {"users": len(out) - 1}


def _sqlite_v0_v1(base, name, src):
    conn = sqlite3.connect(src, timeout=10)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS x6_meta("
                     "key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO x6_meta(key,value) VALUES(?,?)",
                     ("schema_version", "1"))
        conn.execute("PRAGMA user_version=1")
        conn.commit()
    finally:
        conn.close()
    return {"sqlite": True, "to": 1}


# ---------------------------------------------------------------------------
# v1 -> v2：补齐当前字段与结构
# ---------------------------------------------------------------------------

def _memory_cards_v1_v2(base, name, src):
    values, bad = _parse_jsonl(src)
    out = []
    for value in values:
        rec = dict(value) if isinstance(value, dict) else {"facts": [value]}
        facts = rec.get("facts")
        if isinstance(facts, str):
            facts = [facts]
        if not isinstance(facts, list):
            facts = []
        rec["facts"] = [_as_text(x, 300) for x in facts if _as_text(x).strip()]
        rec.setdefault("feelings", "")
        rec.setdefault("follow_up", "")
        rec.setdefault("trigger", "legacy")
        rec.setdefault("time", time.time())
        rec["schema_version"] = 2
        out.append(rec)
    _write_jsonl(src, out)
    return {"records": len(out), "bad": len(bad), "bad_file": _write_bad(src, bad)}


def _dreams_v1_v2(base, name, src):
    values, bad = _parse_jsonl(src)
    out = []
    for value in values:
        rec = dict(value) if isinstance(value, dict) else {"dream": str(value)}
        rec.setdefault("date", time.strftime("%Y-%m-%d"))
        rec["dream"] = _as_text(rec.get("dream") or rec.get("text") or "")
        rec["schema_version"] = 2
        out.append(rec)
    _write_jsonl(src, out)
    return {"records": len(out), "bad": len(bad), "bad_file": _write_bad(src, bad)}


def _personality_v1_v2(base, name, src):
    data = _load_json_dict(src, "personality.json")
    defaults = {
        "mood": "中性", "energy": 80, "last_active": time.time(),
        "birth_time": time.time(), "catchphrases": [], "people": {},
        "plans": [], "narrative": [],
        "milestones": [{"name": "认识", "count": 0, "last_show": 0}],
        "relation_stage": 0, "user_name": "", "user_style": "正常",
        "hobbies": ["听音乐", "讲故事", "想你"], "new_words": [], "guilt": [],
        "last_proactive_date": "", "last_user_feeling": "中性",
    }
    for k, v in defaults.items():
        data.setdefault(k, v)
    data["schema_version"] = 2
    _atomic_json(src, data)
    return {"keys": len(data)}


def _config_v1_v2(base, name, src):
    # 使用正式配置加载器合并默认值并处理敏感字段加密。
    from core.config import load_config, save_config
    cfg = load_config(src)
    cfg["config_schema"] = 2
    save_config(src, cfg)
    return {"keys": len(cfg)}


def _memory_v1_v2(base, name, src):
    data = _load_json_dict(src, "memory.json")
    out = {}
    for user, items in data.items():
        if user == "_schema_version":
            continue
        if not isinstance(items, list):
            items = []
        clean = []
        for item in items:
            if isinstance(item, dict) and "u" in item and "a" in item:
                item = dict(item)
                item.setdefault("t", time.time())
                clean.append(item)
            elif isinstance(item, str):
                clean.append({"u": "", "a": item, "t": time.time()})
        out[str(user)] = clean
    out["_schema_version"] = 2
    _atomic_json(src, out)
    return {"users": len(out) - 1}


def _sqlite_v1_v2(base, name, src):
    conn = sqlite3.connect(src, timeout=10)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS x6_meta("
                     "key TEXT PRIMARY KEY, value TEXT)")
        if name == "chats.db":
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "messages" in tables:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
                if "session_id" not in cols:
                    conn.execute("ALTER TABLE messages ADD COLUMN "
                                 "session_id TEXT DEFAULT 'default'")
                if "ts" not in cols:
                    conn.execute("ALTER TABLE messages ADD COLUMN ts REAL")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_session "
                             "ON messages(username, session_id, ts)")
        conn.execute("INSERT OR REPLACE INTO x6_meta(key,value) VALUES(?,?)",
                     ("schema_version", "2"))
        conn.execute("PRAGMA user_version=2")
        conn.commit()
    finally:
        conn.close()
    return {"sqlite": True, "to": 2}


# 文件名 -> {源版本: 迁移函数}。迁移永远按版本递增执行，不允许跳步。
MIGRATIONS = {
    "memory_cards.jsonl": {0: _memory_cards_v0_v1, 1: _memory_cards_v1_v2},
    "dreams.jsonl": {0: _dreams_v0_v1, 1: _dreams_v1_v2},
    "personality.json": {0: _personality_v0_v1, 1: _personality_v1_v2},
    "config.json": {0: _config_v0_v1, 1: _config_v1_v2},
    "chats.db": {0: _sqlite_v0_v1, 1: _sqlite_v1_v2},
    "vectors.db": {0: _sqlite_v0_v1, 1: _sqlite_v1_v2},
    "graph.db": {0: _sqlite_v0_v1, 1: _sqlite_v1_v2},
    "memory.json": {0: _memory_v0_v1, 1: _memory_v1_v2},
}

# 兼容旧调用方：取每个文件最后一步。
MIGRATORS = {name: steps[max(steps)] for name, steps in MIGRATIONS.items()}


def version_of(registry, name):
    """登记表里的版本；缺失/损坏一律按 v0 处理。"""
    try:
        value = (registry.get("files") or {}).get(name)
        return int(value) if value is not None else SOURCE_VERSION
    except (TypeError, ValueError):
        return SOURCE_VERSION


def migrate_file(base, name, from_version=None, dry_run=False,
                 registry=None, backup=True):
    """迁移单个文件，返回 {ok, file, from, to, steps, detail, backup, error}。"""
    src = os.path.join(base, "data", name)
    out = {"ok": True, "file": name, "from": SOURCE_VERSION,
           "to": SOURCE_VERSION, "steps": [], "detail": {}, "backup": "",
           "error": ""}
    if not os.path.isfile(src):
        out.update(ok=False, error="文件不存在")
        return out
    if registry is None:
        from core import data_schema
        registry = data_schema.load(base) or {}
    start = version_of(registry, name) if from_version is None else int(from_version)
    out["from"] = start
    out["to"] = start
    if start >= TARGET_VERSION:
        return out
    if start < SOURCE_VERSION:
        start = SOURCE_VERSION
        out["from"] = start
    steps = MIGRATIONS.get(name)
    if not steps:
        out.update(ok=False, error="没有迁移器: " + name)
        return out
    if dry_run:
        out["steps"] = ["v%d->v%d" % (v, v + 1)
                        for v in range(start, TARGET_VERSION)]
        out["to"] = TARGET_VERSION
        return out
    if backup:
        out["backup"] = _backup(base, name)
    try:
        for v in range(start, TARGET_VERSION):
            fn = steps.get(v)
            if fn is None:
                raise RuntimeError("缺少 v%d->v%d 迁移器" % (v, v + 1))
            detail = fn(base, name, src) or {}
            out["steps"].append("v%d->v%d" % (v, v + 1))
            out["detail"]["v%d->v%d" % (v, v + 1)] = detail
            out["to"] = v + 1
    except Exception as e:
        out.update(ok=False, error="%s: %s" % (type(e).__name__, str(e)[:360]))
    return out


def migrate_all(base, dry_run=False):
    """把 data/ 下的已登记文件按 v0->v1->v2 顺序迁移到当前版本。"""
    from core import data_schema
    report = {"ok": True, "migrated": [], "skipped": [], "errors": [],
              "backups": [], "dry_run": bool(dry_run)}
    registry = data_schema.load(base) or {}
    if int(registry.get("data_schema", 0) or 0) > data_schema.DATA_SCHEMA:
        report["ok"] = False
        report["errors"].append({
            "file": "_schema.json",
            "error": "数据登记表比当前程序新，已停止迁移；请先升级程序"})
        return report
    versions = dict(registry.get("files") or {})
    for name in data_schema.WATCHED:
        if not os.path.isfile(os.path.join(base, "data", name)):
            report["skipped"].append(name)
            continue
        got = version_of(registry, name)
        if got >= TARGET_VERSION:
            report["skipped"].append(name)
            continue
        r = migrate_file(base, name, from_version=got, dry_run=dry_run,
                         registry=registry)
        if r["ok"]:
            versions[name] = r["to"]
            report["migrated"].append(r)
            if r.get("backup"):
                report["backups"].append(r["backup"])
            if not dry_run:
                registry["files"] = versions
                registry["data_schema"] = data_schema.DATA_SCHEMA
                registry["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                data_schema.save(base, registry)
        else:
            report["ok"] = False
            report["errors"].append({"file": name, "error": r["error"]})
    if not dry_run and report["migrated"]:
        registry["data_schema"] = data_schema.DATA_SCHEMA
        registry["files"] = versions
        registry["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data_schema.save(base, registry)
    return report