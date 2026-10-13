# -*- coding: utf-8 -*-
"""错误信息面向用户化的验收 + 回归保护

为什么需要
----------
原来报错是："「识别图片文字」执行出错：TypeError: OCR.available() takes 1
positional argument but 2 were given"

对开发者有用，对用户没用 —— 既不知道发生了什么，也不知道该做什么。
翻译之后要变成两句话：**发生了什么 + 下一步做什么**，原文不丢。

这个文件守住三件事：
    ① 常见错误能翻译出"人话 + 下一步"
    ② 拿不准的错误**不许瞎猜**（宁可保留原文）
    ③ 接进 trunk.call / 能力分发之后，真的生效
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.error_text import friendly, describe          # noqa: E402


# ── ① 常见错误能翻译 ──
CASES = [
    # (异常, 人话里该有的关键词, 下一步里该有的关键词)
    (ModuleNotFoundError("No module named 'pyautogui'"),
     "可选组件", "pip install"),
    (ConnectionRefusedError("[WinError 10061] 由于目标计算机积极拒绝"),
     "连不上", "服务"),
    (TimeoutError("Read timed out"),
     "等太久", "重试"),
    (FileNotFoundError("[Errno 2] No such file or directory: 'D:\\x.txt'"),
     "找不到文件", "路径"),
    (PermissionError("[WinError 5] 拒绝访问"),
     "没有权限", "占用"),
    (ValueError("Expecting value: line 1 column 1 (char 0)"),
     "数据文件坏了", "json"),
    (TypeError("OCR.available() takes 1 positional argument but 2 were given"),
     "对不上", "版本"),
    (KeyError("config_key"),
     "少了必要字段", "版本"),
    (MemoryError("out of memory"),
     "内存", "关掉"),
]


@pytest.mark.parametrize("exc,what_kw,todo_kw", CASES)
def test_common_errors_are_translated(exc, what_kw, todo_kw):
    what, todo = friendly(exc)
    assert what, "%s 没翻译出人话" % type(exc).__name__
    assert what_kw in what or what_kw in todo, \
        "%s 的翻译里没有 %r：%s / %s" % (type(exc).__name__, what_kw, what, todo)
    assert todo, "%s 没给下一步" % type(exc).__name__


# ── ② 拿不准的不能瞎猜 ──
def test_unknown_error_keeps_original_text():
    """没见过的错误必须保留原文，不能编一个建议出来"""
    what, todo = friendly("某个从没见过的诡异错误 xyz123")
    assert what == "" and todo == "", "不该为未知错误编造解释：%r / %r" % (what, todo)
    d = describe("某个从没见过的诡异错误 xyz123", subject="测试功能")
    assert "xyz123" in d, "原文丢了：%s" % d
    assert "出错了" in d


# ── ③ describe 的成品形态 ──
def test_describe_has_subject_and_detail():
    d = describe(ModuleNotFoundError("No module named 'pyautogui'"),
                 subject="识别图片文字")
    assert "识别图片文字" in d, d
    assert "可选组件" in d, d
    assert "下一步" in d, d
    assert "技术细节" in d, "原文没保留：%s" % d
    assert "pyautogui" in d, d


# ── ④ 接进 trunk.call 后真的生效 ──
def test_trunk_call_error_is_user_friendly():
    from tests.conftest import make_trunk
    t = make_trunk()
    # 造一个一定会抛异常的方法
    class _Boom:
        def fail(self):
            raise ModuleNotFoundError("No module named 'nonexistent_pkg'")
    t.modules["_boommod"] = _Boom()
    r = t.call("_boommod", "fail")
    assert isinstance(r, dict) and r.get("ok") is False, r
    err = r.get("error", "")
    assert "可选组件" in err, "trunk.call 没做翻译：%s" % err
    assert "下一步" in err, "没给下一步：%s" % err
    assert r.get("技术细节"), "技术细节字段没了：%s" % r
    del t.modules["_boommod"]


# ── ⑤ 能力分发路径也生效 ──
def test_capability_error_is_user_friendly():
    from tests.conftest import make_trunk
    from core import safe as _safe
    t = make_trunk()
    tc = t._load_lazy("tool_caller")
    _safe.clear_errors()

    class _Boom2:
        @_safe.safe
        def go(self):
            raise ConnectionRefusedError("[WinError 10061] 目标计算机积极拒绝")
    t.modules["_boommod2"] = _Boom2()
    _Boom2().go()                      # 制造一次 @safe 错误记录
    try:
        r = tc._explain_none(
            {"mod": "_boommod2", "method": "go", "desc": "x", "args": {},
             "readonly": True}, None, "连个服务")
        assert isinstance(r, dict), r
        assert "连不上" in str(r), "能力分发没做翻译：%s" % r
    finally:
        del t.modules["_boommod2"]


def test_friendly_handles_none_and_empty():
    """空输入不能炸"""
    assert friendly(None) == ("", "")
    assert friendly("") == ("", "")
    assert describe(None) == "出错了："
