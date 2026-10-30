# -*- coding: utf-8 -*-
"""PatchV2 协议（批次 46.2/46.3）：局部优先、唯一匹配、锚点、语法与最小性。

设计取舍
--------
* **不重造校验器**：路径越界、受保护目录、base_hash、hunk 唯一匹配都沿用
  ``core.patch_engine.validate_patch``，这里只补 v2 独有的规则；
* **已存在的文件禁止 ``write``**：``write`` 等于整文件覆盖，模型一旦把
  1400 行的文件写回 1200 行就会静默丢代码；v2 只允许 ``update + hunks``，
  ``write`` 仅用于新建；
* **行号锚点是"软校验"**：模型给的 ``line`` 与唯一命中位置差 3 行以内算
  通过，差得多只记 warning（不因锚点漂移丢掉一个本来正确的 hunk）；
* **最小性**：单文件改动 >200 行或跨 >5 文件直接拒绝，提示拆分；
* **风险分级**（L2 自动档用）：新建/新增测试=低，单函数小改=中，
  删改/重命名/配置依赖/跨 3 文件/大改=高，受保护路径=禁止；
* **三态开关** ``code.patch_v2``：off 完全走旧逻辑，shadow 只记录校验结果，
  on 才拒绝不合规 patch。默认 shadow，用户可见行为不变。
"""
from __future__ import annotations

import ast
import difflib
import json
import os
import time

from core.patch_engine import (PROTECTED_PARTS, PatchError, sha256_text,
                               validate_patch)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MAX_FILES = 5
MAX_DIFF_LINES = 200
MAX_CREATE_LINES = 400
ANCHOR_TOLERANCE = 3
EDIT_LOG = os.path.join("data", "code_edits.jsonl")

CONFIG_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "cargo.toml", "go.mod", "go.sum", "dockerfile", "makefile",
    "tox.ini", "pytest.ini", ".gitlab-ci.yml", "build_release.py",
}
CONFIG_DIRS = (".github/", ".gitlab/", ".circleci/", "requirements/")


def mode(trunk):
    """``code.patch_v2``：off / shadow / on，认不出按 shadow。"""
    try:
        value = str(trunk.rule("code.patch_v2", "shadow") or "shadow").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "patch v2 mode")
        return "shadow"
    return value if value in ("off", "shadow", "on") else "shadow"


def auto_apply_enabled(trunk):
    """``code_agent.auto_apply``：低风险改动是否自动应用，默认关。"""
    try:
        return bool(trunk.rule("code_agent.auto_apply", False))
    except Exception as e:
        _x6_swallowed(__name__, e, "auto apply switch")
        return False


def background_enabled(trunk):
    """``code_agent.background``：工作台任务是否走后台线程，默认关。"""
    try:
        return bool(trunk.rule("code_agent.background", False))
    except Exception as e:
        _x6_swallowed(__name__, e, "background switch")
        return False


def verify_mode(trunk):
    """``code.verify_select``：影响面选测，默认 off（关掉就是全量测试）。"""
    try:
        value = str(trunk.rule("code.verify_select", "off") or "off").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "verify switch")
        return "off"
    return value if value in ("off", "shadow", "on") else "off"


def locate_mode(trunk):
    """``code.locate_failures``：失败定位（file:line → 函数），默认 on（批次 D9）。

    和影响面选测拆开：定位只是给回修提示补一段"失败在哪个函数"，
    不改跑哪些测试，所以可以默认开；选测仍由 ``verify_mode`` 控制。
    """
    try:
        value = str(trunk.rule("code.locate_failures", "on") or "on").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "locate switch")
        return "on"
    return value if value in ("off", "shadow", "on") else "on"


def lint_extra_mode(trunk):
    """``code.lint_extra``：ruff/mypy 附加静态检查，默认 shadow（批次 D9）。

    shadow 只把输出记进结果、不参与 ``ok``（避免旧仓库被历史问题卡住）；
    on 才让类型错/风格错真正挡完成；off 完全不跑。
    """
    try:
        value = str(trunk.rule("code.lint_extra", "shadow") or "shadow").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "lint extra switch")
        return "shadow"
    return value if value in ("off", "shadow", "on") else "shadow"


def _rel(path):
    return str(path or "").replace("\\", "/").strip().lstrip("/")


def _full(root, rel):
    return os.path.join(str(root or "."), _rel(rel).replace("/", os.sep))


def _protected(rel):
    parts = [p for p in _rel(rel).split("/") if p not in ("", ".")]
    return any(p in PROTECTED_PARTS for p in parts) or ".." in parts


def _is_config(rel):
    low = _rel(rel).lower()
    name = os.path.basename(low)
    return name in CONFIG_NAMES or low.startswith(CONFIG_DIRS)


