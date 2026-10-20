# -*- coding: utf-8 -*-
"""自动更新：检查、下载、安装和模块重载。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class AutoUpdateDownloadMixin:
    def check_update(self, manifest_url=None, timeout=10):
        """拉取远端 manifest.json，**先验签**再比对版本。

        返回 {ok, has_update, current, latest, changelog, verified, manifest, error}
        验签不通过一律拒绝更新（fail closed），防止投毒更新包被下载执行。
        """
        import urllib.request
        from core import release_sign
        from core.version import get_version

        cur = get_version()
        if not manifest_url and self.trunk:
            manifest_url = self.trunk.config.get("update_manifest_url", "") or ""
        if not manifest_url:
            return {"ok": False, "has_update": False, "current": cur,
                    "error": "未配置更新地址（data/config.json 的 update_manifest_url）"}
        try:
            from core.net_guard import get_net_guard
            d = get_net_guard(self.trunk).check(
                manifest_url, module="auto_updater", purpose="update_manifest")
            if not d.get("allow"):
                raise PermissionError(d.get("reason") or "网络请求被拒绝")
            req = urllib.request.Request(manifest_url,
                                         headers={"Cache-Control": "no-cache"})
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            # utf-8-sig：兼容被记事本/PowerShell 存成带 BOM 的清单
            manifest = json.loads(raw.decode("utf-8-sig"))
        except Exception as e:
            return {"ok": False, "has_update": False, "current": cur,
                    "error": "拉取更新清单失败: " + str(e)[:80]}

        verified = release_sign.verify_manifest(
            manifest, release_sign.load_release_pubkey(self.base))
        if not verified:
            if not self._allow_unsigned_update():
                return {"ok": False, "has_update": False, "current": cur,
                        "verified": False,
                        "latest": str(manifest.get("version", "")),
                        "error": "更新清单验签失败（签名缺失或被篡改），已拒绝更新。\n"
                                 "发版请先运行 python sign_release.py 生成签名。"}
            self._log("警告: 更新清单未通过验签，但 allow_unsigned_update=true，继续")

        latest = str(manifest.get("version", "")).strip()
        return {"ok": True,
                "has_update": self._version_tuple(latest) > self._version_tuple(cur),
                "current": cur, "latest": latest.lstrip("vV"),
                "changelog": manifest.get("changelog", ""),
                "verified": verified, "manifest": manifest}

    def _safe_relpath(self, rel):
        """把清单里的相对路径限制在项目目录内，防目录穿越和链接逃逸。"""
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        if not rel or "\x00" in rel:
            return None
        base = os.path.realpath(os.path.abspath(self.base))
        p = os.path.realpath(os.path.abspath(os.path.join(base, rel)))
        try:
            if os.path.commonpath([base, p]) != base:
                return None
        except (ValueError, OSError):
            return None
        return p

    def download_and_install(self, manifest, progress_cb=None, confirm=True):
        """下载并安装更新包（manifest 必须验签通过）。

        流程：再验签 → 下载到 staging 并逐个校验 sha256 → 确认 → 备份 → 替换 → 记历史，
        任一文件失败则回滚已替换的文件。
        """
        import urllib.request
        from core import release_sign
        from core.version import get_version

        if not release_sign.verify_manifest(manifest,
                                            release_sign.load_release_pubkey(self.base)) \
                and not self._allow_unsigned_update():
            return {"ok": False, "错误": "更新包验签失败，已终止安装"}

        files = manifest.get("files") or []
        if not files:
            return {"ok": False, "错误": "更新包文件列表为空"}

        ver = str(manifest.get("version", "unknown"))
        stage = os.path.join(self.staging, "update_" + re.sub(r"[^\w.\-]", "_", ver))
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage, exist_ok=True)

        # ① 下载 + 逐文件校验 sha256
        total = len(files)
        for i, f in enumerate(files):
            rel, url = f.get("path", ""), f.get("url", "")
            if not rel or not url or self._safe_relpath(rel) is None:
                return {"ok": False, "错误": "更新包条目非法: %r" % (rel,)}
            if progress_cb:
                progress_cb(i, total, rel)
            try:
                from core.net_guard import get_net_guard
                d = get_net_guard(self.trunk).check(
                    url, module="auto_updater", purpose="update_download")
                if not d.get("allow"):
                    raise PermissionError(d.get("reason") or "网络请求被拒绝")
                req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
                data = urllib.request.urlopen(req, timeout=30).read()
            except Exception as e:
                return {"ok": False, "错误": "下载失败 %s: %s" % (rel, str(e)[:60])}
            if hashlib.sha256(data).hexdigest() != str(f.get("sha256", "")).lower():
                return {"ok": False, "错误": "文件校验失败(sha256 不符): " + rel}
            sp = os.path.join(stage, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            with open(sp, "wb") as fh:
                fh.write(data)
        if progress_cb:
            progress_cb(total, total, "下载完成")

        # ② 用户确认
        if confirm and not self.ask_confirm("将更新到 v%s，共 %d 个文件" % (ver, total)):
            return {"ok": False, "错误": "用户取消", "取消": True}

        # ③ 备份 + 替换（失败回滚）
        bk = self.backup_current()
        old_ver = get_version()
        replaced = []
        try:
            for f in files:
                rel = f["path"]
                sp = os.path.join(stage, rel.replace("/", os.sep))
                tp = self._safe_relpath(rel)
                os.makedirs(os.path.dirname(tp), exist_ok=True)
                if os.path.exists(tp):
                    keep = os.path.join(bk, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(keep), exist_ok=True)
                    shutil.copy2(tp, keep)
                shutil.copy2(sp, tp)
                replaced.append((tp, rel))
        except Exception as e:
            for tp, rel in replaced:
                keep = os.path.join(bk, rel.replace("/", os.sep))
                try:
                    if os.path.exists(keep):
                        shutil.copy2(keep, tp)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            return {"ok": False, "错误": "替换失败已回滚: " + str(e)[:60], "备份": bk}

        # ④ 记更新历史（对话框会读这个文件）
        try:
            hp = os.path.join(self.base, "updates", "update_history.jsonl")
            os.makedirs(os.path.dirname(hp), exist_ok=True)
            with open(hp, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "from": old_ver, "to": ver,
                    "files": len(replaced), "verified": True,
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

        # ⑤ 热重载受影响的模块
        self._reload_touched([rel for _, rel in replaced])
        shutil.rmtree(stage, ignore_errors=True)
        self._log("更新完成: v%s -> v%s (%d 个文件)" % (old_ver, ver, len(replaced)))
        return {"ok": True, "更新数": len(replaced), "备份": bk, "版本": ver}
