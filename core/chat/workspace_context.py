# -*- coding: utf-8 -*-
"""聊天上下文拼装：把文件 / 选区压成给模型看的一小段文本。

为什么单独成模块
----------------
工作台（编辑器）和聊天窗口都要用同一套格式，格式如果两边各写一份，
模型看到的「文件:行」引用就会不一致，47.3 的可点击引用也认不出来。

约束：纯函数，不读 UI、不调模型；文件读失败返回带 error 的 dict。
"""
from __future__ import annotations

import os

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MAX_FILE_CHARS = 4000
MAX_SELECTION_CHARS = 2000
_LANG = {".py": "python", ".md": "markdown", ".json": "json",
         ".html": "html", ".css": "css", ".js": "javascript",
         ".ts": "typescript", ".java": "java", ".c": "c", ".cpp": "cpp",
         ".go": "go", ".rs": "rust", ".sql": "sql", ".yaml": "yaml",
         ".yml": "yaml", ".sh": "bash", ".bat": "bat", ".ps1": "powershell"}


def rel_path(path, root="."):
    """绝对路径 -> 相对项目根（跨盘符时退回原路径，正斜杠）。"""
    text = str(path or "").strip()
    if not text:
        return ""
    if root:
        try:
            text = os.path.relpath(text, str(root))
        except ValueError:
            pass
    return text.replace("\\", "/")


def language_of(path):
    return _LANG.get(os.path.splitext(str(path or ""))[1].lower(), "")


def _truncate(text, limit):
    text = str(text or "")
    limit = max(200, int(limit or 0))
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def selection_block(path, root=".", text="", line=0,
                    max_chars=MAX_SELECTION_CHARS):
    """选区片段：``文件:行`` 头 + 代码块（与 47.3 的引用格式一致）。"""
    body = str(text or "").strip("\n")
    if not body.strip():
        return ""
    body, cut = _truncate(body, max_chars)
    rel = rel_path(path, root) or "未保存"
    start = max(1, int(line or 1))
    head = "片段 %s:%d%s" % (rel, start, "（已截断）" if cut else "")
    lang = language_of(path)
    return "%s\n```%s\n%s\n```" % (head, lang, body)


def file_block(path, root=".", max_chars=MAX_FILE_CHARS):
    """读整个文件并压成上下文；失败返回 ``{"ok": False, "error": ...}``。"""
    target = str(path or "")
    if not target or not os.path.isfile(target):
        return {"ok": False, "error": "文件不存在", "text": ""}
    try:
        with open(target, encoding="utf-8", errors="replace") as fp:
            raw = fp.read()
    except OSError as e:
        _x6_swallowed(__name__, e, "read context file")
        return {"ok": False, "error": "读取失败: " + str(e)[:80], "text": ""}
    body, cut = _truncate(raw, max_chars)
    rel = rel_path(target, root)
    head = "文件 %s%s" % (rel, "（已截断）" if cut else "")
    lang = language_of(target)
    return {"ok": True, "error": "", "text": "%s\n```%s\n%s\n```"
            % (head, lang, body), "chars": len(raw)}


def file_text_block(path, root=".", text="", max_chars=MAX_FILE_CHARS):
    """用编辑器里的**当前文本**拼块（未保存的改动也能发给模型）。"""
    body = str(text or "")
    if not body.strip():
        return file_block(path, root, max_chars).get("text") or ""
    body, cut = _truncate(body, max_chars)
    rel = rel_path(path, root) or "未保存"
    head = "文件 %s%s" % (rel, "（已截断）" if cut else "")
    return "%s\n```%s\n%s\n```" % (head, language_of(path), body)


def context_block(file_path=None, root=".", selection="", line=0,
                  max_chars=MAX_FILE_CHARS):
    """组合：有选区就只带选区，否则带整个文件；都没有返回空串。"""
    if selection and str(selection).strip():
        return selection_block(file_path, root, selection, line)
    if file_path:
        return file_block(file_path, root, max_chars).get("text") or ""
    return ""


def prompt_with_context(goal, context=""):
    """把上下文放到用户目标前面：模型先看到代码，再看要求。"""
    goal = str(goal or "").strip()
    context = str(context or "").strip()
    if not context:
        return goal
    if not goal:
        return context + "\n\n请阅读上面的代码。"
    return context + "\n\n我的需求：" + goal
