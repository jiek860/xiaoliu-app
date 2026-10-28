# -*- coding: utf-8 -*-
"""PyInstaller 产物检查器：exe、Qt 插件、能力文件与敏感文件。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools.check_pyinstaller_output import validate_dist  # noqa: E402

# 与 tools/check_pyinstaller_output.py 的 CAPABILITY_FILES 一一对应
_CAPABILITY_PATHS = (
    "PIL/_imaging.cp312-win_amd64.pyd",
    "win32/win32gui.pyd",
    "win32/win32api.pyd",
    "pywin32_system32/pywintypes312.dll",
    "uiautomation/bin/UIAutomationClient_VC140_X64.dll",
    "docx/templates/default-docx-template/[Content_Types].xml",
)


def _fake_dist(root, with_forbidden=False):
    dist = root / "小6智能体"
    internal = dist / "_internal"
    (internal / "PyQt5" / "Qt5" / "bin").mkdir(parents=True)
    (internal / "PyQt5" / "Qt5" / "plugins" / "platforms").mkdir(parents=True)
    exe = dist / "小6智能体.exe"
    with open(exe, "wb") as f:
        f.truncate(6 * 1024 * 1024)
    (internal / "PyQt5" / "Qt5" / "bin" / "Qt5Core.dll").write_bytes(b"x")
    (internal / "PyQt5" / "Qt5" / "plugins" / "platforms" / "qwindows.dll").write_bytes(b"x")
    # 口径 A（exe 保留电脑控制/Word）要验证的能力文件
    for rel in _CAPABILITY_PATHS:
        target = internal / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    if with_forbidden:
        (dist / "config.json").write_text("{}", encoding="utf-8")
        (dist / "私钥.pem").write_text("secret", encoding="utf-8")
    return root


def test_valid_fake_distribution(tmp_path):
    ok, errors, info = validate_dist(_fake_dist(tmp_path))
    assert ok, errors
    assert info["qt_core"] == 1
    assert info["qwindows"] == 1
    assert info["capabilities"].endswith("/%d" % len(_CAPABILITY_PATHS))


def test_forbidden_files_are_reported(tmp_path):
    ok, errors, _info = validate_dist(_fake_dist(tmp_path, with_forbidden=True))
    assert ok is False
    assert any("config.json" in e for e in errors)
    assert any("私钥" in e for e in errors)


def test_missing_pillow_extension_is_reported(tmp_path):
    """Pillow 被 excludes 排掉时（2026-10-27 的真实事故）必须报错

    少了 PIL 的编译扩展，exe 里截图/图像对比/目标框标注全废，
    而且 core/computer_verifier 会把异常吞成"没变化"。
    """
    root = _fake_dist(tmp_path)
    internal = root / "小6智能体" / "_internal"
    (internal / "PIL" / "Image.py").write_bytes(b"x")
    next(p for p in internal.rglob("_imaging*.pyd")).unlink()
    ok, errors, _info = validate_dist(root)
    assert ok is False
    assert any("Pillow" in e for e in errors)


def test_missing_uiautomation_dll_is_reported(tmp_path):
    """datas 元组顺序写反时 dll 会静默丢失（2026-10-28 的真实事故）"""
    root = _fake_dist(tmp_path)
    internal = root / "小6智能体" / "_internal"
    (internal / "uiautomation" / "bin"
     / "UIAutomationClient_VC140_X64.dll").unlink()
    ok, errors, _info = validate_dist(root)
    assert ok is False
    assert any("uiautomation" in e for e in errors)
