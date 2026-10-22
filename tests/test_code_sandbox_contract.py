# -*- coding: utf-8 -*-
"""代码沙盒验证契约测试（修复"沙盒验证运行失败"误报）。

真实故障（2026-10-21）：
    code_runner.run() 成功时只返回 stdout/returncode，
    **没有 "成功" 字段**；而 post_processor.verify_code() 读 res.get("成功")，
    于是任何代码块都被判成"运行失败"，即使代码完全正确。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


class _Trunk:
    base = BASE
    config = {}

    def _log(self, *_a):
        pass

    def _load_lazy(self, name):
        if name == "code_runner":
            from modules.installed.code_runner import CodeExecutor
            return CodeExecutor(self)
        return None


def _runner():
    from modules.installed.code_runner import CodeExecutor
    return CodeExecutor(_Trunk())


# ---------- code_runner 返回契约 ----------
def test_success_result_has_unified_fields():
    r = _runner().run("print(1 + 1)\n", timeout=15)
    for key in ("成功", "输出", "错误", "stdout", "stderr", "returncode"):
        assert key in r, "缺字段 %s" % key
    assert r["成功"] is True
    assert "2" in r["输出"]


def test_definition_only_is_still_success():
    """只定义函数没调用：进程退出码 0，应算成功（不是失败）。"""
    r = _runner().run("def add(a, b):\n    return a + b\n", timeout=15)
    assert r["成功"] is True
    assert r["输出"] == "(无输出)"


def test_runtime_error_reports_failure():
    r = _runner().run("1/0\n", timeout=15)
    assert r["成功"] is False
    assert r["错误"]


def test_syntax_error_reports_failure():
    r = _runner().run("def f(:\n", timeout=15)
    assert r["成功"] is False
    assert r["错误"]


def test_timeout_reports_failure():
    r = _runner().run("while True:\n    pass\n", timeout=2)
    assert r["成功"] is False
    assert "超时" in r["错误"]


# ---------- post_processor 端到端 ----------
def _pp():
    from core.pipeline.post_processor import PostProcessor
    return PostProcessor(_Trunk())


def test_verify_code_reports_success_for_valid_code():
    """有实际输出时显示"运行成功"。"""
    answer = "可以。\n\n```python\nprint(1 + 1)\n```\n\n完成。"
    out = _pp().verify_code("写一个 Python 函数计算两数之和", answer)
    assert "沙盒验证运行成功" in out
    assert "运行失败" not in out


def test_verify_code_definition_only_is_not_failure():
    answer = "可以。\n\n```python\ndef add(a, b):\n    return a + b\n```\n\n完成。"
    out = _pp().verify_code("写一个 Python 函数计算两数之和", answer)
    assert "运行失败" not in out
    assert "通过" in out


def test_verify_code_reports_failure_for_broken_code():
    answer = "好的。\n\n```python\n1/0\n```\n\n完成。"
    out = _pp().verify_code("写代码", answer)
    assert "沙盒验证运行失败" in out


def test_verify_code_marks_definition_only_explicitly():
    answer = "```python\ndef add(a, b):\n    return a + b\n```"
    out = _pp().verify_code("写一个函数", answer)
    assert "通过" in out
    assert "未产生输出" in out


def test_verify_code_compat_with_legacy_returncode_only():
    """旧版 code_runner 只返回 returncode 时也不能误报失败。"""
    class Legacy:
        def run(self, *_a, **_k):
            return {"stdout": "", "stderr": "", "returncode": 0}

    pp = _pp()
    pp.trunk._load_lazy = lambda name: Legacy() if name == "code_runner" else None
    out = pp.verify_code("写代码", "```python\ndef f():\n    return 1\n```")
    assert "运行失败" not in out


def test_non_code_message_is_untouched():
    answer = "这是一段普通回答，没有代码。"
    assert _pp().verify_code("你好", answer) == answer
