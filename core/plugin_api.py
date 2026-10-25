# -*- coding: utf-8 -*-
"""插件公共 API 版本与依赖边界检查。

插件 API 版本
-------------
* 当前版本：``PLUGIN_API_VERSION = "1.0"``。
* 清单（modules_repo/manifest.json）的每个条目必须写 ``api_version``。
* 用户端只接受 ``SUPPORTED_PLUGIN_API`` 里的版本；旧清单缺字段时按
  legacy 兼容模式给出 warning，方便旧仓库平滑升级，但新发布必须写。

依赖边界
--------
第三方插件只能依赖 ``PUBLIC_CORE_MODULES`` 里的公共模块；``core.trunk``、
``core.data_schema``、``core.data_migrations``、``core.secret_store`` 等
内部实现永远禁止。官方随包模块（清单 ``first_party: true``）可以依赖
少量审计过的 core 集成模块，但私有/门面实现同样拒绝。

本模块同时提供 AST 静态检查，不执行插件代码；插件市场安装/下载前先调用。
"""
from __future__ import annotations

import ast
import os

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from core.plugin_capabilities import capability_summary, validate_capabilities

PLUGIN_API_VERSION = "1.0"
SUPPORTED_PLUGIN_API = {"1.0"}

# 第三方插件允许依赖的 core 公共模块；不在列表中视为内部实现。
PUBLIC_CORE_MODULES = {
    "core.safe",
    "core.error_text",
    "core.path_safety",
    "core.tool_schema",
    "core.document_parser",
    "core.net_guard",
    "core.permission_center",
    "core.audit_log",
    "core.security_policy",
    "core.screen_geometry",
    "core.sandbox",
    "core.agent_generic",
    "core.diagnostics",
    "core.retrieval",
    "core.fts_index",
    "core.realtime",
    "core.realtime.tts",
    "core.realtime.audio_devices",
    # 插件 SDK 自身：版本常量、登记表读取和签名校验。
    "core.plugin_api",
    "core.lazy_config",
    "core.plugin_signer",
}

# 永远禁止第三方插件依赖的私有/门面实现。
FORBIDDEN_CORE_PREFIXES = (
    "core._deprecated",
    "core.trunk",
    "core.trunk_",
    "core.data_schema",
    "core.data_migrations",
    "core.secret_store",
    "core.default_secrets",
    "core.release_sign",
    "core.license_",
    "core.auth",
    "core.pipeline",
    "core.permission_center._",
)

# 官方随包模块依赖的集成层；不开放给第三方，但 first_party 可以用。
_FIRST_PARTY_INTEGRATION = (
    "core.auto_update",
    "core.computer_",
    "core.personality_",
    "core.mcp_stdio",
)


def _module_of(node):
    if isinstance(node, ast.ImportFrom) and node.module:
        return node.module
    return ""


def _is_forbidden(module):
    return any(module == p or module.startswith(p)
               for p in FORBIDDEN_CORE_PREFIXES)


def _resolve_from_import(node):
    """把 ``from core import trunk`` 也解析成 ``core.trunk``。"""
    mod = node.module or ""
    names = list(getattr(node, "names", []) or [])
    if mod == "core":
        return ["core." + a.name for a in names if a.name != "*"]
    return [mod] if mod else []


