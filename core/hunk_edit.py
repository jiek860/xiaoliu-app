# -*- coding: utf-8 -*-
"""行级编辑内核（第 6 批 B1 + 深度①~④）：hunk 归一化 / 定位 / 预演 / 3-way / 撤销 / 作用域。

为什么单独一层
--------------
`core/patch_engine.py` 已到 600 行上限，而且它的职责是"安全边界 + 落盘 + 回滚"。
hunk 的"按行号切原文、模糊锚点定位、3-way 冲突、逐 hunk 撤销、作用域护栏"是
另一套**纯文本算法**，拆到这里既能单独测试，也不让 patch_engine 继续膨胀。

hunk 的两种形状（都支持）
-----------------------
* 片段形状：``{"old": "原文唯一片段", "new": "替换内容"}``（模型最常给的）
* 行号形状：``{"start": 12, "end": 18, "new": "...", "context": 2}``
  行号 1 基、闭区间；``context`` 表示前后各带几行做锚点。
  本地按磁盘内容切出 ``old``，模型不必逐字复述原文（小模型最常错在这里）。

定位分级（``locate``）
--------------------
* ``exact``            原文唯一出现
* ``fuzzy_whitespace`` 只有空白差异（缩进/行尾空格）
* ``fuzzy_anchor``     首尾锚点行命中且中间高度相似（用户手改过也能落）
* ``duplicate``        原文出现多次，必须补上下文
* ``missing``          找不到

3-way 冲突（``three_way``）
--------------------------
``base`` 是生成补丁时的文件内容，``ours`` 是磁盘最新内容：
* 用户没碰这个 hunk 的区域 → ``clean``，直接用 AI 结果；
* 改到了同一块 → ``conflict``，给 ``keep_mine`` / ``use_ai`` / ``manual``
  三个选项 + ``merged_preview``，界面能"看得见再选"（不再静默覆盖手改）。

落盘/撤销/作用域在 ``core/hunk_apply.py``
----------------------------------------
本文件只做纯文本算法（可单测、不碰磁盘）；"真的写盘 + 每 hunk 一份快照 +
越界审批"在 hunk_apply，两个文件都控制在 600 行以内。
"""
from __future__ import annotations

import difflib
import os
import re

MAX_HUNKS = 40
MAX_PREVIEW = 4000
ANCHOR_NEAR = 400
FUZZY_RATIO = 0.6
STATUSES = ("exact", "fuzzy_whitespace", "fuzzy_anchor", "duplicate", "missing")
OK_STATUSES = ("exact", "fuzzy_whitespace", "fuzzy_anchor")
CONFLICT_OPTIONS = ("keep_mine", "use_ai", "manual")

STATUS_TEXT = {
    "exact": "精确定位",
    "fuzzy_whitespace": "空白差异定位",
    "fuzzy_anchor": "上下文锚点定位",
    "duplicate": "原文重复，需补上下文",
    "missing": "原文没找到",
    "clean": "无冲突",
    "conflict": "与手改内容冲突",
    "stale": "补丁已过期",
}


def _engine():
    """延迟拿 patch_engine（它在模块级 import 本模块，避免循环导入）。"""
    from core import patch_engine
    return patch_engine


def _rel(path):
    return str(path or "").replace("\\", "/").strip().lstrip("/")


