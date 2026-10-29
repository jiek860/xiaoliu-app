# -*- coding: utf-8 -*-
"""影响面选测与失败定位（批次 46.4）。

为什么单独成模块
----------------
``CodeAgent`` 已经有"全量跑测试"（``pytest -q``）。仓库大了以后一轮 6 分钟，
回修迭代就被拖死。这里只做三件纯函数的事：

* ``select_tests``：按"改动的文件"从 import 反查受影响测试（复用 45.1 索引）；
* ``selected_commands``：把选出的测试文件拼到 pytest 命令上，找不到 pytest
  就返回空（= 继续跑全量，不冒险漏测）；
* ``locate_failures``：把 pytest 的 ``File "x", line N`` / ``x.py:N`` 映射到
  函数名，回修提示里直接写"失败在 core/foo.py:42 func"，模型更容易定点修；
* ``retry_flakes``：失败用例单独重跑一次，只有"重跑仍挂"才算真失败，
  避免偶发用例把整轮循环拖进无意义的回修。

开关 ``code.verify_select`` 默认 off：关掉就是旧的全量测试行为。
"""
from __future__ import annotations

import os
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MAX_TESTS = 20
MAX_LOCATIONS = 20

_FILE_LINE_RE = re.compile(r'File "([^"]+)", line (\d+)')
_PATH_LINE_RE = re.compile(
    r"(?<![\w/.-])([A-Za-z]:[\\/][^\s:]+\.py|[\w./\\-]+\.py):(\d+)(?::\d+)?")
_PYTEST_FAILED_RE = re.compile(r"FAILED\s+([^\s:]+)::([^\s]+)")


def _rel(path, root=None):
    text = str(path or "").strip().strip("'\"")
    text = text.replace("\\", "/")
    if root and os.path.isabs(text):
        try:
            text = os.path.relpath(text, str(root)).replace("\\", "/")
        except ValueError:
            pass
    while text.startswith("./"):
        text = text[2:]
    return text


def select_tests(index, changed_files):
    """按改动文件选测试；``index`` 可以是 CodeIndexV2 或 WorkspaceIndex。"""
    out, seen = [], set()
    for rel in changed_files or []:
        rel = _rel(rel)
        if not rel:
            continue
        paths = []
        try:
            if hasattr(index, "tests_for"):
                paths = index.tests_for(rel) or []
            elif hasattr(index, "related_tests"):
                paths = index.related_tests(rel) or []
        except Exception as e:  # 静默是故意的 - 选测失败就退回全量
            _x6_swallowed(__name__, e, "select tests")
            paths = []
        for item in paths:
            path = item.get("path") if isinstance(item, dict) else item
            path = _rel(path)
            if not path or path in seen:
                continue
            base = os.path.basename(path)
            if not (base.startswith("test_") or path.startswith("tests/")):
                continue
            seen.add(path)
            out.append(path)
    return out[:MAX_TESTS]


def build_test_command(commands, tests):
    """把测试文件拼到第一条 pytest 命令上；没有 pytest 返回空字符串。"""
    if not tests:
        return ""
    for cmd in commands or []:
        text = str(cmd or "")
        if "pytest" not in text:
            continue
        files = [t for t in tests if str(t).strip()]
        if not files:
            return ""
        return text.rstrip() + " " + " ".join(files)
    return ""


def _index_for(agent):
    index = getattr(agent, "_code_index_v2", None)
    if index is not None:
        return index
    from core.code.index_v2 import CodeIndexV2
    base = getattr(getattr(agent, "trunk", None), "base", None) \
        or getattr(agent, "root", ".")
    index = CodeIndexV2(base, getattr(agent, "root", base))
    try:
        index.refresh(getattr(agent, "root", base))
    except Exception as e:  # 静默是故意的 - 索引失败就退回全量
        _x6_swallowed(__name__, e, "refresh index for verify")
    try:
        agent._code_index_v2 = index
    except Exception as e:
        _x6_swallowed(__name__, e, "cache index")
    return index


