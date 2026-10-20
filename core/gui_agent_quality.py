# -*- coding: utf-8 -*-
"""GUI Agent quality helpers: dual-channel grounding, verification and repair.

This module is intentionally UI-toolkit-free. Existing computer control modules
supply screenshots/UIA snapshots and execute actions; this layer decides which
candidate to use, whether the action succeeded, and what to try next.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from core.visual_grounding import fuse_grounding


@dataclass
class RetryPolicy:
    max_retries: int = 2
    wait_seconds: float = 0.3
    refresh_snapshot: bool = True
    allow_replan: bool = True

    def sequence(self):
        out = []
        for i in range(max(0, int(self.max_retries)) + 1):
            if i:
                out.append({"wait": self.wait_seconds})
            if self.refresh_snapshot:
                out.append({"refresh_snapshot": True})
            out.append({"attempt": i + 1})
            if i and self.allow_replan:
                out.append({"replan": True})
        return out


def monitor_at_point(monitors, x, y):
    for m in monitors or []:
        rect = m.get("rect") or m.get("geometry") or [0, 0, 0, 0]
        try:
            mx, my, mw, mh = [int(v) for v in rect[:4]]
        except Exception:  # 静默是故意的
            continue
        if mx <= int(x) < mx + max(1, mw) and my <= int(y) < my + max(1, mh):
            return dict(m)
    return None


def to_logical_point(x, y, scale=1.0):
    scale = float(scale or 1.0)
    return {"x": int(round(float(x) / scale)),
            "y": int(round(float(y) / scale)), "scale": scale}


def to_physical_point(x, y, scale=1.0):
    scale = float(scale or 1.0)
    return {"x": int(round(float(x) * scale)),
            "y": int(round(float(y) * scale)), "scale": scale}


def normalize_rect_for_monitor(rect, monitor_rect, scale=1.0):
    """Clamp a physical rect to one monitor and return logical coordinates."""
    try:
        x, y, w, h = [int(v) for v in rect[:4]]
        mx, my, mw, mh = [int(v) for v in monitor_rect[:4]]
    except Exception:
        return None
    left = max(x, mx)
    top = max(y, my)
    right = min(x + max(1, w), mx + max(1, mw))
    bottom = min(y + max(1, h), my + max(1, mh))
    if right <= left or bottom <= top:
        return None
    logical = to_logical_point(left - mx, top - my, scale)
    return {"x": logical["x"], "y": logical["y"],
            "w": max(1, int(round((right - left) / float(scale or 1.0)))),
            "h": max(1, int(round((bottom - top) / float(scale or 1.0)))),
            "monitor": dict(monitor_rect=list(monitor_rect[:4]), scale=scale)}


def input_mode_for_text(text, ime_active=False):
    """Choose paste for multiline/IME text; type for short ASCII input."""
    s = str(text or "")
    if ime_active or "\n" in s or "\r" in s or len(s) > 120:
        return "paste"
    if all(ord(ch) < 128 for ch in s):
        return "type"
    return "paste"


def normalize_text_for_input(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


class DualChannelLocator:
    def __init__(self, min_uia_confidence=0.65):
        self.min_uia_confidence = float(min_uia_confidence)

    def locate(self, goal, elements=None, ocr_text="", vision_text="",
               top_k=5):
        elements = list(elements or [])
        try:
            hits = fuse_grounding(goal, elements, ocr_text=ocr_text,
                                  vision_text=vision_text, top_k=top_k)
        except Exception:
            hits = []
        if not hits:
            return []
        out = []
        for h in hits:
            h = dict(h)
            source = h.get("source") or "uia"
            if source == "uia" and h.get("confidence", 0) < self.min_uia_confidence:
                # Keep low-confidence UIA candidates after visual candidates.
                h["confidence"] = float(h.get("confidence", 0)) * 0.9
            out.append(h)
        out.sort(key=lambda x: float(x.get("confidence", 0)), reverse=True)
        return out[:max(1, int(top_k))]


def _snapshot_text(snapshot):
    return str((snapshot or {}).get("ui_text") or "").lower()


def verify_snapshot(before, after, expectation):
    """Verify common UI outcomes using UIA/OCR text and screenshot hashes."""
    exp = expectation or {}
    if not isinstance(exp, dict):
        return {"ok": True, "reason": "no expectation"}
    after = after or {}
    before = before or {}
    if exp.get("window_title_contains"):
        title = str(after.get("active_window") or "").lower()
        expected = str(exp["window_title_contains"]).lower()
        return {"ok": expected in title,
                "reason": "window title %s" % ("matched" if expected in title else "not matched")}
    if exp.get("text_contains"):
        expected = str(exp["text_contains"]).lower()
        text = _snapshot_text(after)
        if expected not in text:
            # OCR text can arrive separately in screenshots.
            text += "\n" + str(after.get("ocr_text") or "").lower()
        return {"ok": expected in text,
                "reason": "UI text %s" % ("matched" if expected in text else "not matched")}
    if exp.get("element_present"):
        name = str(exp["element_present"]).lower()
        found = any(name in str(e.get("name", "")).lower()
                    for e in after.get("elements") or [])
        return {"ok": found, "reason": "element %s" % ("found" if found else "missing")}
    if exp.get("screenshot_changed"):
        def sig(snap):
            raw = str((snap or {}).get("screenshot_signature") or
                      (snap or {}).get("screenshot") or "")
            return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
        changed = sig(before) != sig(after)
        return {"ok": changed, "reason": "screenshot %s" % ("changed" if changed else "unchanged")}
    return {"ok": True, "reason": "no concrete expectation"}


def repair_strategy(action, result, attempt=0):
    """Return an ordered, bounded recovery plan for a failed GUI action."""
    text = str((result or {}).get("reason") or (result or {}).get("error") or "").lower()
    action = action or {}
    plan = []
    if any(x in text for x in ("not found", "missing", "未找到", "找不到")):
        plan += ["refresh_snapshot", "scroll_window", "alternate_locator"]
    elif any(x in text for x in ("timeout", "超时", "busy", "忙")):
        plan += ["wait", "refresh_snapshot"]
    elif any(x in text for x in ("permission", "denied", "权限", "拒绝")):
        plan += ["request_confirmation"]
    else:
        plan += ["retry", "refresh_snapshot"]
    if int(attempt) >= 1:
        plan += ["replan"]
    if int(attempt) >= 2:
        plan += ["ask_user"]
    # Stable dedupe, preserving order.
    seen = set()
    return [x for x in plan if not (x in seen or seen.add(x))]


def click_center(rect):
    try:
        x, y, w, h = [int(v) for v in rect[:4]]
        return {"x": x + max(1, w) // 2, "y": y + max(1, h) // 2}
    except Exception:
        return None
