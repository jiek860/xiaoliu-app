# -*- coding: utf-8 -*-
"""安全多文件 patch 引擎（update/create/delete/rename/write）。

核心约束：
* 文件必须位于工作区内；
* patch 带 base_hash 时先校验，防止覆盖用户刚改过的文件；
* update 的 hunk 先做唯一匹配，再做安全的空白差异模糊匹配；
* 应用前备份；任何一步失败整体回滚；
* 支持文件级 / hunk 级选择，且回滚清单包含创建、删除、重命名。
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import time
import uuid

from core.path_safety import is_within


PROTECTED_PARTS = {
    ".git", "data", "backups", "staging", "libs", "optional_libs",
    "__pycache__", ".venv", "venv", "dist", "build", "node_modules",
}


class PatchError(RuntimeError):
    pass


def sha256_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_patch(path, old, new, reason=""):
    return {
        "patch_id": "patch_" + time.strftime("%Y%m%d_%H%M%S") + "_" +
                    uuid.uuid4().hex[:6],
        "goal": reason or "修改文件",
        "files": [{
            "op": "update",
            "path": str(path).replace("\\", "/"),
            "hunks": [{
                "old": str(old), "new": str(new),
                "reason": reason or "",
            }],
        }],
    }


def _safe_path(root, rel):
    root_real = os.path.realpath(os.path.abspath(root))
    raw = str(rel or "").replace("/", os.sep).replace("\\", os.sep)
    if not raw or os.path.isabs(raw) or re.match(r"^[A-Za-z]:", raw):
        raise PatchError("路径越界: " + str(rel))
    parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p in PROTECTED_PARTS for p in parts):
        raise PatchError("受保护路径，禁止修改: " + str(rel))
    if any(p == ".." for p in parts):
        raise PatchError("路径越界: " + str(rel))
    p = os.path.realpath(os.path.join(root_real, *parts))
    if not is_within(root_real, p):
        raise PatchError("路径越界: " + str(rel))
    return p


def _norm_rel(rel):
    return str(rel or "").replace("\\", "/").strip().lstrip("/")


def _read(path):
    with open(path, encoding="utf-8", errors="strict") as f:
        return f.read()


def _op(fp):
    op = str(fp.get("op") or "").strip().lower()
    if not op:
        op = "update" if fp.get("hunks") is not None else "write"
    aliases = {"modify": "update", "edit": "update", "add": "create",
               "remove": "delete", "move": "rename"}
    op = aliases.get(op, op)
    if op not in ("update", "create", "write", "delete", "rename"):
        raise PatchError("不支持的 patch 操作: " + op)
    return op


def _locate_exact(text, old):
    n = text.count(old)
    if n == 1:
        start = text.index(old)
        return start, start + len(old), "exact"
    return None, None, ("duplicate" if n > 1 else "missing")


def _norm_line(line):
    return re.sub(r"\s+", " ", str(line).strip())


def _locate_fuzzy_lines(text, old):
    """只对行内容相同、空白不同的情况做模糊定位。

    不采用任意相似度匹配，避免把模型写错的代码应用到错误位置。
    """
    old_lines = old.splitlines()
    if not old_lines:
        return None
    old_norm = [_norm_line(x) for x in old_lines]
    text_lines = text.splitlines(True)
    candidates = []
    for i in range(0, max(0, len(text_lines) - len(old_lines) + 1)):
        window = text_lines[i:i + len(old_lines)]
        if [_norm_line(x) for x in window] == old_norm:
            start = sum(len(x) for x in text_lines[:i])
            end = start + sum(len(x) for x in window)
            candidates.append((start, end))
    if len(candidates) == 1:
        return candidates[0]
    return None


def _hunk_span(text, old):
    start, end, how = _locate_exact(text, old)
    if start is not None:
        return start, end, how
    if how == "duplicate":
        raise PatchError("原文不唯一（出现 %d 次）" % text.count(old))
    span = _locate_fuzzy_lines(text, old)
    if span:
        return span[0], span[1], "fuzzy_whitespace"
    raise PatchError("原文没找到（已尝试空白差异匹配）")


def _replace_hunk(text, old, new):
    start, end, how = _hunk_span(text, old)
    return text[:start] + str(new) + text[end:], how


def validate_patch(root, patch):
    if not isinstance(patch, dict) or not isinstance(patch.get("files"), list):
        raise PatchError("patch 格式错误：缺少 files")
    normalized = []
    virtual: dict[str, str | None] = {}   # 顺序操作模拟：支持 create/rename 之后继续 update

    def content_of(rel):
        if rel in virtual:
            return virtual[rel]
        p = _safe_path(root, rel)
        if os.path.isfile(p):
            return _read(p)
        return None

    for fp in patch["files"]:
        if not isinstance(fp, dict) or not fp.get("path"):
            raise PatchError("文件条目缺少 path")
        op = _op(fp)
        rel = _norm_rel(fp["path"])
        p = _safe_path(root, rel)
        current = content_of(rel)
        exists = current is not None
        expected = str(fp.get("base_hash") or "")
        # base_hash 只对当前磁盘上的原文件做校验。
        if os.path.isfile(p) and expected and sha256_file(p) != expected:
            raise PatchError("base_hash 不一致，文件已被修改: " + rel)

        new_rel = ""
        if op == "rename":
            new_rel = _norm_rel(fp.get("new_path") or fp.get("to") or "")
            if not new_rel:
                raise PatchError("rename 缺少 new_path: " + rel)
            if not exists:
                raise PatchError("文件不存在: " + rel)
            new_p = _safe_path(root, new_rel)
            if content_of(new_rel) is not None or os.path.exists(new_p):
                raise PatchError("重命名目标已存在: " + new_rel)

        if op in ("create", "write"):
            if "content" not in fp:
                raise PatchError("%s 缺少 content: %s" % (op, rel))
            if op == "create" and exists:
                raise PatchError("文件已存在，不能 create: " + rel)
            if op == "write" and not exists and not fp.get("allow_create"):
                raise PatchError("文件不存在，write 请使用 create: " + rel)
            virtual[rel] = str(fp.get("content") or "")
            normalized.append({
                "op": op, "path": rel, "base_hash": expected,
                "content": virtual[rel],
                "new_path": "", "hunks": [],
                "allow_create": bool(fp.get("allow_create")),
            })
            continue

        if op == "delete":
            if not exists:
                raise PatchError("文件不存在: " + rel)
            virtual[rel] = None
            normalized.append({
                "op": op, "path": rel, "base_hash": expected,
                "content": "", "new_path": "", "hunks": [],
            })
            continue

        if op == "rename":
            virtual[new_rel] = virtual.pop(rel, current)
            normalized.append({
                "op": op, "path": rel, "base_hash": expected,
                "content": "", "new_path": new_rel, "hunks": [],
            })
            continue

        # update
        if not exists:
            raise PatchError("文件不存在: " + rel)
        hunks = fp.get("hunks")
        if not isinstance(hunks, list) or not hunks:
            raise PatchError("文件没有 hunks: " + rel)
        checked = []
        simulated = current
        for i, h in enumerate(hunks):
            if not isinstance(h, dict) or "old" not in h or "new" not in h:
                raise PatchError("hunk 格式错误: %s#%d" % (rel, i))
            old = str(h.get("old") or "")
            if not old:
                raise PatchError("hunk.old 不能为空: %s#%d" % (rel, i))
            try:
                simulated, _how = _replace_hunk(
                    simulated, old, str(h.get("new") or ""))
            except PatchError as e:
                raise PatchError("%s: %s#%d" % (e, rel, i)) from e
            checked.append({"old": old, "new": str(h.get("new") or ""),
                            "reason": str(h.get("reason") or "")})
        virtual[rel] = simulated
        normalized.append({
            "op": op, "path": rel, "base_hash": expected,
            "content": "", "new_path": "", "hunks": checked,
            "allow_create": False,
        })
    return {"patch_id": str(patch.get("patch_id") or
                            ("patch_" + time.strftime("%Y%m%d_%H%M%S") + "_" +
                             uuid.uuid4().hex[:6])),
            "goal": str(patch.get("goal") or ""), "files": normalized,
            "risk": str(patch.get("risk") or "medium")}


def _syntax_error(rel, text):
    """落盘前的语法检查：只查能可靠解析的格式，避免写出半截坏文件。"""
    low = str(rel or "").lower()
    if low.endswith(".py"):
        try:
            ast.parse(str(text or ""))
        except SyntaxError as e:
            return "%s: Python 语法错误 L%s: %s" % (rel, e.lineno, e.msg)
        return ""
    if low.endswith(".json"):
        try:
            json.loads(str(text or "null"))
        except ValueError as e:
            return "%s: JSON 解析失败: %s" % (rel, str(e)[:120])
        return ""
    return ""


def _preview_text(root, fp, selected_hunks, virtual: dict[str, str | None]):
    """在内存里按顺序模拟应用；delete/rename 返回 None。

    `virtual` 让"同一 patch 里先 create 再 update"也能预演，和 apply 的顺序一致。
    """
    rel = fp["path"]
    op = fp["op"]
    if op in ("create", "write"):
        text = str(fp.get("content") or "")
        virtual[rel] = text
        return text
    if op == "delete":
        virtual[rel] = None
        return None
    if op == "rename":
        current = virtual[rel] if rel in virtual else None
        if current is None:
            p = _safe_path(root, rel)
            current = _read(p) if os.path.isfile(p) else ""
        virtual[rel] = None
        virtual[str(fp.get("new_path") or "")] = current
        return None
    body = virtual[rel] if rel in virtual else None
    if body is None:
        p = _safe_path(root, rel)
        body = _read(p) if os.path.isfile(p) else ""
    for hi, h in enumerate(fp.get("hunks") or []):
        key = "%s:%d" % (rel, hi)
        if selected_hunks is not None and key not in selected_hunks:
            continue
        body, _how = _replace_hunk(body, h["old"], h["new"])
    virtual[rel] = body
    return body


def dry_run_patch(root, patch, *, selected_files=None, selected_hunks=None):
    """多文件 patch 的整体预演：不写盘，返回每个文件的最终结果与错误。

    只有全部文件都通过（路径、hunk 唯一性、Python/JSON 语法）才返回 ok。
    调用方应在真正 apply 前执行，失败时整批不落盘。
    """
    try:
        normalized = validate_patch(root, patch)
    except PatchError as e:
        return {"ok": False, "patch_id": "", "files": [], "errors": [str(e)]}
    root = os.path.abspath(root)
    selected_files = set(_norm_rel(x) for x in (selected_files or []))
    selected_hunks = None if selected_hunks is None else set(selected_hunks)
    files, errors = [], []
    virtual: dict[str, str | None] = {}
    for fp in normalized.get("files") or []:
        rel = fp["path"]
        new_rel = _norm_rel(fp.get("new_path") or "")
        if selected_files and rel not in selected_files and \
                new_rel not in selected_files:
            continue
        item = {"path": rel, "op": fp["op"], "changed": False,
                "new_path": new_rel, "error": ""}
        try:
            text = _preview_text(root, fp, selected_hunks, virtual)
            if text is not None:
                err = _syntax_error(new_rel or rel, text)
                if err:
                    item["error"] = err
                    errors.append(err)
                p = _safe_path(root, rel)
                old = _read(p) if os.path.isfile(p) else ""
                item["changed"] = text != old
            else:
                item["changed"] = True
        except PatchError as e:
            item["error"] = str(e)
            errors.append("%s: %s" % (rel, e))
        files.append(item)
    return {"ok": not errors, "patch_id": normalized.get("patch_id", ""),
            "files": files, "errors": errors}


def unified_diff(root, patch, selected_files=None, selected_hunks=None):
    """生成可读 diff，不修改文件。"""
    root = os.path.abspath(root)
    out: list[str] = []
    selected_files = set(_norm_rel(x) for x in (selected_files or []))
    selected_hunks = None if selected_hunks is None else set(selected_hunks)
    for fp in (patch.get("files") or []):
        rel = _norm_rel(fp.get("path") or "")
        op = _op(fp)
        if selected_files and rel not in selected_files and \
                _norm_rel(fp.get("new_path") or fp.get("to") or "") not in selected_files:
            continue
        p = _safe_path(root, rel)
        old_text = _read(p) if os.path.isfile(p) else ""
        new_rel = _norm_rel(fp.get("new_path") or fp.get("to") or "")
        if op in ("create", "write"):
            new_text = str(fp.get("content") or "")
            fromfile = "/dev/null" if not old_text else "a/" + rel
            tofile = "b/" + rel
        elif op == "delete":
            new_text = ""
            fromfile, tofile = "a/" + rel, "/dev/null"
        elif op == "rename":
            new_text = old_text
            fromfile, tofile = "a/" + rel, "b/" + new_rel
        else:
            new_text = old_text
            for hi, h in enumerate(fp.get("hunks") or []):
                if selected_hunks is not None and "%s:%d" % (rel, hi) not in selected_hunks:
                    continue
                try:
                    new_text, _how = _replace_hunk(
                        new_text, str(h.get("old") or ""), str(h.get("new") or ""))
                except PatchError:
                    pass
            fromfile, tofile = "a/" + rel, "b/" + rel
        diff = difflib.unified_diff(
            old_text.splitlines(True), new_text.splitlines(True),
            fromfile=fromfile, tofile=tofile, n=3)
        out.extend(diff)
    return "".join(out)


def _backup_file(root, rel, p, backup_dir):
    if not os.path.isfile(p):
        return ""
    safe_name = rel.replace("/", "__").replace("\\", "__")
    bak = os.path.join(backup_dir, safe_name + ".bak")
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    shutil.copy2(p, bak)
    return bak


def apply_patch(root, patch, *, selected_files=None, selected_hunks=None,
                backup_base=None, require_clean=True):
    """应用 patch，返回 {ok, patch_id, applied, backup_manifest}。"""
    root = os.path.abspath(root)
    patch = validate_patch(root, patch)
    selected_files = set(_norm_rel(x) for x in (selected_files or []))
    selected_hunks = None if selected_hunks is None else set(selected_hunks)
    # 整批预演：任何一处不合法都直接失败，避免"写了一半才发现"。
    if require_clean:
        dry = dry_run_patch(root, patch, selected_files=selected_files,
                            selected_hunks=selected_hunks)
        if not dry.get("ok"):
            raise PatchError("预演失败，未写入任何文件: " +
                             "；".join(dry.get("errors") or []))
    backup_base = backup_base or os.path.join(root, "data", "patch_backups")
    backup_dir = os.path.join(backup_base, patch["patch_id"])
    os.makedirs(backup_dir, exist_ok=True)

    applied = []
    manifest = {"patch_id": patch["patch_id"], "root": root,
                "created_at": time.time(), "files": []}
    try:
        for fp in patch["files"]:
            rel = fp["path"]
            op = fp["op"]
            p = _safe_path(root, rel)
            exists = os.path.isfile(p)
            if selected_files and rel not in selected_files and \
                    fp.get("new_path") not in selected_files:
                continue

            item = {
                "path": rel, "op": op, "existed": exists,
                "backup": "", "new_path": "", "base_hash": "",
                "new_hash": "", "hunks": [],
            }
            old_text = _read(p) if exists else ""
            item["base_hash"] = sha256_text(old_text) if exists else ""

            if op in ("create", "write"):
                if selected_files and rel not in selected_files:
                    continue
                new_text = fp["content"]
                if exists:
                    item["backup"] = _backup_file(root, rel, p, backup_dir)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                tmp = p + ".patch_tmp"
                with open(tmp, "w", encoding="utf-8", newline="") as f:
                    f.write(new_text)
                os.replace(tmp, p)
                item["new_hash"] = sha256_text(new_text)
                applied.append(rel)
            elif op == "delete":
                item["backup"] = _backup_file(root, rel, p, backup_dir)
                os.remove(p)
                applied.append(rel)
            elif op == "rename":
                new_rel = fp["new_path"]
                new_p = _safe_path(root, new_rel)
                item["backup"] = _backup_file(root, rel, p, backup_dir)
                item["new_path"] = new_rel
                os.makedirs(os.path.dirname(new_p), exist_ok=True)
                os.replace(p, new_p)
                applied.append(rel)
            else:  # update
                new_text = old_text
                applied_hunks = []
                for hi, h in enumerate(fp.get("hunks") or []):
                    key = "%s:%d" % (rel, hi)
                    if selected_hunks is not None and key not in selected_hunks:
                        continue
                    new_text, _how = _replace_hunk(
                        new_text, h["old"], h["new"])
                    applied_hunks.append(hi)
                if new_text == old_text:
                    continue
                item["backup"] = _backup_file(root, rel, p, backup_dir)
                item["hunks"] = applied_hunks
                tmp = p + ".patch_tmp"
                with open(tmp, "w", encoding="utf-8", newline="") as f:
                    f.write(new_text)
                os.replace(tmp, p)
                item["new_hash"] = sha256_text(new_text)
                applied.append(rel)

            manifest["files"].append(item)

        manifest_path = os.path.join(backup_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return {"ok": True, "patch_id": patch["patch_id"],
                "applied": applied, "backup_manifest": manifest_path,
                "manifest": manifest}
    except Exception:
        # 已应用的先恢复，保证失败不留半截修改。
        _rollback_manifest(manifest)
        raise


def _rollback_manifest(manifest):
    root = manifest.get("root") or ""
    restored = []
    for item in reversed(manifest.get("files") or []):
        op = item.get("op") or "update"
        try:
            path = _safe_path(root, item.get("path"))
            new_path = item.get("new_path") or ""
            backup = item.get("backup") or ""
            existed = bool(item.get("existed", True))
            if op == "create" and not existed:
                if os.path.isfile(path):
                    os.remove(path)
                restored.append(item.get("path"))
            elif op == "rename" and new_path:
                src = _safe_path(root, new_path)
                if os.path.isfile(src):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    os.replace(src, path)
                elif backup and os.path.isfile(backup):
                    shutil.copy2(backup, path)
                restored.append(item.get("path"))
            elif backup and os.path.isfile(backup):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                shutil.copy2(backup, path)
                restored.append(item.get("path"))
            elif op == "write" and not existed:
                if os.path.isfile(path):
                    os.remove(path)
                restored.append(item.get("path"))
        except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            continue
    return restored


def rollback(manifest_path):
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        raise PatchError("读不了备份清单: " + str(e)) from e
    restored = _rollback_manifest(manifest)
    return {"ok": True, "restored": restored}
