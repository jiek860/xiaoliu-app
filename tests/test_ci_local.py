# -*- coding: utf-8 -*-
"""本地 CI 记录落盘（scripts/ci_local.py）单元测试。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from scripts import ci_local  # noqa: E402


def test_write_record_creates_section_once(tmp_path, monkeypatch):
    target = tmp_path / "doc.md"
    target.write_text("# 手册\n", encoding="utf-8")
    monkeypatch.setattr(ci_local, "RECORD", str(target))

    assert ci_local._write_record([("语法编译", True)], 1, 1, 12.5)
    text = target.read_text(encoding="utf-8")
    assert ci_local.RECORD_SECTION in text
    assert "✅ 全过" in text

    assert ci_local._write_record([("语法编译", False)], 0, 1, 3.0)
    text = target.read_text(encoding="utf-8")
    assert text.count(ci_local.RECORD_SECTION) == 1
    assert "❌ 有失败" in text and "语法编译" in text


def test_write_record_creates_missing_file(tmp_path, monkeypatch):
    target = tmp_path / "sub" / "doc.md"
    monkeypatch.setattr(ci_local, "RECORD", str(target))
    assert ci_local._write_record([("版本号", True)], 1, 1, 1.0)
    text = target.read_text(encoding="utf-8")
    assert "本地定时 CI 运行记录" in text and ci_local.RECORD_SECTION in text


def test_write_record_reports_oserror(tmp_path, monkeypatch):
    target = tmp_path / "doc.md"
    target.write_text("# 手册\n", encoding="utf-8")
    monkeypatch.setattr(ci_local, "RECORD", str(target))

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(ci_local, "open", boom, raising=False)
    assert ci_local._write_record([("语法编译", True)], 1, 1, 1.0) is False
