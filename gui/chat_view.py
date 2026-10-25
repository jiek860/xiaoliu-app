# -*- coding: utf-8 -*-
"""聊天视图：气泡渲染、群聊分段、系统通知（v2 - 修复 _trim_old_messages 缺失）"""
import re
from datetime import datetime
from PyQt5.QtCore import pyqtSignal
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

    def append_user(self, text: str):
        try:
            self._trim_old_messages()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
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
        except Exception as e:  # 静默是故意的
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

    def load_history(self, msgs):
        try:
            self.clear()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
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
            except Exception:  # 静默是故意的
                continue

    def render_reply(self, text: str, fallback_name: str = "小6"):
        try:
            segs = self.split_group(str(text))
            if segs:
                for nm, body in segs:
                    self.append_bubble(nm, self._md.render(body))
            else:
                self.append_bubble(fallback_name, self._md.render(text))
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
                           "task-budget://")):
            try:
                self.actionRequested.emit(u)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
        elif u.startswith("copy://"):
            from PyQt5.QtWidgets import QApplication
            if self._last_reply_text:
                QApplication.clipboard().setText(self._last_reply_text)
