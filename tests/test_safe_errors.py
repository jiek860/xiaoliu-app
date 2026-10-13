# -*- coding: utf-8 -*-
"""@safe 静默错误的可观测性测试

背景
----
@safe 出错时返回 None，**它确实记了日志**（error + 完整堆栈），
但调用方拿到 None —— 和"这方法本来就返回空"完全无法区分。

实测吃过的亏：`ocr_available()` 被多传了一个参数，TypeError 被吞成 None，
现象上就是"这功能没反应"。同类问题还有 check_conflicts 那个
`open(...)[-200:]`（必然 TypeError，功能从来没成功过）。

本文件验证两件事：
    ① core/safe.py 的 last_error() 能查到最近一次错误（且支持限定名防串台）
    ② tool_caller._explain_none() 把"因出错返回的 None"变成明确的失败信息，
       同时**不误报**真正返回空的情况
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core import safe as _safe                    # noqa: E402
from core.trunk import Trunk                      # noqa: E402
from tests.conftest import make_trunk             # noqa: E402


class _Boom:
    @_safe.safe
    def do_it(self):
        raise RuntimeError("模拟能力炸了")


class _Quiet:
    @_safe.safe
    def nothing(self):
        return None                               # 正常返回空，没出错


def _tc():
    """必须用 make_trunk()，不能直接 Trunk()

    本文件每个用例都建一个 Trunk，直接 Trunk() 的话每个都会在 3 秒后
    后台连 MCP（4 个子进程，累积不释放）—— 实测把 test_mcp_client 里
    那条断言全局 live_count() 的用例搞挂了。见 tests/conftest.py 的说明。
    """
    t = make_trunk()
    return t, t._load_lazy("tool_caller")


def test_safe_records_error_by_name_and_qualname():
    """出错要能按函数名和限定名都查到（防 stats/run 这类同名方法串台）"""
    _safe.clear_errors()
    assert _Boom().do_it() is None                # 行为不变：仍返回 None
    assert _safe.last_error("do_it"), "按函数名查不到"
    assert _safe.last_error("_Boom.do_it"), "按限定名查不到"
    assert "RuntimeError" in _safe.last_error("_Boom.do_it")


def test_safe_does_not_touch_record_on_normal_none():
    """正常返回 None 不该留下错误记录"""
    _safe.clear_errors()
    assert _Quiet().nothing() is None
    assert _safe.last_error("_Quiet.nothing") is None


def test_last_error_expires():
    """过期错误不能算到下一次调用头上

    用 **负数窗口** 而不是 0：within=0 的判定是 `elapsed > 0`，
    如果记录和查询发生在同一个时钟刻度里，elapsed 正好是 0.0，
    `0 > 0` 为假 -> 判定成"没过期" -> 用例偶发失败。
    （实测踩到过：全量跑时它挂了一次，单跑又通过 —— 典型的脆弱测试。）
    负数窗口下 elapsed >= 0 > -1 恒成立，结果确定。
    """
    _safe.clear_errors()
    _Boom().do_it()
    assert _safe.last_error("_Boom.do_it") is not None
    assert _safe.last_error("_Boom.do_it", within=-1) is None, \
        "负窗口也该算过期，说明窗口判断没生效"


def test_explain_none_reports_error_instead_of_silent_none():
    """因出错返回的 None -> 明确的失败信息（这是本文件的核心）"""
    t, tc = _tc()
    _safe.clear_errors()
    _Boom().do_it()
    t.modules["_fakemod"] = type("M", (), {"do_it": _Boom.do_it})
    try:
        r = tc._explain_none(
            {"mod": "_fakemod", "method": "do_it", "desc": "x", "args": {},
             "readonly": True}, None, "模拟能力")
        assert isinstance(r, dict) and r.get("ok") is False, r
        assert "模拟能力" in str(r), "没点明是哪个能力"
        assert "炸了" in str(r) or "RuntimeError" in str(r), "没带上原因"
    finally:
        del t.modules["_fakemod"]


def test_explain_none_keeps_real_none():
    """真正返回空的情况必须保持 None —— 不能误报成错误"""
    t, tc = _tc()
    _safe.clear_errors()
    t.modules["_quietmod"] = type("M", (), {"nothing": _Quiet.nothing})
    try:
        r = tc._explain_none(
            {"mod": "_quietmod", "method": "nothing", "desc": "x", "args": {},
             "readonly": True}, None, "安静能力")
        assert r is None, "真没结果被误报成错误了：%r" % (r,)
    finally:
        del t.modules["_quietmod"]


def test_dispatch_surfaces_the_original_type_error_bug():
    """回归：当初 ocr_available 被多传参数 -> TypeError -> 静默 None 的坑

    现在同一条路径必须给出明确的失败信息，而不是 None。
    """
    t, tc = _tc()
    _safe.clear_errors()
    info = dict(tc.tools["ocr_available"])
    r = tc._dispatch(info, {"不存在的参数": "x"}, "")
    # 允许两种正确结果：要么走兜底没出错，要么明确报错；
    # **不允许**的是"静默 None 且日志里有 TypeError"
    if r is None:
        err = _safe.last_error("available") or _safe.last_error("OCR.available")
        assert not err, "静默返回了 None，但日志里其实有错误：%s" % err
