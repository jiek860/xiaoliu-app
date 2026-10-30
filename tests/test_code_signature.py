# -*- coding: utf-8 -*-
"""函数签名抽取与调用模板。"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code import signature  # noqa: E402

SRC = '''def foo(a, b=2):
    return a + b

class A:
    async def bar(self, x, *args, **kwargs):
        return x

def empty():
    pass
'''


def test_defs_lists_functions_with_lines():
    names = [d["name"] for d in signature.defs(SRC)]
    assert names == ["foo", "bar", "empty"]
    assert signature.defs(SRC)[0]["line"] == 1


def test_params_skips_self_and_stars():
    assert signature.params("self, x, *args, **kwargs") == ["x", "args", "kwargs"]
    assert signature.params("a: int = 1, b") == ["a", "b"]


def test_signature_at_picks_enclosing_def():
    assert signature.signature_at(SRC, 2)["name"] == "foo"
    assert signature.signature_at(SRC, 7)["name"] == "bar"
    assert signature.signature_at(SRC, 0) == {}


def test_call_template_forms():
    sig = {"name": "foo", "args": "a, b=2"}
    assert signature.call_template(sig) == "foo(a=a, b=b)"
    assert signature.call_template(sig, placeholders=False) == "foo(a, b)"
    assert signature.call_template({"name": "empty", "args": ""}) == "empty()"
    assert signature.call_template({}) == ""


def test_signature_text():
    assert signature.signature_text({"name": "foo", "args": "a, b=2"}) == \
        "def foo(a, b=2)"
    assert signature.signature_text({}) == ""
