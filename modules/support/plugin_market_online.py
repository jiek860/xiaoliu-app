# -*- coding: utf-8 -*-
"""插件市场「在线仓库」部分。

从 modules/installed/plugin_market.py 原样搬出（该文件接近 600 行上限）。
只搬代码不改行为：这是一个 mixin，方法名与原来完全一致。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import json
import hashlib

from core.safe_http import open_url as safe_open_url
from core.path_safety import safe_join
from core.plugin_repository import (download_urls, manifest_entry_signed,
                                    remote_repo_urls, safe_plugin_filename)


class PluginMarketOnlineMixin:
    """在线仓库：清单拉取、签名下载、更新检查。"""

    def list_online(self):
        """Query explicitly enabled, host-allowlisted HTTPS sources in order."""
        urls, why = remote_repo_urls(getattr(self.trunk, "config", {}) or {})
        if not urls:
            if self.trunk:
                self.trunk._log("在线插件仓库已禁用: " + why)
            return []
        from core.net_guard import get_net_guard
        ng = get_net_guard(self.trunk)
        errors = []
        for base in urls:
            try:
                u = base + "/manifest.json"
                d = ng.check(u, module="plugin_market", purpose="plugin_index")
                if not d.get("allow"):
                    raise PermissionError(d.get("reason") or "网络请求被拒绝")
                data = json.loads(safe_open_url(u, timeout=8).read().decode("utf-8-sig"))
                items = data if isinstance(data, list) else data.get("modules")
                if isinstance(items, list):
                    return [m for m in items if isinstance(m, dict)]
            except Exception as e:
                errors.append("%s: %s" % (base, str(e)[:50]))
        if self.trunk:
            self.trunk._log("在线插件仓库全部失败: " + " | ".join(errors[:2]))
        return []

    def download(self, filename, meta=None):
        """Download one signed remote plugin from the first valid source.

        Every source is tried only for transport availability. The file is never
        written unless the manifest signature verifies successfully.
        """
        urls, why = remote_repo_urls(getattr(self.trunk, "config", {}) or {})
        if not urls:
            return {"ok": False, "原因": why}
        filename = safe_plugin_filename(filename)
        if not filename:
            return {"ok": False, "原因": "非法模块文件名"}
        dst = safe_join(self.installed_dir, filename)
        if not dst:
            return {"ok": False, "原因": "模块落点越界"}
        if meta is None:
            meta = self._repo_meta(filename)
        if not manifest_entry_signed(meta):
            return {"ok": False, "原因": "远程插件必须携带有效 RSA 签名"}
        from core.net_guard import get_net_guard
        ng = get_net_guard(self.trunk)
        errors, raw, verified_why = [], None, ""
        for u in download_urls(urls, filename):
            try:
                d = ng.check(u, module="plugin_market", purpose="plugin_download")
                if not d.get("allow"):
                    raise PermissionError(d.get("reason") or "网络请求被拒绝")
                candidate = safe_open_url(u, timeout=10).read()
                res, source_why = self._verify_meta(candidate, meta)
                # Remote plugins intentionally do not consult _allow_unsigned().
                if res is None:
                    return {"ok": False,
                            "原因": "远程插件没有有效签名，已拒绝: " + source_why}

                if res is True:
                    raw, verified_why = candidate, source_why
                    break
                errors.append("%s: %s" % (u, source_why))
            except Exception as e:
                errors.append("%s: %s" % (u, str(e)[:60]))
        if raw is None:
            return {"ok": False, "原因": "所有插件仓库均失败或验签不通过: " +
                    " | ".join(errors[:3])}
        api_ok, api_why = self._validate_plugin_payload(raw, meta, filename)
        if not api_ok:
            return {"ok": False, "原因": api_why}
        from core.plugin_installer import backup_plugin_file
        backup = backup_plugin_file(self.installed_dir, self.backup_dir, filename)
        tmp = dst + ".download"
        try:
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, dst)
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass  # 静默是故意的：临时文件清理失败不影响主流程
            return {"ok": False, "原因": "写入失败: " + str(e)[:60]}
        try:
            from core.plugin_governance import PluginGovernance
            gov = PluginGovernance(self.base)
            gi = gov.inspect(raw.decode("utf-8", errors="replace")[:200000], meta)
            gov.record(filename, source="download", trust=gi.get("trust", ""),
                       permissions=gi.get("permissions", []),
                       sha256=hashlib.sha256(raw).hexdigest())
        except Exception:
            gi = {}
        return {"ok": True, "msg": "已下载: %s（%s）" % (filename, verified_why),
                "备份": backup, "治理": gi}

    def check_updates(self, online=None):
        """Return compatible plugin updates using the signed manifest metadata."""
        from core.plugin_registry import select_update
        from core.version import get_version
        online = self.list_online() if online is None else list(online)
        host = str(get_version())
        by_file = {}
        for meta in online:
            by_file.setdefault(str(meta.get("file") or ""), []).append(meta)
        updates, blocked = [], []
        for fname, candidates in by_file.items():
            current = str(self._repo_meta(fname).get("version") or "0.0.0")
            plan = select_update(current, candidates, host_version=host)
            if plan.get("latest"):
                updates.append({"file": fname, "current": current,
                                "latest": plan["latest"]})
            blocked.extend(plan.get("blocked") or [])
        return {"ok": True, "updates": updates, "blocked": blocked}
