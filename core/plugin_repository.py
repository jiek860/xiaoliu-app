# -*- coding: utf-8 -*-
"""Remote plugin repository policy.

Remote plugin code is disabled by default. Enabling it requires an explicit
boolean opt-in *and* a host allowlist. Every URL must be HTTPS, and every
remote plugin must carry a valid manifest signature. Multiple repositories are
supported as ordered fallback sources; there is no unverified fallback.
"""
from __future__ import annotations

import os
import urllib.parse


def _candidate_urls(config):
    raw = config.get("plugin_repo_urls")
    if raw is None or raw == "":
        candidates = []
    elif isinstance(raw, str):
        candidates = [raw]
    elif isinstance(raw, (list, tuple)):
        candidates = [str(x or "").strip() for x in raw if str(x or "").strip()]
    else:
        candidates = []
    # Keep the legacy single-URL setting working as an additional source.
    legacy = str(config.get("online_repo_url") or "").strip()
    if legacy and legacy not in candidates:
        candidates.append(legacy)
    return candidates


def remote_repo_urls(config):
    """Return ``(ordered_urls, reason)``. Empty list means disabled."""
    config = config or {}
    if config.get("plugin_remote_install", False) is not True:
        return [], "远程插件下载默认关闭（plugin_remote_install=false）"
    candidates = _candidate_urls(config)
    if not candidates:
        return [], "未配置在线插件仓库地址"
    allowlist = config.get("plugin_repo_allowlist") or []
    hosts = {str(x).strip().lower() for x in allowlist if str(x).strip()}
    if not hosts:
        return [], "plugin_repo_allowlist 为空，远程插件下载拒绝启动"
    urls = []
    for raw in candidates:
        raw = str(raw or "").strip().rstrip("/")
        try:
            parsed = urllib.parse.urlparse(raw)
        except Exception:
            return [], "在线插件仓库地址无效: %s" % raw[:120]
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return [], "远程插件仓库必须是 HTTPS 且包含主机名: %s" % raw[:120]
        if parsed.username or parsed.password:
            return [], "远程插件仓库地址不得内嵌凭据"
        if parsed.hostname.lower() not in hosts:
            return [], "远程插件仓库主机不在 plugin_repo_allowlist 中: %s" % parsed.hostname
        if raw not in urls:
            urls.append(raw)
    return urls, ""


def remote_repo_policy(config):
    """Backward-compatible single-source view used by older callers."""
    urls, reason = remote_repo_urls(config)
    return (urls[0] if urls else None), reason


def safe_plugin_filename(filename):
    raw = str(filename or "")
    if (not raw or "/" in raw or "\\" in raw or ":" in raw
            or raw != os.path.basename(raw)):
        return None
    if not raw.endswith(".py"):
        return None
    return raw


def manifest_entry_signed(meta):
    return bool(isinstance(meta, dict) and str(meta.get("signature") or "").strip())


def download_url(base_url, filename):
    name = safe_plugin_filename(filename)
    if not name:
        raise ValueError("invalid plugin filename")
    return str(base_url).rstrip("/") + "/" + name


def download_urls(base_urls, filename):
    return [download_url(base, filename) for base in (base_urls or [])]
