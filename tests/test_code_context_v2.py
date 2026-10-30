# -*- coding: utf-8 -*-
"""上下文 v2（批次 45.3/45.4）：优先级、预算、失败栈、灰度三态。"""
import os

from core.code.context_v2 import (build, estimate_tokens, mode,
                                  parse_failure)
from core.code_context import CodeContextMixin
from core.workspace_index import WorkspaceIndex

SOURCE = '''\
def helper(x):
    return x + 1


def wrapper():
    return helper(1)
'''


def _write(root, rel, text):
    path = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return path


def _project(tmp):
    _write(tmp, "core/util.py", SOURCE)
    _write(tmp, "tests/test_util.py",
           "from core.util import helper\n\ndef test_helper():\n"
           "    assert helper(1)\n")
    index = WorkspaceIndex(str(tmp), workspace_root=str(tmp))
    index.rebuild()
    return index


class _Ctx:
    def __init__(self):
        self.rows = []

    def record_shadow(self, payload):
        self.rows.append(payload)
        return True


class _Trunk:
    def __init__(self, how="shadow", sample=0.0):
        self.how = how
        self.sample = sample
        self.ctx = _Ctx()

    def rule(self, name, default=None):
        if name == "code.context_v2":
            return self.how
        if name == "code.context_v2_sample":
            return self.sample
        return default


class _Host(CodeContextMixin):
    def __init__(self, root, index, trunk):
        self.root = str(root)
        self.index = index
        self.trunk = trunk
        self.selection = ""
        self.open_files = []
        self.last_error = ""


def test_estimate_tokens_monotonic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("中文字符") >= 4
    assert estimate_tokens("a" * 400) == 100


def test_parse_failure_two_formats_and_symbol(tmp_path):
    index = _project(tmp_path)
    failure = ("Traceback (most recent call last):\n"
               '  File "core/util.py", line 5, in wrapper\n'
               "    return helper(1)\n"
               "core/util.py:2:1: error: boom\n")
    items = parse_failure(failure, str(tmp_path), index)
    assert [(i["path"], i["line"]) for i in items] == [
        ("core/util.py", 5), ("core/util.py", 2)]
    assert items[0]["symbol"] == "wrapper"
    assert items[1]["symbol"] == "helper"


def test_build_priority_order(tmp_path):
    index = _project(tmp_path)
    failure = '  File "core/util.py", line 5, in wrapper'
    built = build("修复 wrapper", root=str(tmp_path), index=index,
                  selection="选中的代码", last_error=failure,
                  rules="## 规则\n- 必须跑测试")
    text = built["text"]
    assert text.index("PROJECT RULES") < text.index("=== TASK") \
        < text.index("USER SELECTION") < text.index("FAILURE STACK")
    assert "wrapper" in text
    assert built["tokens"] == estimate_tokens(text)


def test_build_respects_budget(tmp_path):
    index = _project(tmp_path)
    built = build("修复 helper", root=str(tmp_path), index=index,
                  selection="x" * 5000, max_chars=1200)
    assert len(built["text"]) <= int(1200 * 0.75)
    assert built["tokens"] <= estimate_tokens("x" * int(1200 * 0.75))


def test_build_without_index_or_inputs_is_safe(tmp_path):
    built = build("随便看看", root=str(tmp_path), index=None)
    assert "=== TASK ===" in built["text"]
    assert built["files"] == []
    assert built["truncated"] is False


def test_mode_defaults_on():
    # 批次 D7：显式 shadow/on 生效；未知值按默认 on
    assert mode(_Trunk("shadow")) == "shadow"
    assert mode(_Trunk("ON")) == "on"
    assert mode(_Trunk("whatever")) == "on"


def test_integration_on_mode_uses_v2(tmp_path):
    index = _project(tmp_path)
    host = _Host(tmp_path, index, _Trunk("on"))
    built = host.build_context("修复 helper", max_files=6, max_chars=8000)
    assert built["mode"] == "on"
    assert "=== TASK ===" in built["text"]
    assert built["tokens"] <= estimate_tokens("x" * 6000)


def test_integration_off_mode_keeps_legacy(tmp_path):
    index = _project(tmp_path)
    host = _Host(tmp_path, index, _Trunk("off"))
    built = host.build_context("修复 helper", max_files=6, max_chars=8000)
    assert built.get("mode") is None
    assert "context_v2" not in built


def test_integration_shadow_sample_zero_keeps_legacy(tmp_path):
    index = _project(tmp_path)
    trunk = _Trunk("shadow", sample=0.0)
    host = _Host(tmp_path, index, trunk)
    built = host.build_context("修复 helper", max_files=6, max_chars=8000)
    assert "context_v2" not in built
    assert trunk.ctx.rows == []


def test_integration_shadow_sample_one_records(tmp_path):
    index = _project(tmp_path)
    trunk = _Trunk("shadow", sample=1.0)
    host = _Host(tmp_path, index, trunk)
    built = host.build_context("修复 helper", max_files=6, max_chars=8000)
    assert built["context_v2"]["mode"] == "shadow"
    assert trunk.ctx.rows[-1]["kind"] == "context_v2"
    assert trunk.ctx.rows[-1]["tokens"] >= 1