def changed_lines(patch):
    """估算改动行数：hunk 新旧行数之和；create/write 取内容行数。"""
    total = 0
    for fp in (patch or {}).get("files") or []:
        op = str(fp.get("op") or "update")
        if op in ("create", "write"):
            total += len(str(fp.get("content") or "").splitlines())
            continue
        if op != "update":
            continue
        for hunk in fp.get("hunks") or []:
            total += len(str(hunk.get("old") or "").splitlines())
            total += len(str(hunk.get("new") or "").splitlines())
    return total


def classify_patch(root, patch):
    """给 patch 定风险等级：low / medium / high / forbidden。

    L2 只自动应用 low / medium；high 交给审批；forbidden 直接拒绝
    （``validate_patch`` 也会挡受保护路径，这里再兜一层）。
    """
    files = []
    ops = set()
    for fp in (patch or {}).get("files") or []:
        rel = _rel(fp.get("path"))
        files.append(rel)
        ops.add(str(fp.get("op") or "update"))
    lines = changed_lines(patch)
    reasons = []
    if any(_protected(rel) for rel in files):
        return {"level": "forbidden", "reasons": ["受保护路径，禁止修改"],
                "files": files, "diff_lines": lines, "auto_apply": False}
    if ops & {"delete", "rename"}:
        reasons.append("删除/重命名文件")
    if any(_is_config(rel) for rel in files):
        reasons.append("修改配置/依赖/构建脚本")
    if len(files) >= 3:
        reasons.append("跨 %d 个文件" % len(files))
    if lines > 120:
        reasons.append("改动 %d 行" % lines)
    if reasons:
        level = "high"
    elif ops and ops <= {"create"}:
        level = "low"
        reasons.append("新建文件")
        if any(rel.startswith("tests/") or os.path.basename(rel).startswith("test_")
               for rel in files):
            reasons.append("新增测试")
    elif lines <= 40 and len(files) <= 2:
        level = "medium"
        reasons.append("局部修改 %d 行" % lines)
    else:
        level = "high"
        reasons.append("改动范围偏大")
    return {"level": level, "reasons": reasons, "files": files,
            "diff_lines": lines, "auto_apply": level in ("low", "medium")}


