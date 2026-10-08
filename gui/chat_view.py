# -*- coding: utf-8 -*-
"""聊天视图：气泡渲染、群聊分段、系统通知（v2 - 修复 _trim_old_messages 缺失）"""
import os
import re
from datetime import datetime
from PyQt5.QtWidgets import QTextBrowser
from PyQt5.QtCore import Qt
from gui.markdown_renderer import MarkdownRenderer

GROUP_COLORS = {
    "小6": "#9b59b6",
    "小七": "#e74c3c",
    "小八": "#3498db",
    "小九": "#2ecc71",
}

MAX_BLOCKS = 600


class ChatView(QTextBrowser):
    def __init__(self, parent=None, base_dir: str = "."):
        super().__init__(parent)
        self.base_dir = base_dir
        self._md = MarkdownRenderer()
        self._last_codes = []
        self._last_reply_text = ""
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_anchor)
        self.setStyleSheet(
            "font-size:14px;background-color:#f5f5f5;border:none;"
            "border-radius:8px;padding:10px;"
        )
        try:
            self.document().setMaximumBlockCount(MAX_BLOCKS)
        except Exception:
            pass

    def _trim_old_messages(self, max_blocks=MAX_BLOCKS):
        try:
            doc = self.document()
            n = doc.blockCount()
            if n <= max_blocks:
                return
            cur = self.textCursor()
            cur.movePosition(cur.Start)
            cur.movePosition(cur.Down, cur.KeepAnchor, n - max_blocks)
            cur.removeSelectedText()
        except Exception:
            pass

    def append_user(self, text: str):
        try:
            self._trim_old_messages()
        except Exception:
            pass
        try:
            import html as _h
            _time = datetime.now().strftime("%H:%M")
            self.append(
                '<div style="text-align:right;margin:10px 0;">'
                '<span style="background:#4a9eff;color:#fff;padding:8px 14px;'
                'border-radius:14px 14px 4px 14px;">'
                + _h.escape(text) +
                '</span>'
                '<div style="color:#aaa;font-size:10px;margin-top:2px;">'
                + _time + '</div></div>'
            )
        except Exception as e:
            from core.logger import get_logger
            get_logger().error("append_user 失败: %s" % e)

    def append_bubble(self, name: str, body_html: str):
        try:
            _time = datetime.now().strftime("%H:%M")
            c = GROUP_COLORS.get(name, "#1a1a2e")
            head = (
                '<div style="margin:12px 0;">'
                '<div style="margin-bottom:4px;">'
                f'<span style="font-size:13px;color:{c};font-weight:bold;">{name}</span>'
                f'<span style="font-size:10px;color:#aaa;margin-left:8px;">{_time}</span>'
                '</div>'
                '<div style="background-color:#f5f5f5;padding:10px 14px;'
                'border-radius:4px 14px 14px 14px;max-width:80%;display:inline-block;">'
            )
            self.append(head + body_html + '</div></div>')
        except Exception as e:
            from core.logger import get_logger
            get_logger().error("append_bubble 失败: %s" % e)

    def append_thinking(self) -> int:
        try:
            self.append('<div style="color:#888;font-style:italic">... 正在思考 ...</div>')
            return self.document().lastBlock().position()
        except Exception:
            try:
                return len(self.toPlainText())
            except Exception:
                return 0

    def remove_from_anchor(self, anchor: int):
        try:
            cur = self.textCursor()
            cur.setPosition(anchor)
            cur.movePosition(cur.End, cur.KeepAnchor)
            cur.removeSelectedText()
        except Exception:
            pass

    @staticmethod
    def split_group(text: str):
        ms = list(re.finditer(r"【(小6|小七|小八|小九)】\s*", text))
        if not ms:
            return None
        segs = []
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
            body = text[m.end():end].strip()
            if body:
                segs.append((m.group(1), body))
        return segs or None

    def load_history(self, msgs):
        try:
            self.clear()
        except Exception:
            pass
        if not msgs:
            return
        for m in msgs:
            try:
                if not isinstance(m, dict):
                    continue
                role = str(m.get("role", ""))
                text = str(m.get("text", ""))
                if not text:
                    continue
                if role in ("u", "user"):
                    self.append_user(text)
                elif role in ("a", "assistant"):
                    self.render_reply(text, fallback_name="小6")
                else:
                    self.append(text)
            except Exception:
                continue

    def render_reply(self, text: str, fallback_name: str = "小6"):
        try:
            segs = self.split_group(str(text))
            if segs:
                for nm, body in segs:
                    self.append_bubble(nm, self._md.render(body))
            else:
                self.append_bubble(fallback_name, self._md.render(text))
        except Exception as e:
            from core.logger import get_logger
            get_logger().error("render_reply 失败: %s" % e)
            try:
                self.append(f'<b style="color:#1a1a2e">{fallback_name}:</b><br>{text}<br>')
            except Exception:
                pass
        self._last_codes = self._md.codes
        self._last_reply_text = text

    def _on_anchor(self, url):
        u = url.toString()
        if u.startswith("copy_"):
            try:
                idx = int(u.split("copy_")[1])
                if 0 <= idx < len(self._last_codes):
                    from PyQt5.QtWidgets import QApplication
                    QApplication.clipboard().setText(self._last_codes[idx])
                    self.append('<div style="color:#52c41a;font-size:11px">代码已复制</div>')
            except Exception:
                pass
        elif u.startswith("copy://"):
            from PyQt5.QtWidgets import QApplication
            if self._last_reply_text:
                QApplication.clipboard().setText(self._last_reply_text)
