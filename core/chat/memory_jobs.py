# -*- coding: utf-8 -*-
"""记忆周巩固任务（批次 43.5）。

只做低风险的清理，不生成新记忆：
    删除已过期卡、合并同 id 重复卡、把总量压到上限（默认 800 条）。

改写前先留一份 ``memory_cards.jsonl.bak``；任何异常都静默返回统计，
由 scheduler 的 `_safe_run` 记录，不影响聊天。
"""
import json
import os
import shutil
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

DEFAULT_MAX_CARDS = 800


def _load_rows(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fp:
            lines = fp.readlines()
    except OSError:
        return rows
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError) as e:
            _x6_swallowed(__name__, e, "bad_line")
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _created(row):
    for key in ("created_at", "time", "date"):
        value = row.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0.0


def _row_id(row):
    return str(row.get("id") or "")


def _expired(row, now):
    value = row.get("expires_at")
    try:
        return value is not None and float(value) <= float(now)
    except (TypeError, ValueError):
        return False


def _write_atomic(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def weekly_consolidate(base=".", *, now=None, max_cards=DEFAULT_MAX_CARDS):
    """过期清理 + 同 id 去重 + 总量上限；返回统计（含失败信息）。"""
    base = str(base or ".")
    path = os.path.join(base, "data", "memory_cards.jsonl")
    now = float(now or time.time())
    stats = {"before": 0, "after": 0, "removed_expired": 0,
             "removed_dupes": 0, "trimmed": 0, "backup": "",
             "changed": False, "error": ""}
    if not os.path.exists(path):
        return stats
    rows = _load_rows(path)
    stats["before"] = len(rows) if rows else _count_lines(path)
    # 1) 过期
    kept = []
    for row in rows:
        if _expired(row, now):
            stats["removed_expired"] += 1
            continue
        kept.append(row)
    # 2) 同 id 去重：保留后出现（更新）的那条
    by_id, order = {}, []
    for row in kept:
        cid = _row_id(row)
        if not cid:
            order.append(row)                 # 旧卡没有 id，保留
            continue
        if cid in by_id:
            stats["removed_dupes"] += 1
            order[order.index(by_id[cid])] = row
            by_id[cid] = row
        else:
            by_id[cid] = row
            order.append(row)
    # 3) 总量上限：保留最新的 max_cards 条
    limit = max(1, int(max_cards or DEFAULT_MAX_CARDS))
    if len(order) > limit:
        indexed = list(enumerate(order))
        indexed.sort(key=lambda item: (-_created(item[1]), -item[0]))
        keep = set(i for i, _row in indexed[:limit])
        stats["trimmed"] = len(order) - limit
        order = [row for i, row in enumerate(order) if i in keep]
    stats["after"] = len(order)
    if not (stats["removed_expired"] or stats["removed_dupes"] or stats["trimmed"]):
        return stats
    try:
        backup = path + ".bak"
        shutil.copyfile(path, backup)
        stats["backup"] = backup
        _write_atomic(path, order)
        stats["changed"] = True
    except Exception as e:
        _x6_swallowed(__name__, e, "consolidate")
        stats["error"] = str(e)[:120]
    return stats


def _count_lines(path):
    try:
        with open(path, encoding="utf-8") as fp:
            return sum(1 for line in fp if line.strip())
    except OSError:
        return 0