def _anchor_warning(root, fp, rel):
    """模型给了 ``line`` 时校验锚点；偏移过大只记 warning。"""
    text = ""
    try:
        with open(_full(root, rel), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    warnings = []
    for i, hunk in enumerate(fp.get("hunks") or []):
        try:
            anchor = int(hunk.get("line") or 0)
        except (TypeError, ValueError):
            anchor = 0
        if anchor <= 0:
            continue
        old = str(hunk.get("old") or "")
        if not old:
            continue
        idx = text.find(old)
        if idx < 0:
            continue
        actual = text[:idx].count("\n") + 1
        if abs(actual - anchor) > ANCHOR_TOLERANCE:
            warnings.append("%s#%d 行号锚点 %d 与实际 %d 相差较大"
                            % (rel, i, anchor, actual))
    return warnings


def _protocol_errors(root, patch):
    errors, warnings = [], []
    files = patch.get("files") or []
    if len(files) > MAX_FILES:
        errors.append("一次最多改 %d 个文件，当前 %d 个，请拆分"
                      % (MAX_FILES, len(files)))
    total = changed_lines(patch)
    if total > MAX_DIFF_LINES:
        errors.append("单次改动 %d 行超过 %d 行上限，请拆分为小步"
                      % (total, MAX_DIFF_LINES))
    for fp in files:
        rel = _rel(fp.get("path"))
        op = str(fp.get("op") or "update")
        if op == "write":
            if os.path.isfile(_full(root, rel)):
                errors.append("已存在文件禁止 write（会导致整文件覆盖）：%s，"
                              "请改用 update + hunks" % rel)
        if op in ("create", "write"):
            lines = len(str(fp.get("content") or "").splitlines())
            if lines > MAX_CREATE_LINES:
                warnings.append("%s 新建 %d 行，注意是否只是生成物" % (rel, lines))
            continue
        if op == "update":
            for i, hunk in enumerate(fp.get("hunks") or []):
                if not str(hunk.get("old") or "").strip():
                    errors.append("%s#%d hunk.old 为空" % (rel, i))
            warnings.extend(_anchor_warning(root, fp, rel))
    return errors, warnings


def _render(root, patch):
    """在内存里按顺序模拟应用，返回 {rel: 新内容}（delete 为 None）。"""
    virtual = {}

    def current(rel):
        if rel in virtual:
            return virtual[rel]
        try:
            with open(_full(root, rel), encoding="utf-8", errors="strict") as f:
                return f.read()
        except (OSError, ValueError):
            return None

    for fp in patch.get("files") or []:
        rel = _rel(fp.get("path"))
        op = str(fp.get("op") or "update")
        if op in ("create", "write"):
            virtual[rel] = str(fp.get("content") or "")
        elif op == "delete":
            virtual[rel] = None
        elif op == "rename":
            virtual[_rel(fp.get("new_path"))] = current(rel)
            virtual[rel] = None
        else:
            text = current(rel) or ""
            for hunk in fp.get("hunks") or []:
                old = str(hunk.get("old") or "")
                new = str(hunk.get("new") or "")
                if old and text.count(old) == 1:
                    text = text.replace(old, new, 1)
                else:
                    virtual[rel + "#unresolved"] = text
            virtual[rel] = text
    return virtual


def compile_check(root, patch):
    """Python/JSON 语法检查：改完解析不了就不该落盘。"""
    errors, warnings = [], []
    try:
        rendered = _render(root, patch)
    except Exception as e:  # 静默是故意的 - 渲染失败只记录，不误判语法
        _x6_swallowed(__name__, e, "render patch")
        return {"ok": True, "errors": [], "warnings": ["无法预演，跳过语法检查"]}
    for rel, text in rendered.items():
        if rel.endswith("#unresolved"):
            warnings.append("%s 有 hunk 未能在内存中精确定位，语法检查跳过"
                            % rel.split("#")[0])
            continue
        if text is None:
            continue
        low = rel.lower()
        if low.endswith(".py"):
            try:
                ast.parse(text)
            except SyntaxError as e:
                errors.append("%s: Python 语法错误 L%s: %s"
                              % (rel, e.lineno, e.msg))
        elif low.endswith(".json"):
            try:
                json.loads(text or "null")
            except ValueError as e:
                errors.append("%s: JSON 解析失败: %s" % (rel, str(e)[:120]))
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _merge_anchors(normalized, raw):
    """把模型给的 ``line`` 锚点补回规范化 patch（validate_patch 会丢弃它）。"""
    raw_files = (raw or {}).get("files") or []
    for i, fp in enumerate(normalized.get("files") or []):
        raw_fp = raw_files[i] if i < len(raw_files) else {}
        raw_hunks = raw_fp.get("hunks") if isinstance(raw_fp, dict) else None
        raw_hunks = raw_hunks if isinstance(raw_hunks, list) else []
        for j, hunk in enumerate(fp.get("hunks") or []):
            raw_hunk = raw_hunks[j] if j < len(raw_hunks) else {}
            if isinstance(raw_hunk, dict) and raw_hunk.get("line"):
                hunk["line"] = raw_hunk.get("line")
    return normalized


def review(root, patch, trunk=None):
    """完整审查：旧校验 + v2 规则 + 语法 + 风险分级。

    返回 ``{ok, errors, warnings, normalized, risk, mode}``；
    ``validate_patch`` 抛出的 ``PatchError`` 原样向上传播（旧行为不变）。
    """
    normalized = _merge_anchors(validate_patch(root, patch), patch)
    errors, warnings = _protocol_errors(root, normalized)
    checked = compile_check(root, normalized)
    errors.extend(checked.get("errors") or [])
    warnings.extend(checked.get("warnings") or [])
    risk = classify_patch(root, normalized)
    if risk["level"] == "forbidden":
        errors.append("受保护路径，禁止修改：" + ", ".join(risk["files"]))
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "normalized": normalized, "risk": risk, "mode": mode(trunk)}


def function_span(code, line_no):
    """找包含指定行的最内层函数/类，返回 1 基的 ``start/end/name``。"""
    try:
        tree = ast.parse(str(code or ""))
    except (SyntaxError, ValueError):
        return None
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        start = int(getattr(node, "lineno", 1) or 1)
        for deco in getattr(node, "decorator_list", []) or []:
            start = min(start, int(getattr(deco, "lineno", start) or start))
        end = int(getattr(node, "end_lineno", start) or start)
        try:
            line_no = int(line_no)
        except (TypeError, ValueError):
            return None
        if not start <= line_no <= end:
            continue
        if best is None or start >= best["start"]:
            best = {"start": start, "end": end, "name": str(node.name)}
    return best


def minimal_hunks(old, new, context=3):
    """把"整文件新内容"压成最少行级 hunk，供内联编辑局部替换。"""
    a = str(old or "").splitlines(True)
    b = str(new or "").splitlines(True)
    out = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for group in matcher.get_grouped_opcodes(context):
        i1, i2 = group[0][1], group[-1][2]
        j1, j2 = group[0][3], group[-1][4]
        old_text = "".join(a[i1:i2])
        new_text = "".join(b[j1:j2])
        if old_text == new_text:
            continue
        out.append({"old": old_text, "new": new_text, "start_line": i1 + 1})
    return out


def record_edit(root, entry):
    """内联编辑审计：谁、哪个任务、哪个文件、前后哈希、结果。"""
    row = dict(entry or {})
    row.setdefault("time", time.time())
    try:
        folder = os.path.join(os.path.abspath(root or "."), "data")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, os.path.basename(EDIT_LOG))
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return path
    except OSError as e:
        _x6_swallowed(__name__, e, "record code edit")
        return ""


def text_hash(text):
    return sha256_text(str(text or ""))