def validate_plugin_source(source, *, strict=False, first_party=False):
    """检查插件源码依赖。

    返回 {ok, errors, warnings, api_version, strict, first_party}。
    * strict=True：第三方插件只能使用 PUBLIC_CORE_MODULES；
    * first_party=True：允许官方集成层，但仍禁止 FORBIDDEN_CORE_PREFIXES；
    * 私有符号（下划线开头）永远禁止从 core 导入。
    """
    errors, warnings = [], []
    try:
        tree = ast.parse(str(source or ""))
    except SyntaxError as e:
        return {"ok": False, "api_version": PLUGIN_API_VERSION,
                "strict": bool(strict), "first_party": bool(first_party),
                "errors": ["语法错误: %s" % str(e)[:200]], "warnings": []}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(a.name == "*" for a in node.names):
                errors.append("禁止从 core 使用星号导入: %s" % (node.module or "core"))
            modules = _resolve_from_import(node)
            for mod in modules:
                if not mod.startswith("core"):
                    continue
                if _is_forbidden(mod):
                    errors.append("禁止导入私有/内部模块: " + mod)
                    continue
                if strict and not first_party and mod not in PUBLIC_CORE_MODULES:
                    errors.append("第三方插件只能使用公共 API 模块: " + mod)
                elif (not first_party and not strict
                      and mod not in PUBLIC_CORE_MODULES
                      and any(mod.startswith(p)
                              for p in _FIRST_PARTY_INTEGRATION)):
                    warnings.append("插件依赖内部集成模块: " + mod)
            for alias in node.names:
                if alias.name.startswith("_") and alias.name != "_x6_swallowed":
                    where = node.module or "core"
                    errors.append("禁止导入 core 私有符号: %s.%s"
                                  % (where, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if not mod.startswith("core"):
                    continue
                if _is_forbidden(mod):
                    errors.append("禁止导入私有/内部模块: " + mod)
                elif strict and not first_party and mod not in PUBLIC_CORE_MODULES:
                    errors.append("第三方插件只能使用公共 API 模块: " + mod)
        elif isinstance(node, ast.Attribute):
            # 捕获 core.trunk.xxx 之类的属性访问。
            try:
                val = node.value
                parts = []
                while isinstance(val, ast.Attribute):
                    parts.append(val.attr)
                    val = val.value
                if isinstance(val, ast.Name) and val.id == "core":
                    mod = "core." + ".".join(reversed(parts))
                    if _is_forbidden(mod):
                        if strict:
                            errors.append("第三方插件不能访问内部实现: " + mod)
                        else:
                            warnings.append("插件访问内部实现: " + mod)
            # 静默是故意的：AST 属性链畸形时跳过该节点，顶层仍返回结构化结果
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")
    return {"ok": not errors, "api_version": PLUGIN_API_VERSION,
            "strict": bool(strict), "first_party": bool(first_party),
            "errors": errors[:20], "warnings": warnings[:20]}


def validate_plugin_file(path, *, strict=False, first_party=False):
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return {"ok": False, "api_version": PLUGIN_API_VERSION,
                "strict": bool(strict), "first_party": bool(first_party),
                "errors": [str(e)[:200]], "warnings": []}
    return validate_plugin_source(src, strict=strict, first_party=first_party)


def manifest_api_version(meta):
    v = (meta or {}).get("api_version")
    if not v:
        return {"ok": True, "api_version": "", "legacy": True,
                "errors": [], "warnings": ["旧清单没有 api_version，按兼容模式处理"]}
    if str(v) not in SUPPORTED_PLUGIN_API:
        return {"ok": False, "api_version": str(v), "legacy": False,
                "errors": ["不支持的插件 API 版本: " + str(v)], "warnings": []}
    return {"ok": True, "api_version": str(v), "legacy": False,
            "errors": [], "warnings": []}


def is_first_party(meta):
    """清单显式标记 first_party 的才是官方随包模块。"""
    return bool((meta or {}).get("first_party"))


def validate_plugin_manifest(meta, source=None, *, strict=None,
                             first_party=None):
    """同时校验清单版本和源码依赖，供安装/下载入口使用。"""
    meta = meta or {}
    if first_party is None:
        first_party = is_first_party(meta)
    if strict is None:
        strict = not first_party
    mv = manifest_api_version(meta)
    cap = validate_capabilities(
        meta, plugin_name=meta.get("name") or meta.get("file"))
    errors = list(mv.get("errors") or []) + list(cap.get("errors") or [])
    warnings = list(mv.get("warnings") or []) + list(cap.get("warnings") or [])
    source_result = None
    if source is not None:
        source_result = validate_plugin_source(
            source, strict=strict, first_party=first_party)
        errors.extend(source_result.get("errors") or [])
        warnings.extend(source_result.get("warnings") or [])
    return {"ok": not errors,
            "api_version": mv.get("api_version") or PLUGIN_API_VERSION,
            "legacy": bool(mv.get("legacy") or cap.get("legacy")),
            "strict": bool(strict), "first_party": bool(first_party),
            "errors": errors[:30], "warnings": warnings[:30],
            "source": source_result,
            "capabilities": cap.get("capabilities"),
            "capability_schema_version": cap.get("schema_version"),
            "capability_legacy": bool(cap.get("legacy")),
            "risk_level": cap.get("risk_level"),
            "risk_reasons": cap.get("risk_reasons"),
            "capability_summary": capability_summary(cap)}
