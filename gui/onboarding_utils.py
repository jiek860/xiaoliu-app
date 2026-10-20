# -*- coding: utf-8 -*-
"""首次设置向导共享工具。"""
from __future__ import annotations

import os

from core import model_setup

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def _model_text(w):
    return (w.currentText() if hasattr(w, "currentText") else w.text()).strip()


def _set_model_text(w, s):
    s = str(s or "")
    if hasattr(w, "setEditText"):
        w.setEditText(s)
    else:
        w.setText(s)


def marker_path(trunk):
    d = getattr(trunk, "data_dir", None)
    if not d:
        base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        d = os.path.join(base, "data")
    return os.path.join(d, ".guide_done")


def needs_onboarding(trunk):
    if os.path.exists(marker_path(trunk)):
        return False
    try:
        return not model_setup.check(trunk, probe=False)["ready"]
    except Exception as e:
        _x6_swallowed(__name__, e)
        return False


def mark_done(trunk):
    try:
        p = marker_path(trunk)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("ok")
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass
