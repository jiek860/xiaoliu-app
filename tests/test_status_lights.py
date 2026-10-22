# -*- coding: utf-8 -*-
"""状态栏"本地/云端"指示灯测试（修复双绿 + 重启不恢复）。"""

import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.status_lights import (  # noqa: E402
    COLOR_OFF, COLOR_ON, MODE_CLOUD, MODE_LOCAL, is_cloud_mode, paint,
    paint_from_config,
)


class _W:
    def __init__(self):
        self.sheet = ""
        self.text = ""

    def setStyleSheet(self, v):
        self.sheet = v

    def setText(self, v):
        self.text = v

    @property
    def green(self):
        return COLOR_ON in self.sheet

    @property
    def grey(self):
        return COLOR_OFF in self.sheet


# ---------------- 模式判定 ----------------
def test_is_cloud_mode():
    assert is_cloud_mode("云端模型") is True
    assert is_cloud_mode("本地路由") is False
    assert is_cloud_mode("") is False
    assert is_cloud_mode(None) is False


# ---------------- 核心回归：不能双绿 ----------------
def test_local_mode_only_local_is_green():
    local, cloud = _W(), _W()
    paint(MODE_LOCAL, local, cloud)
    assert local.green is True
    assert cloud.green is False, "本地模式下云端灯不应是绿色（原 bug）"
    assert cloud.grey is True


def test_cloud_mode_only_cloud_is_green():
    local, cloud = _W(), _W()
    paint(MODE_CLOUD, local, cloud)
    assert cloud.green is True
    assert local.green is False, "云端模式下本地灯不应是绿色"
    assert local.grey is True


def test_never_both_green_for_any_mode():
    for mode in ("本地路由", "云端模型", "", None, "随便什么"):
        local, cloud = _W(), _W()
        paint(mode, local, cloud)
        assert not (local.green and cloud.green), "模式 %r 出现双绿" % (mode,)


def test_unknown_mode_falls_back_to_local():
    local, cloud = _W(), _W()
    r = paint("乱码", local, cloud)
    assert r["cloud"] is False
    assert local.green is True


# ---------------- 按钮与顶栏同步 ----------------
def test_button_and_label_follow_mode():
    local, cloud, btn, label = _W(), _W(), _W(), _W()
    paint(MODE_CLOUD, local, cloud, btn, label)
    assert "云端" in btn.text
    assert "云端" in label.text

    paint(MODE_LOCAL, local, cloud, btn, label)
    assert "本地路由" in btn.text
    assert "本地路由" in label.text


def test_none_widgets_are_tolerated():
    """控件没构建好（None）时不能崩。"""
    paint(MODE_CLOUD, None, None, None, None)
    paint(MODE_LOCAL, None, None, None, None)


# ---------------- 重启恢复 ----------------
class _Trunk:
    def __init__(self, mode):
        self.config = {"model_mode": mode}


class _Win:
    def __init__(self, mode):
        self._status_local = _W()
        self._status_cloud = _W()
        self.model_btn = _W()
        self.model_status_label = _W()
        self.trunk = _Trunk(mode)


def test_paint_from_config_restores_cloud():
    w = _Win(MODE_CLOUD)
    r = paint_from_config(w)
    assert r["cloud"] is True
    assert w._status_cloud.green is True
    assert w._status_local.green is False


def test_paint_from_config_restores_local():
    w = _Win(MODE_LOCAL)
    r = paint_from_config(w)
    assert r["cloud"] is False
    assert w._status_local.green is True


def test_paint_from_config_survives_broken_config():
    class Bad:
        @property
        def config(self):
            raise RuntimeError("config unavailable")

    w = _Win(MODE_LOCAL)
    w.trunk = Bad()
    r = paint_from_config(w)
    assert r["cloud"] is False      # 回退到本地


def test_paint_from_config_never_raises_without_widgets():
    class Bare:
        trunk = _Trunk(MODE_CLOUD)

    paint_from_config(Bare())       # 不抛异常即通过


# ---------------- 真控件（offscreen） ----------------
def test_real_qt_labels():
    pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])  # noqa: F841
    a, b = QLabel("本地"), QLabel("云端")
    paint(MODE_CLOUD, a, b)
    assert COLOR_ON in b.styleSheet()
    assert COLOR_OFF in a.styleSheet()
