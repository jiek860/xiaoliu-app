# -*- coding: utf-8 -*-
"""hunk 落盘 / 逐段快照撤销 / 作用域护栏（第 6 批 深度③④）。

从 `core/hunk_edit.py` 拆出（该文件到 600 行上限）：hunk_edit 只留纯文本算法
（形状归一化、定位分级、预演、3-way）；这里负责"真的写盘、留快照、能撤销"。

为什么每个 hunk 一份快照
----------------------
整文件一份备份只能"整体撤销"。逐 hunk 留快照后，用户可以只后悔某一段：
`undo_hunk` 把文件恢复到"这个 hunk 应用之前"，`undo_all` 回到第一次改动之前。
"""
from __future__ import annotations

import json
import os
import shutil
import time

from core.hunk_edit import (_apply_span, _engine, _read, _rel, _write,
                            conflict_report, explain_status, locate,
                            normalize_hunk)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def _backup_path(backup_dir, rel, index):
    safe = rel.replace("/", "__").replace("\\", "__")
    return os.path.join(backup_dir, "%s.h%02d.bak" % (safe, int(index)))


def apply_hunks(root, patch, selected_hunks=None, backup_base=None,
                conflict_policy="ask", base_texts=None, format_first=False):
    """逐 hunk 落盘：每个 hunk 各留一份快照，可单独撤销。

    ``conflict_policy``：
    * ``ask``  记录冲突但照常应用（界面会把冲突摆出来让用户复核）；
    * ``block`` 有冲突就不动这个文件（保守，避免覆盖手改）；
    * ``mine``  有冲突保留用户内容（跳过这个文件）；
    * ``ai``    忽略 3-way 检查（老行为）。
    非 update 的文件（create/write/delete/rename）仍交给 patch_engine。

    ``format_first``（第 7 批 深度⑤）：应用前先把目标文件格式化，再确认
    hunk 还能定位；定位不了就整体回退格式化，绝不停在"格式化了、补丁没落"。
    """
    root = os.path.abspath(root)
    patch = dict(patch or {})
    patch_id = str(patch.get("patch_id") or
                   ("patch_hunks_" + time.strftime("%Y%m%d_%H%M%S")))
    fmt = {}
    if format_first:
        try:
            from core.code_format import format_patch_files
            fmt = format_patch_files(root, patch)
        # 静默是故意的 - 格式化是"锦上添花"，失败必须继续应用补丁
        except Exception as e:
            _x6_swallowed(__name__, e, "format before hunk apply")
            fmt = {"ok": False, "reason": str(e)[:150]}
    backup_dir = os.path.join(backup_base or os.path.join(
        root, "data", "patch_backups"), patch_id)
    selected = None if selected_hunks is None else set(selected_hunks)
    manifest = {"patch_id": patch_id, "root": root, "created_at": time.time(),
                "files": []}
    applied, errors, conflicts, rows = [], [], [], []
    for fi, fp in enumerate(patch.get("files") or []):
        rel = _rel(fp.get("path"))
        op = str(fp.get("op") or ("update" if fp.get("hunks") is not None
                                 else "write"))
        if op != "update":
            sub = {"patch_id": "%s_f%02d" % (patch_id, fi),
                   "goal": str(patch.get("goal") or ""), "files": [fp]}
            try:
                r = _engine().apply_patch(root, sub, backup_base=backup_base,
                                          require_clean=False)
            except Exception as e:  # 静默是故意的 - 错误收进结果，不中断整批
                errors.append("%s: %s" % (rel, e))
                continue
            applied.extend(r.get("applied") or [])
            manifest["files"].append({"path": rel, "op": op, "existed": True,
                                      "backup": "", "hunks": [],
                                      "manifest": str(r.get("backup_manifest") or "")})
            continue
        text = _read(root, rel)
        if text is None:
            errors.append("文件不存在: " + rel)
            continue
        base = (base_texts or {}).get(rel)
        if base is not None and base != text and conflict_policy != "ai":
            found = conflict_report(root, {"files": [fp]}, {rel: base})
            if found:
                conflicts.extend(found)
                if conflict_policy in ("block", "mine"):
                    errors.append("%s 与磁盘最新内容冲突（%d 处），按策略跳过"
                                  % (rel, len(found)))
                    continue
        os.makedirs(backup_dir, exist_ok=True)
        file_rows = []
        changed = False
        for hi, raw in enumerate(fp.get("hunks") or []):
            key = "%s:%d" % (rel, hi)
            row = {"key": key, "index": hi, "status": "missing", "line": 0,
                   "backup": "", "noop": False, "error": "", "skipped": False}
            if selected is not None and key not in selected:
                row["skipped"] = True
                file_rows.append(row)
                rows.append(row)
                continue
            try:
                hunk = normalize_hunk(raw, text)
            except ValueError as e:
                row["error"] = str(e)
                errors.append("%s#%d: %s" % (rel, hi, e))
                file_rows.append(row)
                rows.append(row)
                continue
            current = _read(root, rel) or ""
            found = locate(current, hunk)
            row["status"] = found["status"]
            row["line"] = found["line"]
            if found["span"] is None:
                msg = "%s#%d: %s" % (rel, hi, explain_status(found["status"]))
                row["error"] = msg
                errors.append(msg)
                file_rows.append(row)
                rows.append(row)
                continue
            bak = _backup_path(backup_dir, rel, hi)
            shutil.copy2(_engine()._safe_path(root, rel), bak)
            row["backup"] = bak
            new_text = _apply_span(current, found["span"], hunk.get("new"))
            row["noop"] = new_text == current
            if not row["noop"]:
                _write(root, rel, new_text)
                changed = True
            file_rows.append(row)
            rows.append(row)
        if changed and rel not in applied:
            applied.append(rel)
        manifest["files"].append({"path": rel, "op": op, "existed": True,
                                  "backup": "", "hunks": file_rows})
    manifest_path = os.path.join(backup_dir, "manifest.json")
    try:
        os.makedirs(backup_dir, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except OSError as e:
        errors.append("备份清单写入失败: " + str(e)[:120])
        manifest_path = ""
    return {"ok": not errors, "patch_id": patch_id, "applied": applied,
            "hunks": rows, "conflicts": conflicts, "errors": errors,
            "format": fmt, "manifest": manifest_path,
            "backup_manifest": manifest_path}


def _load(manifest_path):
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def list_undo_points(manifest_path):
    """列出可撤销点：``[{path, index, backup, line}]``。"""
    try:
        manifest = _load(manifest_path)
    except (OSError, ValueError):
        return []
    out = []
    for item in manifest.get("files") or []:
        for row in item.get("hunks") or []:
            if not row.get("backup"):
                continue
            out.append({"path": item.get("path"), "index": row.get("index"),
                        "backup": row.get("backup"), "line": row.get("line")})
    return out


def undo_hunk(manifest_path, rel, index):
    """把文件恢复到"这个 hunk 应用之前"的状态（同文件后面的 hunk 会一起回退）。"""
    rel = _rel(rel)
    try:
        manifest = _load(manifest_path)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": "读不了清单: " + str(e)[:120]}
    for item in manifest.get("files") or []:
        if _rel(item.get("path")) != rel:
            continue
        for row in item.get("hunks") or []:
            if int(row.get("index", -1)) != int(index):
                continue
            bak = str(row.get("backup") or "")
            if not bak or not os.path.isfile(bak):
                return {"ok": False, "error": "这个 hunk 没有快照，无法单独撤销"}
            root = str(manifest.get("root") or "")
            try:
                target = _engine()._safe_path(root, rel)
            except Exception as e:  # 静默是故意的 - 路径异常作为结果返回
                return {"ok": False, "error": str(e)[:120]}
            shutil.copy2(bak, target)
            return {"ok": True, "restored": [rel], "path": rel, "index": int(index)}
    return {"ok": False, "error": "清单里没有这个 hunk: %s#%s" % (rel, index)}


def undo_all(manifest_path):
    """整批撤销：每个文件恢复到自己第一个 hunk 之前的快照。"""
    try:
        manifest = _load(manifest_path)
    except (OSError, ValueError) as e:
        return {"ok": False, "restored": [], "error": "读不了清单: " + str(e)[:120]}
    root = str(manifest.get("root") or "")
    restored = []
    for item in manifest.get("files") or []:
        rel = _rel(item.get("path"))
        rows = list(item.get("hunks") or [])
        bak = str(rows[0].get("backup") or "") if rows else ""
        if not bak and item.get("manifest"):
            try:
                r = _engine().rollback(str(item["manifest"]))
                restored.extend(r.get("restored") or [])
            except Exception as e:  # 静默是故意的 - 单个文件回滚失败继续
                restored.append("%s(失败: %s)" % (rel, str(e)[:60]))
            continue
        if not bak or not os.path.isfile(bak):
            continue
        try:
            shutil.copy2(bak, _engine()._safe_path(root, rel))
            restored.append(rel)
        except Exception as e:  # 静默是故意的 - 继续撤销其它文件
            restored.append("%s(失败: %s)" % (rel, str(e)[:60]))
    return {"ok": True, "restored": restored}


# ---------------------------------------------------------------- 作用域
def _in_scope(rel, allowed):
    rel = _rel(rel)
    for item in allowed:
        if rel == item or rel.startswith(item.rstrip("/") + "/"):
            return True
    return False


def scope_guard(patch, allowed_files, strict=True):
    """深度④ 作用域护栏：只允许改任务相关文件，越界单独审批。

    ``allowed_files`` 为空表示"不设限"（老调用保持原行为）；
    有值但 patch 想改外的文件 → ``violations`` 列出，``requires_approval``
    为 True 交给上层二次审批；``strict=True`` 时 ``blocked`` 也为 True。
    """
    allowed = [_rel(x) for x in (allowed_files or []) if str(x or "").strip()]
    if not allowed:
        return {"ok": True, "violations": [], "requires_approval": False,
                "blocked": False, "allowed": []}
    violations = []
    for fp in (patch or {}).get("files") or []:
        rel = _rel(fp.get("path"))
        new_rel = _rel(fp.get("new_path") or fp.get("to"))
        if _in_scope(rel, allowed) and (not new_rel or _in_scope(new_rel, allowed)):
            continue
        violations.append({"path": rel, "new_path": new_rel,
                           "reason": "不在本次任务允许修改的文件范围内"})
    return {"ok": not violations or not strict, "violations": violations,
            "requires_approval": bool(violations),
            "blocked": bool(violations and strict), "allowed": allowed,
            "summary": ("%d 个文件越界：%s" % (
                len(violations), ", ".join(v["path"] for v in violations))
                if violations else "")}
