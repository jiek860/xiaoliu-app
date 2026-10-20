# -*- coding: utf-8 -*-
"""插件公共 API 版本与依赖边界测试。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.plugin_api import (  # noqa: E402
    PLUGIN_API_VERSION, manifest_api_version, validate_plugin_manifest,
    validate_plugin_source,
)


def test_public_plugin_api_accepts_public_imports():
    src = """
from modules.base import BaseModule
from core.safe import safe
from core.path_safety import safe_join

class Demo(BaseModule):
    pass
"""
    r = validate_plugin_source(src, strict=True)
    assert r["ok"] is True
    assert r["api_version"] == PLUGIN_API_VERSION


def test_plugin_private_core_import_rejected():
    for src in (
        "from core.trunk import Trunk\n",
        "from core.safe import _private\n",
        "import core._deprecated.registry\n",
        "from core.data_migrations import migrate_all\n",
    ):
        r = validate_plugin_source(src, strict=True)
        assert r["ok"] is False, src
        assert r["errors"]


def test_internal_module_allowed_only_non_strict():
    src = "from core.auto_update_patch import AutoUpdatePatchMixin\n"
    assert validate_plugin_source(src, strict=False)["ok"] is True
    assert validate_plugin_source(src, strict=True)["ok"] is False


def test_manifest_api_version():
    assert manifest_api_version({"api_version": "1.0"})["ok"] is True
    assert manifest_api_version({})["legacy"] is True
    assert manifest_api_version({"api_version": "9.9"})["ok"] is False


def test_from_core_import_is_resolved_to_real_module():
    assert validate_plugin_source(
        "from core import trunk\n", strict=True)["ok"] is False
    assert validate_plugin_source(
        "from core import safe\n", strict=True)["ok"] is True


def test_star_import_rejected():
    r = validate_plugin_source("from core import *\n", strict=True)
    assert r["ok"] is False
    assert any("星号" in e for e in r["errors"])


def test_manifest_validation_combines_version_and_source_rules():
    good = validate_plugin_manifest(
        {"api_version": "1.0"},
        "from core.safe import safe\n")
    assert good["ok"] is True

    bad_api = validate_plugin_manifest(
        {"api_version": "9.9"}, "from core.safe import safe\n")
    assert bad_api["ok"] is False

    third_party_private = validate_plugin_manifest(
        {"api_version": "1.0"},
        "from core.auto_update_patch import Patch\n")
    assert third_party_private["ok"] is False

    # 官方随包模块允许审计过的集成层，但 core.trunk 仍然永远禁止。
    first_party = validate_plugin_manifest(
        {"api_version": "1.0", "first_party": True},
        "from core.auto_update_patch import Patch\n")
    assert first_party["ok"] is True
    assert validate_plugin_manifest(
        {"api_version": "1.0", "first_party": True},
        "from core.trunk import Trunk\n")["ok"] is False


def test_manifest_entries_declare_plugin_api():
    import json
    path = os.path.join(BASE, "modules_repo", "manifest.json")
    if not os.path.exists(path):
        return
    manifest = json.load(open(path, encoding="utf-8-sig"))
    assert manifest
    assert all(m.get("api_version") == PLUGIN_API_VERSION for m in manifest)
    assert all(m.get("first_party") is True for m in manifest)


def test_plugin_market_payload_gate_blocks_private_core():
    from modules.installed.plugin_market import PluginMarket

    class Fake:
        trunk = None

    ok, why = PluginMarket._validate_plugin_payload(
        Fake(), b"from core.trunk import Trunk\n", {"api_version": "1.0"})
    assert ok is False
    assert "私有" in why or "API" in why


def test_base_module_exposes_same_api_version():
    from modules.base import BaseModule
    assert BaseModule.PLUGIN_API_VERSION == PLUGIN_API_VERSION
