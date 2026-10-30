# -*- coding: utf-8 -*-
"""运行输出解析：退出码、异常类型、失败位置。

为什么独立
----------
``code_editor_runner`` 只负责把进程输出贴进文本框；"这段输出说明了什么"
是纯文本规则，独立出来后既能被运行页用，也能被测试页/代码 Agent 复用。
"""
from __future__ import annotations

import re

try:
    from core.code.verify import locate_failures
except ImportError:  # pragma: no cover
    def locate_failures(output, index=None, root=None):
        return []

_EXC_RE = re.compile(r"^(?P<type>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|"
                     r"Warning|Interrupt|Exit)):?\s*(?P<msg>.*)$")
_FILE_LINE_RE = re.compile(r'File "([^"]+)", line (\d+)')
MAX_EXCEPTIONS = 10


def exceptions(text):
    """从 traceback 里抽异常：``[{type, message, file, line}]``（自后向前）。"""
    lines = str(text or "").splitlines()
    out = []
    last_loc = None
    for raw in lines:
        stripped = raw.strip()
        loc = _FILE_LINE_RE.search(stripped)
        if loc:
            last_loc = (loc.group(1), int(loc.group(2)))
            continue
        m = _EXC_RE.match(stripped)
        if not m:
            continue
        typ = m.group("type")
        # "Traceback (most recent call last):" 这类不是异常
        if typ in ("Traceback",):
            continue
        out.append({"type": typ, "message": m.group("msg").strip(),
                    "file": (last_loc or ("", 0))[0],
                    "line": (last_loc or ("", 0))[1]})
        if len(out) >= MAX_EXCEPTIONS:
            break
    return out


def last_exception(text):
    """最后一个异常（终端里真正导致程序的失败的那个）。"""
    items = exceptions(text)
    return items[-1] if items else {}


def failed_locations(text, root=None):
    """输出里出现过的 ``文件:行``（去重），双击问题页可跳。"""
    return locate_failures(text, None, root)


def exit_text(code):
    """退出码 -> 人话。"""
    code = int(code or 0)
    if code == 0:
        return "退出码 0（成功）"
    if code == 2:
        return "退出码 2（用法错误）"
    if code == 130:
        return "退出码 130（被 Ctrl+C 中断）"
    return "退出码 %d（运行出错）" % code


def summary(text, code=0, root=None):
    """一行结论：成功 / 失败类型 + 位置。"""
    exc = last_exception(text)
    if code == 0 and not exc:
        return "运行完成，没有报错"
    if not exc:
        return exit_text(code)
    loc = ""
    if exc.get("file"):
        loc = " @ %s:%d" % (exc["file"], int(exc.get("line") or 0))
    return "%s: %s%s" % (exc.get("type"), (exc.get("message") or "")[:80], loc)
