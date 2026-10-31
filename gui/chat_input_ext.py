# -*- coding: utf-8 -*-
"""聊天输入扩展：拖文件进输入框、Ctrl+V 粘贴截图、按文档类型解析。

为什么单独成文件
----------------
`build_ui` / `lifecycle_mixin` 都是布局与窗口生命周期代码，已经接近行数上限；
文件解析（PDF/Word/Excel/PPT/MD/HTML）与图片落盘是可单独测的纯逻辑，放这里。

连线原则：能解析的就解析成文字放进输入框（用户确认后随消息一起发给模型），
解析不了的文件明确报错，不再出现"拖进来什么都没发生"。
"""
from __future__ import annotations

import os
from datetime import datetime

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None

SUPPORTED_EXTS = {
    ".txt", ".md", ".log", ".csv", ".json", ".yaml", ".yml",
    ".html", ".htm", ".pdf", ".docx", ".xlsx", ".xlsm", ".pptx",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif",
              ".tiff"}
MAX_DOC_CHARS = 4000


def is_image(path):
    return os.path.splitext(str(path or ""))[1].lower() in IMAGE_EXTS


def is_supported(path):
    ext = os.path.splitext(str(path or ""))[1].lower()
    return ext in SUPPORTED_EXTS or ext in IMAGE_EXTS


def document_text(path, max_chars=MAX_DOC_CHARS, trunk=None):
    """解析文档并压成可发送文本；失败返回 ``{"ok": False, "error": ...}``。

    trunk 传进来时，图片/扫描件在本地 OCR 不可用（或没认出字）后
    会走模块里的云端 OCR 兜底。
    """
    from core.document_parser import parse
    result = parse(path, trunk=trunk)
    if not result.get("ok") and not result.get("skipped"):
        # 文件刚复制完/被杀软占用时第一次常失败，重试一次再报错
        result = parse(path, trunk=trunk)
    if not result.get("ok"):
        return {"ok": False, "text": "",
                "error": str(result.get("error") or "解析失败")}
    text = str(result.get("text") or "").strip()
    if not text:
        return {"ok": False, "text": "", "error": "文件里没有可提取的文字"}
    limit = max(200, int(max_chars or 0))
    cut = len(text) > limit
    body = text[:limit]
    head = "📄 文件: %s（%d 字%s）" % (
        os.path.basename(str(path)), int(result.get("chars") or len(text)),
        "，已截断" if cut else "")
    return {"ok": True, "text": head + "\n" + body, "error": ""}


def insert_into_input(win, text):
    """把文字追加到聊天输入框（QTextEdit / QLineEdit 都兼容）。"""
    widget = getattr(win, "input", None)
    if widget is None or not str(text or "").strip():
        return False
    try:
        if hasattr(widget, "toPlainText"):
            cur = widget.toPlainText()
            sep = "\n" if cur.strip() else ""
            widget.setPlainText(cur + sep + str(text))
        else:
            cur = widget.text()
            sep = " " if cur.strip() else ""
            widget.setText(cur + sep + str(text))
        widget.setFocus()
        return True
    except Exception as e:  # 静默是故意的 - 输入框异常不该影响聊天
        _x6_swallowed(__name__, e, "insert attachment text")
        return False


def attach_document(win, path):
    """读取文档并把内容放进输入框；返回是否成功。"""
    result = document_text(path, trunk=getattr(win, "trunk", None))
    if not result.get("ok"):
        _say(win, "⚠️ 读取失败：%s（%s）" % (
            os.path.basename(str(path)), result.get("error")))
        return False
    if not insert_into_input(win, result["text"]):
        return False
    _say(win, "📎 已读取 %s，内容已放进输入框，发送即可" %
         os.path.basename(str(path)))
    return True


def attach_image(win, path):
    """把图片交给已有的 multimodal 入口（没有就只提示路径）。"""
    path = str(path or "")
    if not os.path.isfile(path):
        return False
    upload = getattr(win, "upload_image", None)
    if callable(upload):
        try:
            upload(path)
            return True
        except Exception as e:  # 静默是故意的 - 退回下面的提示路径
            _x6_swallowed(__name__, e, "attach image")
    insert_into_input(win, "（图片：%s）" % path)
    _say(win, "🖼 已加入图片：%s" % os.path.basename(path))
    return True


def attach_paths(win, paths):
    """批量接入拖进来的文件，返回成功数量。"""
    done = 0
    for path in paths or []:
        path = str(path or "")
        if not os.path.isfile(path):
            continue
        if is_image(path):
            done += 1 if attach_image(win, path) else 0
        elif is_supported(path):
            done += 1 if attach_document(win, path) else 0
        else:
            _say(win, "⚠️ 暂不支持这个文件类型：%s" %
                 os.path.basename(path))
    return done


def save_clipboard_image(win):
    """把剪贴板里的图片存到 data/paste_images/，返回路径（没有图片返回空）。"""
    try:
        image = QApplication.clipboard().image()
        if image is None or image.isNull():
            return ""
        base = str(getattr(win, "base", "") or os.getcwd())
        folder = os.path.join(base, "data", "paste_images")
        os.makedirs(folder, exist_ok=True)
        name = "paste_%s.png" % datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(folder, name)
        if not image.save(path, "PNG"):
            return ""
        return path
    except Exception as e:  # 静默是故意的 - 粘贴失败退回普通粘贴
        _x6_swallowed(__name__, e, "save clipboard image")
        return ""


def handle_paste_image(win):
    """Ctrl+V 时若剪贴板是图片则落盘并接入；返回是否消费了这次粘贴。"""
    mime = QApplication.clipboard().mimeData()
    if mime is None or not mime.hasImage():
        return False
    if mime.hasUrls() or mime.hasText():
        return False
    path = save_clipboard_image(win)
    if not path:
        return False
    return bool(attach_image(win, path))


def _say(win, text):
    chat = getattr(win, "chat", None)
    if chat is None:
        return
    try:
        if hasattr(chat, "append_system"):
            chat.append_system(str(text))
        else:
            chat.append(str(text))
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "chat notice")


class InputFilter(QObject):
    """输入框事件过滤器：拖拽文件 + Ctrl+V 图片。"""

    def __init__(self, win, parent=None):
        super().__init__(parent if isinstance(parent, QObject) else None)
        self.win = win

    def eventFilter(self, obj, event):
        if obj is getattr(self.win, "input", None):
            kind = event.type()
            if kind == QEvent.DragEnter:
                urls = event.mimeData().urls() if event.mimeData() else []
                if any(is_supported(u.toLocalFile()) for u in urls):
                    event.acceptProposedAction()
                    return True
            elif kind == QEvent.Drop:
                urls = event.mimeData().urls() if event.mimeData() else []
                attach_paths(self.win, [u.toLocalFile() for u in urls])
                event.acceptProposedAction()
                return True
            elif kind == QEvent.KeyPress:
                if event.matches(QKeySequence.Paste) and \
                        handle_paste_image(self.win):
                    return True
        return False


def install(win):
    """给输入框挂扩展（保留原有 Enter 发送事件过滤器）。"""
    if getattr(win, "_chat_input_filter", None) is not None:
        return win._chat_input_filter
    widget = getattr(win, "input", None)
    if widget is None:
        return None
    widget.setAcceptDrops(True)
    widget.setToolTip("可直接拖入 PDF / Word / Excel / PPT / MD 文件；"
                      "Ctrl+V 可粘贴截图")
    flt = InputFilter(win, widget)
    widget.installEventFilter(flt)
    win._chat_input_filter = flt
    return flt
