# -*- coding: utf-8 -*-
"""Patch 备份、清单合并与回滚（2026-10-31 拆分）。

从 `core/patch_engine.py` 拆出（该文件已到 600 行上限）。这里只负责
「备份点 → 清单 → 回滚」这条链路；校验、预演、应用仍在 patch_engine。

对外导入路径不变：`from core.patch_engine import rollback` 仍然可用。
"""
import json
import os
import shutil
import time

# 说明：_safe_path / PatchError 放在 core.patch_engine。为避免循环导入，
# 这里在**函数调用时**再取（patch_engine 完成加载后才会有人调 rollback）。
def _engine():
    from core import patch_engine
    return patch_engine


def _backup_file(root, rel, p, backup_dir):
    if not os.path.isfile(p):
        return ""
    safe_name = rel.replace("/", "__").replace("\\", "__")
    bak = os.path.join(backup_dir, safe_name + ".bak")
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    shutil.copy2(p, bak)
    return bak


def _merge_manifests(backup_base, normalized, root, manifests):
    """把每组备份清单合成一份，一次 rollback 就能撤销整批修改。"""
    if not manifests:
        return ""
    try:
        merged = {"patch_id": normalized.get("patch_id", ""), "root": root,
                  "created_at": time.time(), "files": []}
        for path in manifests:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            merged["files"].extend(data.get("files") or [])
        folder = os.path.join(backup_base, normalized.get("patch_id", "patch"))
        os.makedirs(folder, exist_ok=True)
        merged_path = os.path.join(folder, "manifest.json")
        with open(merged_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        return merged_path
    except (OSError, ValueError):
        # 合并失败时返回空，调用方改记每组清单，撤销能力不丢。
        return ""


def _rollback_manifest(manifest):
    eng = _engine()
    root = manifest.get("root") or ""
    restored = []
    for item in reversed(manifest.get("files") or []):
        op = item.get("op") or "update"
        try:
            path = eng._safe_path(root, item.get("path"))
            new_path = item.get("new_path") or ""
            backup = item.get("backup") or ""
            existed = bool(item.get("existed", True))
            if op == "create" and not existed:
                if os.path.isfile(path):
                    os.remove(path)
                restored.append(item.get("path"))
            elif op == "rename" and new_path:
                src = eng._safe_path(root, new_path)
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
    eng = _engine()
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        raise eng.PatchError("读不了备份清单: " + str(e)) from e
    restored = _rollback_manifest(manifest)
    return {"ok": True, "restored": restored}
