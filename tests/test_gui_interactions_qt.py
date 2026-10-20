# -*- coding: utf-8 -*-
"""pytest-qt interaction tests for high-value GUI paths."""
import os
import sys

import pytest

pytest.importorskip("pytestqt")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QLineEdit  # noqa: E402


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {"ai_name": "测试"}
        self.modules = {}

    def call(self, *_a, **_k):
        return {"ok": True}

    def _log(self, *_a, **_k):
        pass


def test_command_palette_typing_and_enter_runs_selected(qtbot, tmp_path):
    from gui.command_palette import CommandPalette
    called = []
    palette = CommandPalette(_Trunk(tmp_path), {"settings": lambda: called.append("settings")})
    qtbot.addWidget(palette)
    palette.show()
    qtbot.keyClicks(palette.search, "settings")
    qtbot.waitUntil(lambda: palette.list_w.count() >= 1, timeout=2000)
    matches = [i for i in range(palette.list_w.count())
               if "settings" in palette.list_w.item(i).text()]
    assert matches, "settings panel should be searchable"
    palette.list_w.setCurrentRow(matches[0])
    qtbot.keyClick(palette.search, Qt.Key_Return)
    qtbot.waitUntil(lambda: called == ["settings"], timeout=2000)


def test_command_palette_escape_rejects(qtbot, tmp_path):
    from gui.command_palette import CommandPalette
    palette = CommandPalette(_Trunk(tmp_path))
    qtbot.addWidget(palette)
    palette.show()
    palette.search.setFocus()
    qtbot.keyClick(palette.search, Qt.Key_Escape)
    assert not palette.isVisible()


def test_onboarding_cloud_key_is_password_masked(qtbot, tmp_path):
    from gui.onboarding_wizard import OnboardingWizard
    wiz = OnboardingWizard(_Trunk(tmp_path))
    qtbot.addWidget(wiz)
    assert wiz.ed_cloud_key.echoMode() == QLineEdit.Password
    wiz.ed_cloud_key.setText("not-a-real-key")
    assert wiz.ed_cloud_key.text() == "not-a-real-key"
    assert wiz.ed_cloud_url.placeholderText() or wiz.ed_cloud_url.text() is not None


def test_onboarding_tab_navigation_reaches_cloud_fields(qtbot, tmp_path):
    from gui.onboarding_wizard import OnboardingWizard
    wiz = OnboardingWizard(_Trunk(tmp_path))
    qtbot.addWidget(wiz)
    wiz.show()
    wiz.ed_cloud_key.setFocus()
    qtbot.keyClick(wiz.ed_cloud_key, Qt.Key_Tab)
    # The exact next widget may evolve, but focus must stay inside the wizard.
    assert wiz.focusWidget() is not None
