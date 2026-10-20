# -*- coding: utf-8 -*-
"""Remote plugin repository must be HTTPS, allowlisted and signed."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.plugin_repository import (  # noqa: E402
    download_url, download_urls, manifest_entry_signed, remote_repo_policy,
    remote_repo_urls, safe_plugin_filename,
)


def _cfg(**extra):
    data = {
        "plugin_remote_install": True,
        "online_repo_url": "https://plugins.example.com/repo",
        "plugin_repo_allowlist": ["plugins.example.com"],
    }
    data.update(extra)
    return data


def test_remote_plugin_disabled_by_default():
    url, why = remote_repo_policy({"online_repo_url": "https://gitee.com/x/y"})
    assert url is None
    assert "默认关闭" in why


def test_remote_plugin_requires_https_and_allowlist():
    assert remote_repo_policy(_cfg())[0] == "https://plugins.example.com/repo"
    assert remote_repo_policy(_cfg(online_repo_url="http://plugins.example.com/repo"))[0] is None
    assert remote_repo_policy(_cfg(plugin_repo_allowlist=["other.example"]))[0] is None
    assert remote_repo_policy(_cfg(online_repo_url="https://u:p@plugins.example.com/repo"))[0] is None


def test_remote_plugin_signature_required():
    assert manifest_entry_signed({"signature": "abc"}) is True
    assert manifest_entry_signed({"signature": ""}) is False
    assert manifest_entry_signed({}) is False


def test_filename_and_download_url_are_single_level_py():
    assert safe_plugin_filename("notes.py") == "notes.py"
    assert safe_plugin_filename("../notes.py") is None
    assert safe_plugin_filename("notes.txt") is None
    assert download_url("https://plugins.example.com/repo/", "notes.py") == \
        "https://plugins.example.com/repo/notes.py"


def test_multiple_repositories_keep_order():
    cfg = _cfg(online_repo_url="", plugin_repo_urls=[
        "https://gitee.com/cloud-drift/liuyun/raw/master",
        "https://raw.githubusercontent.com/jiek860/xiaoliu-app/main/modules_repo",
    ], plugin_repo_allowlist=["gitee.com", "raw.githubusercontent.com"])
    urls, why = remote_repo_urls(cfg)
    assert why == ""
    assert urls == [
        "https://gitee.com/cloud-drift/liuyun/raw/master",
        "https://raw.githubusercontent.com/jiek860/xiaoliu-app/main/modules_repo",
    ]
    assert download_urls(urls, "notes.py")[1].endswith("/modules_repo/notes.py")


def test_multiple_repositories_fail_closed_if_any_url_is_unsafe():
    cfg = _cfg(online_repo_url="", plugin_repo_urls=[
        "https://gitee.com/cloud-drift/liuyun/raw/master",
        "http://raw.githubusercontent.com/jiek860/xiaoliu-app/main/modules_repo",
    ], plugin_repo_allowlist=["gitee.com", "raw.githubusercontent.com"])
    urls, why = remote_repo_urls(cfg)
    assert urls == []
    assert "HTTPS" in why
