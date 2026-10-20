# -*- coding: utf-8 -*-
"""PyInstaller 产物检查器：exe、Qt 插件和敏感文件。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools.check_pyinstaller_output import validate_dist  # noqa: E402


def _fake_dist(root, with_forbidden=False):
    dist = root / "小6智能体"
    (dist / "_internal" / "PyQt5" / "Qt5" / "bin").mkdir(parents=True)
    (dist / "_internal" / "PyQt5" / "Qt5" / "plugins" / "platforms").mkdir(parents=True)
    exe = dist / "小6智能体.exe"
    with open(exe, "wb") as f:
        f.truncate(6 * 1024 * 1024)
    (dist / "_internal" / "PyQt5" / "Qt5" / "bin" / "Qt5Core.dll").write_bytes(b"x")
    (dist / "_internal" / "PyQt5" / "Qt5" / "plugins" / "platforms" / "qwindows.dll").write_bytes(b"x")
    if with_forbidden:
        (dist / "config.json").write_text("{}", encoding="utf-8")
        (dist / "私钥.pem").write_text("secret", encoding="utf-8")
    return root


def test_valid_fake_distribution(tmp_path):
    ok, errors, info = validate_dist(_fake_dist(tmp_path))
    assert ok, errors
    assert info["qt_core"] == 1
    assert info["qwindows"] == 1


def test_forbidden_files_are_reported(tmp_path):
    ok, errors, _info = validate_dist(_fake_dist(tmp_path, with_forbidden=True))
    assert ok is False
    assert any("config.json" in e for e in errors)
    assert any("私钥" in e for e in errors)