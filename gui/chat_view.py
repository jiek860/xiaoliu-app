# -*- coding: utf-8 -*-
"""聊天视图：气泡渲染、群聊分段、系统通知（v2 - 修复 _trim_old_messages 缺失）"""
import re
from datetime import datetime
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QTextBrowser
from gui.markdown_renderer import MarkdownRenderer

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


GROUP_COLORS = {
    "小6": "#9b59b6",
    "小七": "#e74c3c",
    "小八": "#3498db",
    "小九": "#2ecc71",
}

MAX_BLOCKS = 600
OLDER_LINK_TEXT = "↑ 加载更早的消息"


class ChatView(QTextBrowser):
    # 任务结果卡片 / 引导卡片里的链接统一发出去，由主窗口决定打开哪个页面。
    actionRequested = pyqtSignal(str)

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
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

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
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    @staticmethod
    def _fmt_time(ts=None) -> str:
        """历史消息优先显示原始时间；没有时间戳时退回当前时刻。"""
        try:
            if ts:
                return datetime.fromtimestamp(float(ts)).strftime("%H:%M")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "format history time")
        return datetime.now().strftime("%H:%M")

    def _user_block_html(self, text: str, ts=None) -> str:
        import html as _h
        return (
            '<div style="text-align:right;margin:10px 0;">'
            '<span style="background:#4a9eff;color:#fff;padding:8px 14px;'
            'border-radius:14px 14px 4px 14px;">'
            + _h.escape(str(text or "")) +
            '</span>'
            '<div style="color:#aaa;font-size:10px;margin-top:2px;">'
            + self._fmt_time(ts) + '</div></div>'
        )

    def _bubble_block_html(self, name: str, body_html: str, ts=None) -> str:
        c = GROUP_COLORS.get(name, "#1a1a2e")
        head = (
            '<div style="margin:12px 0;">'
            '<div style="margin-bottom:4px;">'
            f'<span style="font-size:13px;color:{c};font-weight:bold;">{name}</span>'
            f'<span style="font-size:10px;color:#aaa;margin-left:8px;">'
            f'{self._fmt_time(ts)}</span>'
            '</div>'
            '<div style="background-color:#f5f5f5;padding:10px 14px;'
            'border-radius:4px 14px 14px 14px;max-width:80%;display:inline-block;">'
        )
        return head + body_html + '</div></div>'

    def _older_link_html(self) -> str:
        return ('<div style="text-align:center;margin:8px 0;">'
                '<a href="history://older" style="color:#1976d2;'
                'font-size:12px;">' + OLDER_LINK_TEXT + '</a></div>')

    def append_user(self, text: str, ts=None):
        try:
            self._trim_old_messages()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            self.append(self._user_block_html(text, ts))
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("append_user 失败: %s" % e)

    def append_bubble(self, name: str, body_html: str, ts=None):
        try:
            self.append(self._bubble_block_html(name, body_html, ts))
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("append_bubble 失败: %s" % e)

    def append_thinking(self) -> int:
        try:
            self.append('<div style="color:#888;font-style:italic">... 正在思考 ...</div>')
            return self.document().lastBlock().position()
        except Exception:  # 静默是故意的
            try:
                return len(self.toPlainText())
            except Exception:  # 静默是故意的
                return 0

    def stream_render(self, anchor, text: str, fallback_name: str = "小6") -> int:
        """重绘流式气泡，返回这一帧的锚点（供下一次替换）。

        先删掉上一帧再整体渲染：流式过程中就能看到 Markdown 排版，
        结束时也不会从纯文本突然跳成另一种样子。
        """
        try:
            if anchor is not None:
                self.remove_from_anchor(anchor)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        cur = self.textCursor()
        cur.movePosition(cur.End)
        pos = cur.position()
        self.append_bubble(fallback_name, self._md.render(str(text or "")))
        self._last_codes = self._md.codes
        self._last_reply_text = str(text or "")
        return pos

    def at_bottom(self, tolerance: int = 24) -> bool:
        """视口是否贴着底部（流式时用来判断该不该自动跟随）"""
        try:
            sb = self.verticalScrollBar()
            return sb.value() >= sb.maximum() - max(0, int(tolerance))
        except Exception:  # 静默是故意的
            return True

    def scroll_to_bottom(self):
        try:
            sb = self.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def append_system(self, text: str):
        """轻量系统提示（居中灰字），不占气泡、不打断阅读"""
        try:
            import html as _h
            self.append('<div style="color:#999;font-size:12px;text-align:center;'
                        'margin:8px 0;">' + _h.escape(str(text)) + '</div>')
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def append_plain(self, name: str, text: str):
        """纯文本气泡（中断回复时用，避免渲染半截 Markdown 失败）"""
        try:
            import html as _h
            body = _h.escape(str(text or "")).replace("\n", "<br>")
            self.append_bubble(name, body)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def remove_from_anchor(self, anchor: int):
        try:
            cur = self.textCursor()
            cur.setPosition(anchor)
            cur.movePosition(cur.End, cur.KeepAnchor)
            cur.removeSelectedText()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

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

    def _history_block_html(self, m) -> str:
        if not isinstance(m, dict):
            return ""
        role = str(m.get("role", ""))
        text = str(m.get("text", ""))
        if not text:
            return ""
        ts = m.get("ts")
        if role in ("u", "user"):
            return self._user_block_html(text, ts)
        if role in ("a", "assistant"):
            return self._bubble_block_html(
                "小6", self._md.render(text), ts)
        import html as _h
        return ('<div style="margin:8px 0;color:#666;font-size:12px;">'
                + _h.escape(text) + '</div>')

    def load_history(self, msgs, has_older=False):
        try:
            self.clear()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        if has_older:
            try:
                self.append(self._older_link_html())
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "append older link")
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
                ts = m.get("ts")
                if role in ("u", "user"):
                    self.append_user(text, ts)
                elif role in ("a", "assistant"):
                    self.render_reply(text, fallback_name="小6", ts=ts)
                else:
                    self.append(text)
            except Exception:  # 静默是故意的
                continue
        try:
            self.scroll_to_bottom()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "scroll to bottom")

    def _drop_empty_leading_blocks(self):
        """清掉顶部的空白段（insertHtml 前置空段会留一行空行）。"""
        doc = self.document()
        while doc.blockCount() > 1 and not doc.firstBlock().text().strip():
            cur = QTextCursor(doc)
            cur.movePosition(QTextCursor.Start)
            cur.deleteChar()

    def _remove_older_link(self):
        """移除"加载更早"提示所在的段落。"""
        doc = self.document()
        found = doc.find(OLDER_LINK_TEXT)
        if found.isNull():
            return
        block = found.block()
        cur = QTextCursor(doc)
        cur.setPosition(block.position())
        cur.select(QTextCursor.BlockUnderCursor)
        cur.removeSelectedText()
        cur.deleteChar()
        self._drop_empty_leading_blocks()

    def prepend_history(self, msgs, has_older=False):
        """把更早的一页插到顶部，并尽量保持当前阅读位置不跳。"""
        msgs = list(msgs or [])
        if not msgs and not has_older:
            return
        doc = self.document()
        sb = self.verticalScrollBar()
        max_blocks = 0
        try:
            max_blocks = int(doc.maximumBlockCount() or 0)
            # 上限开着时，插入头部会被 Qt 立刻从头部裁掉，先临时关掉
            if max_blocks > 0:
                doc.setMaximumBlockCount(0)
            old_value = sb.value()
            doc.adjustSize()
            old_height = doc.size().height()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "measure before prepend")
            old_value = 0
            old_height = 0
        try:
            self._remove_older_link()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "remove older link")
        html = "".join(self._history_block_html(m) for m in msgs)
        try:
            if html:
                cur = QTextCursor(doc)
                cur.movePosition(QTextCursor.Start)
                # 直接 insertHtml 会并进第一段，先插入空段落把它顶下去
                cur.insertBlock()
                cur.insertHtml(html)
            if has_older:
                cur = QTextCursor(doc)
                cur.movePosition(QTextCursor.Start)
                cur.insertBlock()
                cur.insertHtml(self._older_link_html())
            self._drop_empty_leading_blocks()
            if max_blocks > 0:
                # 超出上限时从尾部裁，保住用户正在往上看的更早内容
                excess = doc.blockCount() - max_blocks
                if excess > 0:
                    cut = doc.findBlockByNumber(max_blocks)
                    if cut.isValid():
                        tail = QTextCursor(doc)
                        tail.setPosition(cut.position())
                        tail.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
                        tail.removeSelectedText()
                doc.setMaximumBlockCount(max_blocks)
            doc.adjustSize()
            grown = doc.size().height() - old_height
            if grown > 0:
                sb.setValue(int(old_value + grown))
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("prepend_history 失败: %s" % e)

    def render_reply(self, text: str, fallback_name: str = "小6", ts=None):
        try:
            segs = self.split_group(str(text))
            if segs:
                for nm, body in segs:
                    self.append_bubble(nm, self._md.render(body), ts)
            else:
                self.append_bubble(fallback_name, self._md.render(text), ts)
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("render_reply 失败: %s" % e)
            try:
                self.append(f'<b style="color:#1a1a2e">{fallback_name}:</b><br>{text}<br>')
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
        self._last_codes = self._md.codes
        self._last_reply_text = text

    def append_task_result_card(self, task_id, status="completed", summary="",
                                error="", next_action="", action_label=""):
        """在聊天流里显示任务结果卡片 + 查看任务入口。

        QTextBrowser 的链接通过 actionRequested 抛给主窗口，避免聊天视图
        依赖 TaskCenterDialog / SecurityCenterDialog，保持组件解耦。
        """
        try:
            import html as _h
            ok = str(status) in ("completed", "done", "success")
            color = "#16a34a" if ok else "#dc2626"
            title = "任务完成" if ok else "任务失败"
            body = _h.escape(str(summary or error or ""))[:600]
            links = ['<a href="task://%s" style="color:#1976d2;">查看任务</a>'
                     % _h.escape(str(task_id))]
            if next_action:
                links.append('<a href="%s" style="color:#dc2626;">%s</a>'
                             % (_h.escape(str(next_action)),
                                _h.escape(action_label or "下一步")))
            self.append(
                '<div style="margin:10px 0;padding:12px;border:1px solid #e5e6eb;'
                'border-left:4px solid %s;border-radius:10px;background:#fff;">'
                '<div style="font-weight:700;color:%s;">%s</div>'
                '<div style="color:#475467;font-size:12px;margin:5px 0;">%s</div>'
                '<div style="font-size:12px;">%s</div></div>'
                % (color, color, title, body, " &nbsp; ".join(links)))
        except Exception as e:  # 静默是故意的
            from core.logger import get_logger
            get_logger().error("append_task_result_card 失败: %s" % e)

    def append_guidance_card(self, title, message, action, action_label):
        try:
            import html as _h
            self.append(
                '<div style="margin:8px 0;padding:10px 12px;border-radius:10px;'
                'background:#f0f7ff;border:1px solid #d6e8ff;">'
                '<b style="color:#1976d2;">%s</b> '
                '<span style="color:#475467;font-size:12px;">%s</span> '
                '<a href="%s" style="color:#dc2626;font-size:12px;">%s</a>'
                '</div>' % (_h.escape(str(title)), _h.escape(str(message)),
                            _h.escape(str(action)), _h.escape(str(action_label))))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _on_anchor(self, url):
        u = url.toString()
        if u.startswith("copy_"):
            try:
                idx = int(u.split("copy_")[1])
                if 0 <= idx < len(self._last_codes):
                    from PyQt5.QtWidgets import QApplication
                    QApplication.clipboard().setText(self._last_codes[idx])
                    self.append('<div style="color:#52c41a;font-size:11px">代码已复制</div>')
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
        elif u.startswith(("task://", "retry://", "settings://",
                           "plugins://", "security://", "guidance://",
                           "task-budget://", "history://")):
            try:
                self.actionRequested.emit(u)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
        elif u.startswith("copy://"):
            from PyQt5.QtWidgets import QApplication
            if self._last_reply_text:
                QApplication.clipboard().setText(self._last_reply_text)
