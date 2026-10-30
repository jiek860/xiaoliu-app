# -*- coding: utf-8 -*-
"""函数签名：抽取当前所在函数的定义，生成调用模板。

为什么用正则而不是 ast
----------------------
这里只服务"光标在函数体内 -> 插入一行调用模板"这一个场景，需要容忍
**正在编辑、语法还不完整**的代码；``ast.parse`` 遇到未闭合括号会直接失败，
正则反而更稳。完整的结构分析仍由 ``core.code.index_v2`` 负责。
"""
from __future__ import annotations

import re

_DEF_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:async[ \t]+)?def[ \t]+(?P<name>\w+)"
    r"[ \t]*\((?P<args>[^)]*)\)", re.MULTILINE)
MAX_PARAMS = 12


def defs(source):
    """列出所有函数定义：``[{name, args, line, indent}]``（行号 1-based）。"""
    text = str(source or "")
    out = []
    for m in _DEF_RE.finditer(text):
        start = text.count("\n", 0, m.start()) + 1
        out.append({"name": m.group("name"), "args": m.group("args"),
                    "line": start, "indent": m.group("indent")})
    return out


def params(args):
    """参数串 -> 名字列表（跳过 self/cls/*args/**kwargs 的星号）。"""
    out = []
    for raw in str(args or "").split(","):
        name = raw.strip().split("=")[0].strip().lstrip("*")
        name = name.split(":")[0].strip()
        if not name or name in ("self", "cls"):
            continue
        out.append(name)
        if len(out) >= MAX_PARAMS:
            break
    return out


def signature_at(source, line):
    """返回包含第 ``line`` 行的函数定义（同一缩进块内），没有返回 {}。"""
    if int(line or 0) <= 0:
        return {}
    line = int(line)
    best = {}
    for item in defs(source):
        if int(item["line"]) <= line:
            best = item
    return best


def call_template(sig, placeholders=True):
    """``def foo(a, b)`` -> ``foo(a=a, b=b)``（占位写法，方便直接改）。"""
    name = str((sig or {}).get("name") or "")
    if not name:
        return ""
    names = params((sig or {}).get("args") or "")
    if not names:
        return name + "()"
    if not placeholders:
        return "%s(%s)" % (name, ", ".join(names))
    return "%s(%s)" % (name, ", ".join("%s=%s" % (n, n) for n in names))


def signature_text(sig):
    """一行签名（状态栏/工具提示用）。"""
    if not sig:
        return ""
    return "def %s(%s)" % (sig.get("name"), sig.get("args"))
