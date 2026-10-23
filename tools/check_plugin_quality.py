# -*- coding: utf-8 -*-
"""插件质量门禁（Module-Level Program Standard 第十节落地版）。

把"标准"从文档变成可执行检查。分三级：

  error   违规即失败（发布门禁）
  warn    不符合应然要求，但不阻塞（生成报告）
  info    仅统计

用法：
    py -3 tools/check_plugin_quality.py            # 只报 error 是否通过
    py -3 tools/check_plugin_quality.py --strict   # warn 也算失败
    py -3 tools/check_plugin_quality.py --json     # 机器可读
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.plugin_api import (  # noqa: E402
    PLUGIN_API_VERSION, SUPPORTED_PLUGIN_API, validate_plugin_source,
)
from core.plugin_capabilities import CAPABILITY_KEYS  # noqa: E402
from core.tool_contract import validate_tools  # noqa: E402

MANIFEST = os.path.join(BASE, "modules_repo", "manifest.json")
SRC_DIR = os.path.join(BASE, "modules_repo")

# v2.1 S1：18 项原有必填 + 3 项新增必填（license/author/min_host_version）
# + 2 项自动推导（plugin_tier/risk_level）
REQUIRED_FIELDS = ("name", "title", "file", "cls", "desc", "group",
                   "version", "api_version", "first_party", "sha256",
                   "signature", "capabilities",
                   "license", "author", "min_host_version",
                   "plugin_tier", "risk_level")

# 隐式全局状态检查（标准 3.4）：命中即 warn
_GLOBAL_PATTERNS = (
    (re.compile(r"\bos\.environ\b"), "直接读环境变量（应走配置系统）"),
    (re.compile(r"^\s*global\s+\w+", re.M), "使用 global 声明"),
    (re.compile(r"\bos\.getcwd\(\)"), "依赖当前工作目录"),
    (re.compile(r"^[A-Z_]+\s*=\s*(\{|\[)", re.M), "模块级可变全局容器"),
)

# 硬编码密钥检查（标准 5.3）
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[\"'][^\"']{8,}[\"']"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _load_manifest():
    with open(MANIFEST, encoding="utf-8-sig") as f:
        return json.load(f)


def _read_src(meta):
    path = os.path.join(SRC_DIR, meta.get("file") or "")
    if not os.path.isfile(path):
        return None, path
    try:
        return open(path, encoding="utf-8", errors="replace").read(), path
    except OSError:
        return None, path


def _tools_of_source(src):
    """从源码里取出 TOOLS 声明（只做字面量求值，不执行模块）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not (isinstance(item, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == "TOOLS"
                        for t in item.targets)):
                continue
            try:
                value = ast.literal_eval(item.value)
            except (ValueError, SyntaxError):
                return []
            return value if isinstance(value, list) else []
    return []


def _inherited_methods(tree):
    """顺着本文件里出现的基类名，去 core/ 与 modules/ 找它的方法集合。

    只做**一层静态查找**（够覆盖 AgentGeneric 这类薄基类），
    找不到就返回空集合 —— 宁可少算，也不要猜错。
    """
    base_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for b in node.bases:
                if isinstance(b, ast.Name):
                    base_names.add(b.id)
                elif isinstance(b, ast.Attribute):
                    base_names.add(b.attr)
    found = set()
    if not base_names:
        return found
    search_dirs = (os.path.join(BASE, "core"), os.path.join(BASE, "modules"),
                   os.path.join(BASE, "modules", "installed"))
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".py"):
                continue
            try:
                sub = ast.parse(open(os.path.join(d, fn), encoding="utf-8",
                                     errors="replace").read())
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(sub):
                if isinstance(node, ast.ClassDef) and node.name in base_names:
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef,
                                             ast.AsyncFunctionDef)):
                            found.add(item.name)
    return found


