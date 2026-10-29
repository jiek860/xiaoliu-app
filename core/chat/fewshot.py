# -*- coding: utf-8 -*-
"""少样本示例选择（批次 42.5）+ 反思失败库/建议晋升（批次 48.1/48.2）。

从 ``core/chat/data/chat_fewshot.json``（随包种子；``data/chat_fewshot.json``
可覆盖）里按当前话题 / 计划动作挑 2 组短对话，让模型「照着长度和语气说话」，
而不是靠形容词描述风格。

48.1 起这里还存反思失败样本：低分回答进 ``data/chat_failures.jsonl``，
脱敏、同类去重、可复查；48.2 把同类建议聚合成候选规则，**必须人工确认**
才写入 ``data/chat_promoted_rules.json``（人格卡与 critic 只读这个文件），
撤销即删规则并记审计。所有函数都不调模型，坏文件按空处理。

只在人格卡 `on` 或规划器注入时使用；默认 shadow 不改变提示词。
"""
import hashlib
import json
import os
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

try:
    from core.redaction import redact_text
except ImportError:  # pragma: no cover
    def redact_text(value, limit=1000):
        text = str(value if value is not None else "")
        return text[:limit] if limit else text

from core.chat.critic import (FALLBACK_RULES, LOW_DIM, LOW_TOTAL,
                              rubric_dims, rubric_issues, rubric_total)

_SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "chat_fewshot.json")
_BUILTIN = [
    {"u": "在吗", "a": "在，说。"},
    {"u": "今天累死了", "a": "听起来是被榨干了。先歇会儿，别急着复盘。"},
]
_CACHE = {}

FAIL_FILE = "chat_failures.jsonl"
CAND_FILE = "chat_rule_candidates.json"
PROMOTED_FILE = "chat_promoted_rules.json"
AUDIT_FILE = "chat_promoted_audit.jsonl"
FAIL_KEEP = 200
FAIL_TTL_DAYS = 7
CAND_TTL_DAYS = 30


def _read(path):
    try:
        stat = os.stat(path)
        hit = _CACHE.get(path)
        if hit and hit[0] == stat.st_mtime:
            return hit[1]
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        rows = [r for r in data if isinstance(r, dict) and r.get("u") and r.get("a")]
        _CACHE[path] = (stat.st_mtime, rows)
        return rows
    except (OSError, ValueError, TypeError):
        return []


def pick(base=".", topic="", act="", limit=2):
    """按 act（权重 2）与 topic（权重 1）打分，返回最多 limit 组。"""
    path = os.path.join(str(base or "."), "data", "chat_fewshot.json")
    rows = _read(path)
    if not rows and os.path.abspath(path) != _SEED_PATH:
        rows = _read(_SEED_PATH)       # 用户没放覆盖文件时用随包种子
    fallback = not rows
    rows = rows or list(_BUILTIN)
    topic = str(topic or "")
    act = str(act or "")
    scored = []
    for order, row in enumerate(rows):
        score = (2 if act and row.get("act") == act else 0) + (
            1 if topic and row.get("topic") == topic else 0)
        if score > 0:
            scored.append((-score, order, row))
    scored.sort(key=lambda item: (item[0], item[1]))
    if not scored and fallback:
        picked = rows[:max(0, int(limit or 0))]
        return [{"u": str(row["u"]), "a": str(row["a"])} for row in picked]
    return [{"u": str(row["u"]), "a": str(row["a"])}
            for _, _, row in scored[:max(0, int(limit or 0))]]


# ================================================================
# 失败库 / 建议晋升（48.1 / 48.2）
# ================================================================
def _data_path(base, name):
    return os.path.join(str(base or "."), "data", name)


def _norm(text):
    return "".join(str(text or "").lower().split())