def selected_commands(agent, changed_files):
    """``code.verify_select=on`` 时返回选测命令；其他情况返回 []。"""
    from core.patch_protocol import verify_mode
    if verify_mode(getattr(agent, "trunk", None)) != "on":
        return []
    try:
        index = _index_for(agent)
        tests = select_tests(index, changed_files)
        if not tests:
            return []
        commands = list(getattr(agent, "test_commands", None)
                        or agent.detect_test_commands())
        cmd = build_test_command(commands, tests)
        if not cmd:
            return []
        agent._emit("verify_select", {
            "step": "按影响面选测 %d 个文件" % len(tests),
            "tests": tests, "command": cmd})
        return [cmd]
    except Exception as e:  # 静默是故意的 - 选测只是加速，失败必须退回全量
        _x6_swallowed(__name__, e, "verify selected commands")
        return []


def _symbol_at(index, rel, line):
    if index is None:
        return ""
    try:
        outline = index.outline(rel) or []
    except Exception as e:
        _x6_swallowed(__name__, e, "locate outline")
        return ""
    best = ""
    best_start = -1
    for item in outline:
        try:
            start = int(item.get("start_line") or 0)
            end = int(item.get("end_line") or start)
        except (TypeError, ValueError):
            continue
        if start <= line <= end and start >= best_start:
            best_start = start
            best = str(item.get("symbol") or "")
    return best


def _symbol_from_file(root, rel, line):
    try:
        from core.patch_protocol import function_span
        with open(os.path.join(str(root), rel.replace("/", os.sep)),
                  encoding="utf-8", errors="replace") as fp:
            span = function_span(fp.read(), line)
        return str((span or {}).get("name") or "")
    except (OSError, ValueError) as e:
        _x6_swallowed(__name__, e, "locate symbol from file")
        return ""


def locate_failures(output, index=None, root=None):
    """解析失败位置并补上函数名，供回修提示直接定位。"""
    text = str(output or "")
    found, seen = [], set()
    for pattern in (_FILE_LINE_RE, _PATH_LINE_RE):
        for m in pattern.finditer(text):
            rel = _rel(m.group(1), root)
            try:
                line = int(m.group(2))
            except (TypeError, ValueError):
                continue
            if not rel.endswith(".py") or line <= 0:
                continue
            key = (rel, line)
            if key in seen:
                continue
            seen.add(key)
            symbol = _symbol_at(index, rel, line)
            if not symbol and root:
                symbol = _symbol_from_file(root, rel, line)
            found.append({"file": rel, "line": line, "symbol": symbol})
            if len(found) >= MAX_LOCATIONS:
                return found
    return found


def locate_digest(found):
    """把定位结果压成提示词里的一小段。"""
    lines = []
    for item in found or []:
        label = "%s:%s" % (item.get("file"), item.get("line"))
        if item.get("symbol"):
            label += " (%s)" % item.get("symbol")
        if label not in lines:
            lines.append(label)
    return "\n".join("  - " + x for x in lines[:MAX_LOCATIONS])


def retry_flakes(run_case, test_ids, retries=1):
    """重跑失败用例：重跑通过=flake，仍失败=real。``run_case(id)->{ok}``。"""
    real, flakes = [], []
    attempts = 0
    for test_id in test_ids or []:
        passed = False
        for _ in range(max(0, int(retries)) + 1):
            attempts += 1
            try:
                result = run_case(test_id) or {}
            except Exception as e:  # 静默是故意的 - 单用例重跑失败按真失败处理
                _x6_swallowed(__name__, e, "retry flake")
                result = {"ok": False}
            if result.get("ok"):
                passed = True
                break
        (flakes if passed else real).append(str(test_id))
    return {"real": real, "flakes": flakes, "attempts": attempts}


def failed_test_ids(output):
    """从 pytest 短摘要里取 ``file::test`` 列表（去重）。"""
    out, seen = [], set()
    for m in _PYTEST_FAILED_RE.finditer(str(output or "")):
        test_id = "%s::%s" % (m.group(1), m.group(2))
        if test_id not in seen:
            seen.add(test_id)
            out.append(test_id)
    return out[:MAX_TESTS]
