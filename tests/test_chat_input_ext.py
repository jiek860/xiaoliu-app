# -*- coding: utf-8 -*-
"""聊天输入扩展：文档解析、附件进输入框、图片/剪贴板接线。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pytest

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QTextEdit  # noqa: E402

from gui import chat_input_ext as ext  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeChat:
    def __init__(self):
        self.system = []

    def append_system(self, text):
        self.system.append(text)


class _FakeWin:
    def __init__(self):
        self.base = BASE
        self.input = QTextEdit()
        self.chat = _FakeChat()
        self.image_calls = []

    def upload_image(self, path=None):
        self.image_calls.append(path)


def test_is_supported_and_is_image():
    assert ext.is_supported("a.pdf") and ext.is_supported("a.docx")
    assert ext.is_supported("a.PNG")
    assert not ext.is_supported("a.exe")
    assert ext.is_image("a.jpg") and not ext.is_image("a.pdf")


def test_document_text_reads_markdown(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("# 标题\n\n正文内容", encoding="utf-8")
    r = ext.document_text(str(f))
    assert r["ok"] is True
    assert "note.md" in r["text"] and "正文内容" in r["text"]


def test_document_text_reports_unsupported(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"\x00\x01")
    r = ext.document_text(str(f))
    assert r["ok"] is False and r["error"]


def test_attach_document_puts_text_in_input(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    win = _FakeWin()
    assert ext.attach_document(win, str(f)) is True
    assert "hello" in win.input.toPlainText()
    assert win.chat.system and "已读取" in win.chat.system[0]


def test_attach_document_failure_keeps_chat_notice(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"\x00")
    win = _FakeWin()
    assert ext.attach_document(win, str(f)) is False
    assert "读取失败" in win.chat.system[0]


def test_attach_image_uses_upload_image(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG")
    win = _FakeWin()
    assert ext.attach_image(win, str(f)) is True
    assert win.image_calls == [str(f)]


def test_attach_paths_mixes_docs_and_images(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("x", encoding="utf-8")
    img = tmp_path / "b.png"
    img.write_bytes(b"\x89PNG")
    bad = tmp_path / "c.exe"
    bad.write_bytes(b"")
    win = _FakeWin()
    assert ext.attach_paths(win, [str(doc), str(img), str(bad), "", "/nope"]) == 2
    assert any("暂不支持" in s for s in win.chat.system)


def test_insert_into_input_supports_line_edit():
    from PyQt5.QtWidgets import QLineEdit
    win = _FakeWin()
    win.input = QLineEdit()
    assert ext.insert_into_input(win, "abc") is True
    assert win.input.text() == "abc"
    assert ext.insert_into_input(win, "def") is True
    assert win.input.text() == "abc def"


def test_save_clipboard_image_without_image_returns_empty(monkeypatch):
    class _Clip:
        def image(self):
            class _I:
                def isNull(self):
                    return True
            return _I()

    monkeypatch.setattr(ext.QApplication, "clipboard",
                        staticmethod(lambda: _Clip()))
    assert ext.save_clipboard_image(_FakeWin()) == ""


def test_handle_paste_image_without_image_is_false(monkeypatch):
    class _Mime:
        def hasImage(self):
            return False

    class _Clip:
        def mimeData(self):
            return _Mime()

    monkeypatch.setattr(ext.QApplication, "clipboard",
                        staticmethod(lambda: _Clip()))
    assert ext.handle_paste_image(_FakeWin()) is False


def test_install_is_idempotent():
    win = _FakeWin()
    first = ext.install(win)
    assert first is not None
    assert ext.install(win) is first


def test_document_text_reports_empty_file(tmp_path):
    """空文件不再静默返回 ok：调用方要知道"没文字"而不是以为解析成功。"""
    f = tmp_path / "empty.md"
    f.write_text("   \n", encoding="utf-8")
    r = ext.document_text(str(f))
    assert r["ok"] is False and "没有可提取" in r["error"]


def test_document_text_falls_back_to_cloud_ocr(tmp_path, monkeypatch):
    """本地 OCR 依赖缺失时，走模块里的云端 OCR 兜底。"""
    import sys
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    class _Ocr:
        def recognize(self, path):
            return {"文字": "截图上的字"}

    class _Trunk:
        modules = {"image_ocr": _Ocr()}

    r = ext.document_text(str(png), trunk=_Trunk())
    assert r["ok"] is True and "截图上的字" in r["text"]