def read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    try:
        with open(path, encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError as exc:
        _x6_swallowed(__name__, exc, "read_jsonl")
    return rows


def write_jsonl(path, rows):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            for row in rows:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except OSError as exc:
        _x6_swallowed(__name__, exc, "write_jsonl")


def load_json(path, default):
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8"))
            return data if isinstance(data, dict) else default
        except (OSError, TypeError, ValueError) as exc:
            _x6_swallowed(__name__, exc, "load_json")
    return default


def save_json(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        _x6_swallowed(__name__, exc, "save_json")


def failure_rows(base):
    return read_jsonl(_data_path(base, FAIL_FILE))


def record_failure(base, user_input, ai_response, *, dims=None, issues=None,
                   suggestion="", category="", shadow=False, source="规则",
                   enabled=True, keep=FAIL_KEEP):
    """低分样本入库：脱敏、同类去重、保留最近 N 条。"""
    if not enabled:
        return None
    dims = dims or rubric_dims(user_input, ai_response)
    issues = list(issues or rubric_issues(dims, user_input, ai_response))
    category = category or (issues[0] if issues else "general")
    user = redact_text(str(user_input or ""), limit=80)
    answer = redact_text(str(ai_response or ""), limit=120)
    sig = hashlib.sha1(("%s|%s|%s" % (
        _norm(user)[:60], _norm(answer)[:40], category)
    ).encode("utf-8", "replace"), usedforsecurity=False).hexdigest()[:12]
    now = int(time.time())
    rows = failure_rows(base)
    for row in rows:
        if row.get("签名") == sig and row.get("状态") == "open" \
                and now - int(row.get("ts") or 0) <= FAIL_TTL_DAYS * 86400:
            row["seen"] = int(row.get("seen") or 1) + 1
            row["ts"] = now
            write_jsonl(_data_path(base, FAIL_FILE), rows)
            return row.get("id")
    fid = "f_%d_%s" % (now, sig[:6])
    row = {
        "id": fid, "ts": now, "用户": user, "回答": answer,
        "维度": dims, "总分": rubric_total(dims), "问题": issues,
        "类别": category, "建议": str(suggestion or "")[:100],
        "状态": "open", "seen": 1, "影子": bool(shadow),
        "来源": source, "复查": 0, "复现": 0, "签名": sig,
    }
    rows.append(row)
    write_jsonl(_data_path(base, FAIL_FILE), rows[-int(keep or FAIL_KEEP):])
    return fid


def mark_failure(base, failure_id, status="resolved"):
    rows = failure_rows(base)
    hit = None
    for row in rows:
        if row.get("id") == failure_id:
            row["状态"] = status
            row["resolved_at"] = int(time.time())
            hit = row
    if hit:
        write_jsonl(_data_path(base, FAIL_FILE), rows)
        return {"ok": True, "failure": hit}
    return {"ok": False, "error": "失败样本不存在"}


def recheck_failures(base, limit=20):
    """按当前规则重算样本分数：达标自动 resolved，否则复现计数 +1。"""
    rows = failure_rows(base)
    checked = reproduced = resolved = 0
    for row in rows:
        if checked >= int(limit or 20):
            break
        if row.get("状态") != "open":
            continue
        dims = rubric_dims(row.get("用户", ""), row.get("回答", ""))
        total = rubric_total(dims)
        checked += 1
        row["复查"] = int(row.get("复查") or 0) + 1
        row["复查维度"] = dims
        if total >= LOW_TOTAL and not any(v <= LOW_DIM for v in dims.values()):
            row["状态"] = "resolved"
            row["resolved_at"] = int(time.time())
            resolved += 1
        else:
            row["复现"] = int(row.get("复现") or 0) + 1
            reproduced += 1
    write_jsonl(_data_path(base, FAIL_FILE), rows)
    rate = round(reproduced / float(checked), 3) if checked else 0.0
    return {"ok": True, "checked": checked, "reproduced": reproduced,
            "resolved": resolved, "复现率": rate}


def failure_stats(base):
    rows = failure_rows(base)
    cats, seen_total = {}, 0
    for row in rows:
        seen_total += int(row.get("seen") or 1)
        cat = str(row.get("类别") or "general")
        cats[cat] = cats.get(cat, 0) + 1
    checked = sum(int(row.get("复查") or 0) for row in rows)
    repro = sum(int(row.get("复现") or 0) for row in rows)
    return {
        "总数": len(rows),
        "未解决": len([r for r in rows if r.get("状态") == "open"]),
        "累计出现": seen_total,
        "类别": dict(sorted(cats.items(), key=lambda item: -item[1])),
        "复现率": round(repro / float(checked), 3) if checked else 0.0,
        "复查次数": checked,
    }


def load_candidates(base):
    data = load_json(_data_path(base, CAND_FILE), {})
    data.setdefault("candidates", [])
    return data


def save_candidates(base, data):
    data["updated_at"] = int(time.time())
    save_json(_data_path(base, CAND_FILE), data)


def promoted_rules(base):
    data = load_json(_data_path(base, PROMOTED_FILE), {})
    rules = data.get("rules") if isinstance(data, dict) else None
    return [r for r in (rules or []) if isinstance(r, dict)]


def save_promoted(base, rules):
    save_json(_data_path(base, PROMOTED_FILE), {"version": 1, "rules": rules})


def audit_rows(base, limit=30):
    return read_jsonl(_data_path(base, AUDIT_FILE))[-int(limit or 30):]


def _audit(base, action, candidate, by):
    row = {
        "ts": int(time.time()), "action": action,
        "id": candidate.get("id", ""),
        "category": candidate.get("category", ""),
        "rule": candidate.get("rule", {}),
        "by": str(by or "user")[:40],
    }
    rows = read_jsonl(_data_path(base, AUDIT_FILE))
    rows.append(row)
    write_jsonl(_data_path(base, AUDIT_FILE), rows[-200:])


def _suggestion_category(row):
    cat = str(row.get("类别") or "").strip()
    if cat in FALLBACK_RULES:
        return cat
    issues = row.get("问题") or []
    if isinstance(issues, list):
        for issue in issues:
            if issue in FALLBACK_RULES:
                return issue
    return "general"


def promote_candidates(base, *, threshold=3, days=CAND_TTL_DAYS):
    """扫描近期低分：同类建议 ≥N 次生成候选（永不自动生效）。"""
    threshold = max(2, int(threshold or 3))
    window = max(1, int(days or CAND_TTL_DAYS))
    now = int(time.time())
    counts, samples, suggestions = {}, {}, {}
    for row in failure_rows(base):
        if now - int(row.get("ts") or now) > window * 86400:
            continue
        cat = _suggestion_category(row)
        counts[cat] = counts.get(cat, 0) + int(row.get("seen") or 1)
        samples.setdefault(cat, []).append(row.get("id"))
        if row.get("建议"):
            suggestions.setdefault(cat, []).append(str(row["建议"])[:80])
    data = load_candidates(base)
    existing = {c.get("category") for c in data["candidates"]
                if c.get("status") in ("pending", "active")}
    created = []
    for cat, count in counts.items():
        if count < threshold or cat in existing:
            continue
        rule = dict(FALLBACK_RULES.get(cat) or {
            "type": "avoid", "value": "同类问题别再犯：%s" % cat})
        cid = "c_%d_%s" % (now, hashlib.sha1(
            (cat + str(count)).encode("utf-8"), usedforsecurity=False).hexdigest()[:6])
        item = {
            "id": cid, "category": cat, "count": count,
            "suggestion": (suggestions.get(cat) or [rule["value"]])[-1],
            "samples": samples.get(cat, [])[-3:],
            "rule": rule, "status": "pending",
            "created_at": now, "decided_at": 0, "decided_by": "",
        }
        data["candidates"].append(item)
        created.append(item)
    data["candidates"] = data["candidates"][-100:]
    save_candidates(base, data)
    return {"ok": True, "created": len(created), "threshold": threshold,
            "candidates": created}


def decide_candidate(base, candidate_id, action, by="user"):
    """人工确认/撤销；只有这里会改动生效规则文件，并写审计。"""
    data = load_candidates(base)
    item = next((c for c in data.get("candidates", [])
                 if c.get("id") == candidate_id), None)
    if not item:
        return {"ok": False, "error": "候选不存在"}
    if action == "confirm" and item.get("status") not in ("pending", "revoked"):
        return {"ok": False, "error": "候选状态不可确认"}
    if action != "confirm" and item.get("status") != "active":
        return {"ok": False, "error": "候选不在生效状态"}
    item["status"] = "active" if action == "confirm" else "revoked"
    item["decided_at"] = int(time.time())
    item["decided_by"] = str(by or "user")[:40]
    save_candidates(base, data)
    rules = [r for r in promoted_rules(base) if r.get("id") != candidate_id]
    if action == "confirm":
        rule = item.get("rule") or {}
        rules.append({
            "id": item["id"], "category": item.get("category"),
            "type": rule.get("type", "avoid"), "value": rule.get("value", ""),
            "style": rule.get("style", ""),
            "banned": list(rule.get("banned") or []),
            "created_at": int(time.time()),
        })
    save_promoted(base, rules)
    _audit(base, action, item, by)
    return {"ok": True, "candidate": item}