def check_module(meta):
    """检查单个模块，返回 {errors, warnings, info}。"""
    errors, warnings, info = [], [], {}
    name = str(meta.get("name") or "?")

    # --- 标准 9.1 / 9.2 清单必填字段 ---
    for key in REQUIRED_FIELDS:
        if key not in meta:
            errors.append("%s: 清单缺字段 %s（标准 9.2）" % (name, key))

    # --- 标准 1.7 / 9.1 版本 ---
    ver = str(meta.get("api_version") or "")
    if ver not in SUPPORTED_PLUGIN_API:
        errors.append("%s: api_version=%r 不在支持列表 %s（标准 1.7）"
                      % (name, ver, sorted(SUPPORTED_PLUGIN_API)))
    if not re.match(r"^\d+(\.\d+){1,2}$", str(meta.get("version") or "")):
        warnings.append("%s: version=%r 不是语义化版本（标准 9.1）"
                        % (name, meta.get("version")))

    # --- 标准 5.5 / 能力声明 ---
    caps = meta.get("capabilities")
    if not isinstance(caps, dict):
        errors.append("%s: 缺少 capabilities（标准 5.5）" % name)
    else:
        for key in CAPABILITY_KEYS:
            if key not in caps:
                errors.append("%s: capabilities 缺 %s 段（标准 5.5）" % (name, key))

    # --- v2.1 §0.3 / A.4 分级与风险推导一致性 ---
    try:
        from core.plugin_tier import check_manifest as _check_tier
        tr = _check_tier(meta)
        if tr["mismatches"]:
            for mm in tr["mismatches"]:
                errors.append("%s: %s 声明值 %r 与推导值 %r 不一致（v2.1 A.4）"
                              % (name, mm["field"], mm["declared"],
                                 mm["derived"]))
        info["plugin_tier"] = tr["tier"]
        info["risk_level"] = tr["risk"]
    except Exception as e:
        warnings.append("%s: 分级推导失败 %s" % (name, str(e)[:60]))

    # --- v2.1 S1 语义化版本 ---
    if not re.match(r"^\d+\.\d+\.\d+(?:[-+].*)?$",
                    str(meta.get("version") or "")):
        warnings.append("%s: version=%r 不是三段式语义化版本（N9.1）"
                        % (name, meta.get("version")))

    # --- 标准 9.2 签名 ---
    # signature / sha256 由 check_repo_sync.py 和 verify_signature.py 单独把关；
    # quality 检查只看模块源码质量，避免 CI 无签名私钥时被误判。
    src, path = _read_src(meta)
    if src is None:
        errors.append("%s: 源码文件不存在 %s" % (name, path))
        return {"name": name, "errors": errors, "warnings": warnings,
                "info": info}

    # --- 标准 2.4 / 3.2 依赖边界 ---
    dep = validate_plugin_source(src, strict=not meta.get("first_party"),
                                 first_party=bool(meta.get("first_party")))
    for e in dep.get("errors") or []:
        errors.append("%s: %s（标准 2.4）" % (name, e))
    for w in dep.get("warnings") or []:
        warnings.append("%s: %s" % (name, w))

    # --- 标准 5.3 硬编码密钥 ---
    for rx in _SECRET_PATTERNS:
        if rx.search(src):
            errors.append("%s: 疑似硬编码密钥（标准 5.3）" % name)
            break

    # --- 标准 3.4 隐式全局状态 ---
    for rx, why in _GLOBAL_PATTERNS:
        if rx.search(src):
            warnings.append("%s: %s（标准 3.4）" % (name, why))

    # --- 标准 6.5 不得吞异常 ---
    try:
        tree = ast.parse(src)
        swallow, waived = 0, 0
        src_lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = node.body or []
            is_swallow = (len(body) == 1 and isinstance(body[0], ast.Pass)) or (
                len(body) == 1 and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and body[0].value.value is Ellipsis)
            if not is_swallow:
                continue
            # 允许项目已约定的"静默是故意的"显式豁免（行尾或上一行注释）
            lineno = body[0].lineno
            ctx = "".join(src_lines[max(0, lineno - 3):lineno])
            if "静默是故意的" in ctx or "nosec" in ctx:
                waived += 1
            else:
                swallow += 1
        if swallow:
            errors.append("%s: %d 处 except 直接 pass 且未标注理由（标准 6.5）"
                          % (name, swallow))
        info["except_pass"] = swallow
        info["except_pass_waived"] = waived
    except SyntaxError as e:
        errors.append("%s: 语法错误 %s" % (name, str(e)[:80]))

    # --- 标准 4.1 / 4.2 生命周期 ---
    try:
        tree = ast.parse(src)
        methods = {n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        # 入口/清理方法可能来自父类（例如三个 agent 继承 AgentGeneric）。
        # 只看本文件会误报，所以顺着基类名再去 core/modules 里找一次。
        inherited = _inherited_methods(tree)
        methods |= inherited
        info["has_run"] = "run" in methods
        info["has_stop"] = bool(methods & {"stop", "close", "shutdown",
                                           "cleanup", " _on_stop".strip()})
        if not info["has_run"]:
            errors.append("%s: 缺入口 run()（标准 1.2）" % name)
                # 标准 4.2：只有持有资源的模块才要求 stop()/close()
        _RESOURCE_PATTERNS = (
            re.compile(r"\bthreading\.(Thread|Timer)\b"),
            re.compile(r"\bsocket\."),
            re.compile(r"\bsubprocess\."),
            re.compile(r"\bsqlite3\.connect\b"),
            re.compile(r"\bHTTPServer\b"),
        )
        has_resources = any(rx.search(src) for rx in _RESOURCE_PATTERNS)
        if not info["has_stop"] and has_resources:
            warnings.append("%s: 有资源但未声明 stop()/close()（标准 4.2）" % name)
    except SyntaxError:
        pass

    # --- 标准 1.1 职责与边界 ---
    doc = ""
    try:
        doc = (ast.get_docstring(ast.parse(src)) or "").strip()
    except SyntaxError:
        doc = ""
    if not doc:
        warnings.append("%s: 模块缺 docstring，无法声明职责（标准 1.1）" % name)
    if not re.search(r"不负责|不属于|out of scope|not responsible", src):
        warnings.append("%s: 未声明'不负责的事项'（标准 1.1）" % name)

    # --- 标准 1.3 工具契约 ---
    tools = _tools_of_source(src)
    info["tools"] = len(tools)
    if tools:
        tc = validate_tools(tools, module=name)
        info["tools_without_contract"] = tc.get("missing_contract", 0)
        for e in tc.get("errors") or []:
            errors.append("%s: %s（标准 1.3）" % (name, e))
        if tc.get("missing_contract"):
            warnings.append("%s: %d/%d 个工具未声明 contract（标准 1.3）"
                            % (name, tc["missing_contract"], tc.get("total", 0)))

    # --- 标准 10：旧式中文错误文本 ---
    legacy_err = len(re.findall(r'return\s*\{\s*"错误"', src))
    info["legacy_error_returns"] = legacy_err
    if legacy_err:
        warnings.append("%s: %d 处返回 {'错误': ...}，建议改用 "
                        "core.plugin_errors（标准 6.1）" % (name, legacy_err))
    return {"name": name, "errors": errors, "warnings": warnings,
            "info": info}


def check_all():
    manifest = _load_manifest()
    results = [check_module(m) for m in manifest]
    errors = sum(len(r["errors"]) for r in results)
    warnings = sum(len(r["warnings"]) for r in results)

    # 警告基线棘轮：老模块不许超基线，新模块必须 0 警告
    baseline_path = os.path.join(BASE, "tools", "plugin_quality_baseline.json")
    if os.path.isfile(baseline_path):
        try:
            with open(baseline_path, encoding="utf-8") as f:
                baseline = json.load(f)
            bl_modules = baseline.get("modules", {})
            for r in results:
                name = r["name"]
                if name not in bl_modules:
                    continue
                bl = bl_modules[name]
                cur_w = len(r["warnings"])
                bl_w = bl.get("warn_baseline", 0)
                if bl.get("strict") and cur_w > 0:
                    r["errors"].append("%s: 严格模块有 %d 条警告（基线 0，必须为 0）" % (name, cur_w))
                elif cur_w > bl_w:
                    r["errors"].append("%s: 警告数 %d 超过基线 %d（棘轮只许降不许升）" % (name, cur_w, bl_w))
            errors = sum(len(r["errors"]) for r in results)
            warnings = sum(len(r["warnings"]) for r in results)
        except Exception:
            pass  # 静默是故意的：基线文件可能不存在或格式错误，不影响检查
    return {
        "schema_version": "1.0",
        "plugin_api_version": PLUGIN_API_VERSION,
        "modules": len(results),
        "errors": errors,
        "warnings": warnings,
        "ok": errors == 0,
        "results": results,
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    strict = "--strict" in argv
    report = check_all()
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("插件质量门禁（Module-Level Standard 第十节）")
        print("=" * 70)
        print("模块 %d · error %d · warn %d"
              % (report["modules"], report["errors"], report["warnings"]))
        for r in report["results"]:
            for e in r["errors"]:
                print("  [E] " + e)
            for w in r["warnings"]:
                print("  [W] " + w)
        print()
        if report["ok"] and not strict:
            print("[OK] 质量门禁通过（error=0）")
        elif report["ok"] and strict and report["warnings"] == 0:
            print("[OK] 严格模式通过（error=0, warn=0）")
        else:
            print("[X] 质量门禁未通过")
    if not report["ok"]:
        return 1
    if strict and report["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