def _read(root, rel):
    """读工作区文件；越界/不存在返回 None（不抛，预演要能列出全部问题）。"""
    eng = _engine()
    try:
        p = eng._safe_path(root, rel)
    except eng.PatchError:
        return None
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def _write(root, rel, text):
    eng = _engine()
    p = eng._safe_path(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".hunk_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(str(text or ""))
    os.replace(tmp, p)
    return p


def split_lines(text):
    return str(text or "").splitlines(True)


def _norm(line):
    return re.sub(r"\s+", " ", str(line).strip())


def _line_of(text, offset):
    return str(text or "")[:max(0, int(offset))].count("\n") + 1


def _clip(text, limit=MAX_PREVIEW):
    text = str(text or "")
    if limit and len(text) > limit:
        return text[:limit] + "\n…（预览已截断，共 %d 字）" % len(text)
    return text


def explain_status(status):
    """定位/冲突状态的中文说明（界面与时间线共用）。"""
    return STATUS_TEXT.get(str(status), "未知状态")


def is_range_shape(hunk):
    """是不是"行号形状"的 hunk（没有 old，给 start/end）。"""
    if not isinstance(hunk, dict):
        return False
    if "old" in hunk:
        return False
    return "start" in hunk or "start_line" in hunk


def hunk_from_range(file_text, start, end, new, context=0):
    """把"改第 start~end 行"变成片段形状：切出 old，拼回带上下文的新内容。

    行号 1 基、闭区间；``context`` 是前后各带几行做锚点。
    超出范围会自动夹紧，避免模型给出 start=999 直接炸掉整条链路。
    """
    lines = split_lines(file_text)
    total = len(lines)
    if total == 0:
        raise ValueError("文件为空，无法按行号切 hunk")
    try:
        start = int(start)
        end = int(end)
    except (TypeError, ValueError):
        raise ValueError("hunk 行号必须是整数") from None
    start = max(1, min(start, total))
    end = max(start, min(end, total))
    ctx = max(0, int(context or 0))
    lo = max(1, start - ctx)
    hi = min(total, end + ctx)
    old = "".join(lines[lo - 1:hi])
    before = "".join(lines[lo - 1:start - 1])
    after = "".join(lines[end:hi])
    body = str(new or "")
    if old.endswith("\n") and not body.endswith("\n"):
        body += "\n"
    return {"old": old, "new": before + body + after,
            "start_line": start, "end_line": end, "context": ctx}


def materialize_hunk(hunk, file_text):
    """行号形状 → 片段形状；已经是片段形状就原样返回副本。"""
    if not is_range_shape(hunk):
        return dict(hunk or {})
    out = dict(hunk)
    start = out.get("start", out.get("start_line"))
    end = out.get("end", start)
    built = hunk_from_range(file_text, start, end, out.get("new"),
                            out.get("context", 0))
    out.update({"old": built["old"], "new": built["new"],
                "start_line": built["start_line"]})
    return out


def normalize_hunk(hunk, file_text=None):
    """统一成 ``{old, new, reason, line}``；缺 old 且能拿到文件内容时自动切。"""
    if is_range_shape(hunk):
        if file_text is None:
            raise ValueError("行号形状的 hunk 需要文件内容才能切出 old")
        hunk = materialize_hunk(hunk, file_text)
    if not isinstance(hunk, dict):
        raise ValueError("hunk 必须是对象")
    old = str(hunk.get("old") or "")
    if not old:
        raise ValueError("hunk.old 不能为空")
    item = {"old": old, "new": str(hunk.get("new") or ""),
            "reason": str(hunk.get("reason") or ""),
            "line": hunk.get("line") or hunk.get("start_line") or 0}
    if hunk.get("anchor"):
        item["anchor"] = str(hunk.get("anchor"))
    return item


# ---------------------------------------------------------------- 定位
def _fuzzy_whitespace(text, old):
    old_lines = split_lines(old)
    if not old_lines:
        return None
    norm_old = [_norm(x) for x in old_lines]
    lines = split_lines(text)
    spans = []
    for i in range(0, max(0, len(lines) - len(old_lines) + 1)):
        window = lines[i:i + len(old_lines)]
        if [_norm(x) for x in window] == norm_old:
            start = sum(len(x) for x in lines[:i])
            spans.append((start, start + sum(len(x) for x in window)))
    return spans[0] if len(spans) == 1 else None


def _fuzzy_anchor(text, old, hunk):
    """首尾锚点行 + 中间相似度：容忍用户手改过几行，但必须唯一命中。"""
    old_lines = split_lines(old)
    if len(old_lines) < 2:
        return None
    norm_old = [_norm(x) for x in old_lines]
    first, last = norm_old[0], norm_old[-1]
    if not first or not last:
        return None
    anchor = str(hunk.get("anchor") or "")
    anchor_at = text.find(anchor) if anchor else -1
    lines = split_lines(text)
    size = len(old_lines)
    best, best_ratio, tie = None, 0.0, False
    for i in range(0, len(lines)):
        if _norm(lines[i]) != first:
            continue
        for j in range(i + 1, min(len(lines), i + size + 4)):
            if _norm(lines[j]) != last:
                continue
            window = [_norm(x) for x in lines[i:j + 1]]
            ratio = difflib.SequenceMatcher(
                None, norm_old, window, autojunk=False).ratio()
            if ratio < FUZZY_RATIO:
                continue
            start = sum(len(x) for x in lines[:i])
            if anchor_at >= 0 and abs(start - anchor_at) > ANCHOR_NEAR:
                continue
            end = start + sum(len(x) for x in lines[i:j + 1])
            if ratio > best_ratio + 1e-9:
                best, best_ratio, tie = (start, end), ratio, False
            elif abs(ratio - best_ratio) < 1e-9:
                tie = True
    return None if (best is None or tie) else best


def locate(text, hunk):
    """在文本里定位 hunk，返回 ``{status, span, line, how}``（span 为字符偏移）。"""
    text = str(text or "")
    old = str((hunk or {}).get("old") or "")
    if not old:
        return {"status": "missing", "span": None, "line": 0, "how": "empty"}
    count = text.count(old)
    if count == 1:
        start = text.index(old)
        return {"status": "exact", "span": (start, start + len(old)),
                "line": _line_of(text, start), "how": "exact"}
    if count > 1:
        return {"status": "duplicate", "span": None,
                "line": _line_of(text, text.index(old)), "how": "duplicate"}
    span = _fuzzy_whitespace(text, old)
    if span:
        return {"status": "fuzzy_whitespace", "span": span,
                "line": _line_of(text, span[0]), "how": "whitespace"}
    span = _fuzzy_anchor(text, old, hunk)
    if span:
        return {"status": "fuzzy_anchor", "span": span,
                "line": _line_of(text, span[0]), "how": "anchor"}
    return {"status": "missing", "span": None, "line": 0, "how": "missing"}


def _apply_span(text, span, new):
    return str(text or "")[:span[0]] + str(new or "") + str(text or "")[span[1]:]


def apply_hunk(text, hunk):
    """在内存里应用一个 hunk：``{ok, text, status, noop}``。"""
    found = locate(text, hunk)
    if found["span"] is None:
        return {"ok": False, "text": str(text or ""), "status": found["status"],
                "noop": False, "line": found["line"]}
    out = _apply_span(text, found["span"], (hunk or {}).get("new"))
    return {"ok": True, "text": out, "status": found["status"],
            "noop": out == str(text or ""), "line": found["line"]}


def hunk_key(patch, file_index, hunk_index):
    files = (patch or {}).get("files") or []
    rel = _rel(files[file_index].get("path")) if file_index < len(files) else ""
    return "%s:%d" % (rel, hunk_index)


def all_hunk_keys(patch):
    keys = []
    for fi, fp in enumerate((patch or {}).get("files") or []):
        if str(fp.get("op") or "update") != "update":
            continue
        for hi in range(len(fp.get("hunks") or [])):
            keys.append(hunk_key(patch, fi, hi))
    return keys


# ---------------------------------------------------------------- 预演
def plan(root, patch, selected_hunks=None):
    """逐 hunk 预演：不写盘，返回每个 hunk 的定位状态与错误。

    返回 ``{ok, files, errors, warnings, hunks}``；``hunks`` 是扁平列表，
    界面按 ``rel:index`` 找对应的那一行。
    """
    root = os.path.abspath(root)
    selected = None if selected_hunks is None else set(selected_hunks)
    files, errors, warnings, flat = [], [], [], []
    for fi, fp in enumerate((patch or {}).get("files") or []):
        rel = _rel(fp.get("path"))
        op = str(fp.get("op") or ("update" if fp.get("hunks") is not None
                                  else "write"))
        item = {"path": rel, "op": op, "hunks": [], "errors": [], "changed": False}
        if op != "update":
            files.append(item)
            continue
        text = _read(root, rel)
        if text is None:
            msg = "文件不存在: " + rel
            item["errors"].append(msg)
            errors.append(msg)
            files.append(item)
            continue
        sim = text
        for hi, raw in enumerate(fp.get("hunks") or []):
            key = "%s:%d" % (rel, hi)
            row = {"key": key, "file_index": fi, "index": hi, "reason": "",
                   "line": 0, "status": "missing", "skipped": False, "error": ""}
            try:
                hunk = normalize_hunk(raw, sim)
            except ValueError as e:
                row["error"] = str(e)
                item["errors"].append("%s#%d: %s" % (rel, hi, e))
                errors.append("%s#%d: %s" % (rel, hi, e))
                item["hunks"].append(row)
                flat.append(row)
                continue
            row["reason"] = hunk.get("reason") or ""
            row["skipped"] = selected is not None and key not in selected
            found = locate(sim, hunk)
            row["status"] = found["status"]
            row["line"] = found["line"]
            if found["span"] is None:
                msg = "%s#%d: %s" % (rel, hi, explain_status(found["status"]))
                row["error"] = msg
                item["errors"].append(msg)
                errors.append(msg)
            elif found["status"] == "fuzzy_anchor":
                warnings.append("%s#%d 靠上下文锚点定位（原文与磁盘有差异）"
                                % (rel, hi))
            if found["span"] is not None and not row["skipped"]:
                sim = _apply_span(sim, found["span"], hunk.get("new"))
            item["hunks"].append(row)
            flat.append(row)
        item["changed"] = sim != text
        files.append(item)
    return {"ok": not errors, "files": files, "errors": errors,
            "warnings": warnings, "hunks": flat}


def summary(result):
    """把 plan 结果压成一行中文，直接显示在预览条上。"""
    rows = list((result or {}).get("hunks") or [])
    if not rows:
        return "没有行级修改"
    ok = sum(1 for r in rows if r.get("status") in OK_STATUSES)
    skip = sum(1 for r in rows if r.get("skipped"))
    bad = len(rows) - ok - skip
    text = "%d 个 hunk：%d 可应用" % (len(rows), ok)
    if skip:
        text += " · %d 已跳过" % skip
    if bad:
        text += " · %d 需补上下文" % bad
    return text


# ---------------------------------------------------------------- 3-way
def three_way(base, ours, hunk, max_chars=MAX_PREVIEW):
    """对比"生成补丁时的内容"与"磁盘最新内容"，判断这段改动是否冲突。"""
    base = str(base or "")
    ours = str(ours or "")
    try:
        hunk = normalize_hunk(hunk, base)
    except ValueError as e:
        return {"status": "stale", "message": str(e), "options": {},
                "merged_preview": "", "ours_preview": _clip(ours, max_chars)}
    found_base = locate(base, hunk)
    if found_base["span"] is None:
        return {"status": "stale",
                "message": "补丁基准文件里找不到这段原文（补丁已过期）",
                "options": {}, "merged_preview": "",
                "ours_preview": _clip(ours, max_chars)}
    merged = apply_hunk(ours, hunk)
    found_ours = locate(ours, hunk)
    status = "conflict"
    if ours == base:
        status = "clean"
    elif found_ours["status"] == "exact":
        base_seg = base[found_base["span"][0]:found_base["span"][1]]
        ours_seg = ours[found_ours["span"][0]:found_ours["span"][1]]
        status = "clean" if base_seg == ours_seg else "conflict"
    use_ai = merged.get("text") if merged.get("ok") else ""
    result = {"status": status, "status_text": explain_status(status),
              "line": found_base["line"],
              "options": {"keep_mine": ours, "use_ai": use_ai, "manual": ""},
              "merged_preview": _clip(use_ai, max_chars),
              "ours_preview": _clip(ours, max_chars)}
    if status == "conflict":
        result["hint"] = ("这段你已经改过，AI 也想改：保留我的 / 用 AI 的 / "
                          "手动合并三选一")
    return result


def conflict_report(root, patch, base_texts=None):
    """一次性列出所有冲突，供审批弹窗与时间线展示。"""
    out = []
    for fp in (patch or {}).get("files") or []:
        rel = _rel(fp.get("path"))
        if str(fp.get("op") or "update") != "update":
            continue
        base = (base_texts or {}).get(rel)
        if base is None:
            continue
        ours = _read(root, rel)
        if ours is None or ours == base:
            continue
        for hi, raw in enumerate(fp.get("hunks") or []):
            report = three_way(base, ours, raw)
            if report.get("status") != "conflict":
                continue
            out.append({"key": "%s:%d" % (rel, hi), "path": rel, "index": hi,
                        "line": report.get("line", 0),
                        "merged_preview": report.get("merged_preview", ""),
                        "hint": report.get("hint", "")})
    return out


def try_materialize(hunk, text):
    """行号形状 → 片段形状；失败时原样返回（调用方决定怎么报错）。"""
    if not is_range_shape(hunk):
        return hunk
    try:
        return materialize_hunk(hunk, text)
    except (TypeError, ValueError):
        return hunk


# ---------------------------------------------------------------- 对外转发
# 落盘/撤销/作用域拆到 core/hunk_apply.py（本文件到 600 行上限）；这里保留同名
# 入口，`from core.hunk_edit import apply_hunks` 等老调用不变。
def apply_hunks(root, patch, selected_hunks=None, backup_base=None,
                conflict_policy="ask", base_texts=None, format_first=False):
    from core.hunk_apply import apply_hunks as impl
    return impl(root, patch, selected_hunks=selected_hunks,
                backup_base=backup_base, conflict_policy=conflict_policy,
                base_texts=base_texts, format_first=format_first)


def list_undo_points(manifest_path):
    from core.hunk_apply import list_undo_points as impl
    return impl(manifest_path)


def undo_hunk(manifest_path, rel, index):
    from core.hunk_apply import undo_hunk as impl
    return impl(manifest_path, rel, index)


def undo_all(manifest_path):
    from core.hunk_apply import undo_all as impl
    return impl(manifest_path)


def scope_guard(patch, allowed_files, strict=True):
    from core.hunk_apply import scope_guard as impl
    return impl(patch, allowed_files, strict=strict)
