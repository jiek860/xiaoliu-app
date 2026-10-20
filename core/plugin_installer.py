# -*- coding: utf-8 -*-
"""Safe plugin update/rollback helpers used by the market UI."""
from __future__ import annotations

import os
import shutil

from core.path_safety import safe_join


def backup_plugin_file(installed_dir, backup_dir, filename):
    """Copy the currently installed plugin to the rollback slot.

    Returns the backup path, or "" when there is no existing installed file.
    """
    src = safe_join(installed_dir, filename)
    dst = safe_join(backup_dir, filename)
    if not src or not dst or not os.path.isfile(src):
        return ""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def module_name_from_meta(meta):
    meta = meta or {}
    name = str(meta.get("name") or "").strip()
    if name:
        return name
    fname = str(meta.get("file") or "").strip()
    return os.path.splitext(os.path.basename(fname))[0]


def apply_update(pm, meta):
    """Download a signed update, retain a rollback copy and hot-reload it."""
    meta = dict(meta or {})
    filename = str(meta.get("file") or "").strip()
    if not filename:
        return {"ok": False, "原因": "更新元数据缺少 file"}
    name = module_name_from_meta(meta)
    backup = backup_plugin_file(pm.installed_dir, pm.backup_dir, filename)
    r = pm.download(filename, meta)
    if not r.get("ok"):
        return r
    reloaded = False
    try:
        if pm.trunk and hasattr(pm.trunk, "_load_lazy"):
            pm.trunk._load_lazy(name)
            reloaded = True
    except Exception:  # 静默是故意的 - 下次启动会重新加载
        reloaded = False
    try:
        from core.plugin_registry import InstallLedger
        InstallLedger(pm.base).record(
            name, meta.get("version"), "update",
            {"file": filename, "backup": backup, "reloaded": reloaded})
    except Exception:  # 静默是故意的 - 账本失败不影响安装结果
        pass
    return {**r, "name": name, "backup": backup, "reloaded": reloaded}
