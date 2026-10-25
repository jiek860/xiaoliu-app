# -*- coding: utf-8 -*-
"""Markdown 渲染：代码高亮、粗体、行内代码、标题、列表"""
import re
import html

_KEYWORDS = (
    r'\b(def|class|return|if|else|elif|for|while|import|from|as|try|except|finally|'
    r'with|in|not|and|or|None|True|False|lambda|pass|break|continue|raise|yield|'
    r'global|nonlocal|assert|del|is|async|await|function|var|let|const|new|this|'
    r'public|private|static|void|int|float|print|self)\b'
)


class MarkdownRenderer:
    """无状态渲染器；每次渲染重置 _codes"""
    def __init__(self):
        self._codes = []

    @property
    def codes(self):
        return self._codes

    def render(self, text: str) -> str:
        self._codes = []
        text = str(text or "")
        # 流式输出时围栏可能还没闭合：先补一个结束围栏，
        # 避免半截代码块以一堆反引号的形式堆在气泡里。
        if text.count("```") % 2 == 1:
            text += "\n```"
        parts = re.split(r'```(\w*)\n(.*?)```', text, flags=re.DOTALL)
        out = []
        lang = "text"
        code_idx = 0
        for i, part in enumerate(parts):
            if i % 3 == 1:
                lang = part or "text"
            elif i % 3 == 2:
                code = part.rstrip()
                self._codes.append(code)
                idx = code_idx
                code_idx += 1
                out.append(self._render_code_block(code, lang, idx))
            else:
                out.append(self._render_text(part))
        return "".join(out)

    def _render_code_block(self, code: str, lang: str, idx: int) -> str:
        esc = "\n".join(self._hl_line(ln) for ln in code.split("\n"))
        return (
            '<div style="background-color:#1e1e2e;color:#d4d4d4;padding:10px;'
            'margin:6px 0;border-left:3px solid #4a9eff">'
            '<div style="color:#888888;margin-bottom:4px">'
            f'<span>{lang}</span> '
            f'<a href="copy_{idx}" style="color:#4a9eff;text-decoration:none">[复制]</a>'
            '</div><pre style="margin:0;color:#d4d4d4;white-space:pre-wrap">'
            + esc + '</pre></div>'
        )

    def _hl_line(self, line: str) -> str:
        if "#" in line:
            hp = line.find("#")
            seg_code, seg_cmt = line[:hp], line[hp:]
        else:
            seg_code, seg_cmt = line, ""
        seg_code = html.escape(seg_code)
        seg_code = re.sub(_KEYWORDS, r'<span style="color:#c586c0">\1</span>', seg_code)
        if seg_cmt:
            seg_code += '<span style="color:#6a9955">' + html.escape(seg_cmt) + '</span>'
        return seg_code

    def _render_text(self, part: str) -> str:
        lines = part.split("\n")
        buf = []
        for ln in lines:
            if ln.startswith("### "):
                buf.append('<div style="font-weight:600;margin-top:6px">' + self._inline(ln[4:]) + '</div>')
            elif ln.startswith("## "):
                buf.append('<div style="font-weight:700;font-size:15px;margin-top:8px">' + self._inline(ln[3:]) + '</div>')
            elif ln.startswith("# "):
                buf.append('<div style="font-weight:700;font-size:17px;margin-top:10px">' + self._inline(ln[2:]) + '</div>')
            elif ln.startswith("- ") or ln.startswith("* "):
                buf.append('<div style="margin-left:14px">&bull; ' + self._inline(ln[2:]) + '</div>')
            elif ln.strip():
                buf.append(self._inline(ln))
        return "<br>".join(buf)

    def _inline(self, x: str) -> str:
        x = html.escape(x)
        x = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', x)
        x = re.sub(
            r'`([^`]+)`',
            r'<code style="background:#eee;padding:1px 4px;border-radius:3px">\1</code>',
            x,
        )
        return x
