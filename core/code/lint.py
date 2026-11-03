# -*- coding: utf-8 -*-
"""编辑器静态检查的纯逻辑（第 8 批 B5 + 深度⑧⑨）。

为什么从 `gui/code_editor_widget.py` 搬出来
------------------------------------------
那个文件已经贴着 600 行上限，而这一批要加"LSP 诊断优先 / 实时 ruff /
错误行一键修复"三件事。把"怎么调 ruff、怎么解析 JSON、多源诊断怎么合并"
这类不依赖 Qt 的规则搬到这里，GUI 只留几行接线。

三个数据源与优先级（深度⑧）
--------------------------
1. **LSP 诊断**：语言服务已经在跑，它的诊断最准（类型错误也能报）；
2. **ruff（实时，文本走 stdin）**：未保存也准，规则类问题；
3. **ast**：语法错误兜底，永远可用、零依赖。

``merge_problems`` 只返回**一个**列表（页面/状态栏只有一个计数），
规则是"非空的最高优先级优先"，避免同一处问题被三个源各报一次。
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

SOURCE_LSP = "LSP"
SOURCE_RUFF = "ruff"
SOURCE_AST = "ast"
LIVE_TIMEOUT_SEC = 3.0
MAX_ROWS = 200


def ruff_base():
    """ruff 命令前缀：PATH 里有就用它，否则 `python -m ruff`。"""
    exe = shutil.which("ruff")
    return [exe] if exe else [sys.executable, "-m", "ruff"]


def ruff_command(path):
    """检查磁盘上的文件（保存/打开后用）。"""
    return ruff_base() + ["check", "--output-format=json", "--quiet",
                          "--", str(path)]


def ruff_stdin_command(path):
    """检查**编辑器里的文本**（深度⑨）：未保存的内容也参与检查。"""
    return ruff_base() + ["check", "--output-format=json", "--quiet",
                          "--stdin-filename", str(path), "-"]


def parse_ruff_json(text):
    """ruff JSON → [(行, 列, 规则码, 描述)]；不是合法 JSON 返回 None。"""
    try:
        data = json.loads(text or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        loc = item.get("location") or {}
        try:
            rows.append((int(loc.get("row") or 1),
                         int(loc.get("column") or 1),
                         str(item.get("code") or ""),
                         str(item.get("message") or "")))
        except (TypeError, ValueError):
            continue
    return rows


def ast_problems(code):
    """兜底：没跑成 ruff 时只报语法错误（与实时下划线同源）。"""
    try:
        ast.parse(code or "")
    except SyntaxError as ex:
        return [(int(ex.lineno or 1), int(ex.offset or 1), "SyntaxError",
                 str(ex.msg or "语法错误"))]
    return []


def live_ruff(text, path, timeout=LIVE_TIMEOUT_SEC):
    """实时检查：把文本喂给 ``ruff --stdin-filename``，返回行列表或 None。

    同步跑（不是 QProcess）：只在编辑停手 900ms 后触发，超时有上限，
    最坏情况是 -3s 的卡顿；换来的是"未保存也能标红"，比"只认磁盘"值。
    """
    if not str(path or "").lower().endswith((".py", ".pyw")):
        return None
    try:
        proc = subprocess.run(
            ruff_stdin_command(path), input=str(text or ""),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=float(timeout or LIVE_TIMEOUT_SEC),
            cwd=os.path.dirname(os.path.abspath(str(path))) or None,
            shell=False)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        # 静默是故意的 - 实时检查跑不起来就靠 ast，不影响编辑
        _x6_swallowed(__name__, e, "live ruff")
        return None
    return parse_ruff_json(proc.stdout)


def lsp_rows(diagnostics, path=""):
    """LSP ``publishDiagnostics`` → [(行, 列, 来源, 描述)]（只留错误/警告）。"""
    target = _norm_path(path)
    rows = []
    for uri, items in (diagnostics or {}).items():
        if target and not _same_doc(uri, target):
            continue
        for item in items or []:
            if not isinstance(item, dict):
                continue
            rng = item.get("range") or {}
            if not rng:
                continue          # 没有定位的诊断不能画波浪线，也不算问题
            severity = item.get("severity") or 1
            try:
                severity = int(severity)
            except (TypeError, ValueError):
                severity = 1
            if severity > 2:
                continue          # 3=Info 4=Hint：不当问题计数
            start = rng.get("start") or {}
            try:
                line = int(start.get("line") or 0) + 1
                col = int(start.get("character") or 0) + 1
            except (TypeError, ValueError):
                continue
            code = str(item.get("source") or "LSP")
            # 警告带 ⚠ 前缀：问题页据此标橙，错误标红（页面只有 4 元组可用）
            prefix = "⚠ " if severity == 2 else ""
            rows.append((line, col, "LSP·" + code,
                         prefix + str(item.get("message") or "")[:200]))
            if len(rows) >= MAX_ROWS:
                return rows
    return rows


def _norm_path(value):
    text = str(value or "").strip()
    if text.startswith("file://"):
        try:
            from core.lsp_protocol import path_for_uri
            text = path_for_uri(text)
        # 静默是故意的 - URI 解析不了就按原文比对，不影响其它诊断
        except Exception as e:
            _x6_swallowed(__name__, e, "normalize uri")
            text = text[len("file://"):]
    text = text.replace("\\", "/")
    if os.path.isabs(text) or re.match(r"^[A-Za-z]:", text):
        return os.path.normcase(os.path.normpath(text)).replace("\\", "/")
    return text


def _same_doc(uri, target):
    """URI 与目标路径是否指向同一个文件（绝对/相对路径都要能对上）。"""
    left, right = _norm_path(uri), _norm_path(target)
    if not left or not right:
        return False
    if left == right:
        return True
    if os.path.isabs(left) and os.path.isabs(right):
        return False
    # 一边相对一边绝对（测试里常见）：退到文件名比对
    return os.path.basename(left) == os.path.basename(right)


def merge_problems(*groups):
    """多源诊断合并：非空的最高优先级优先（LSP > ruff > ast）。"""
    for rows in groups:
        rows = list(rows or [])
        if rows:
            return rows[:MAX_ROWS]
    return []


def status():
    """自检摘要：有没有 ruff / 走哪条通道。"""
    base = ruff_base()
    return {"ruff": os.path.basename(base[0]) if base else "",
            "可用": bool(base), "来源": [SOURCE_LSP, SOURCE_RUFF, SOURCE_AST]}
