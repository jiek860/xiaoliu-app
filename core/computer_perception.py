# -*- coding: utf-8 -*-
"""电脑 Agent 观察、UIA/OCR/grounding 和目标解析。"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections import OrderedDict
from core.visual_grounding import parse_uia_lines, ground, fuse_grounding

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class ComputerPerceptionMixin:
    def _ctrl(self):
        if self.controller is not None:
            return self.controller
        c = (getattr(self.trunk, "modules", {}) or {}).get("computer_controller")
        if c is None:
            try:
                self.trunk.call("computer_controller", "__no__")
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
            c = (getattr(self.trunk, "modules", {}) or {}).get("computer_controller")
        if c is None:
            raise RuntimeError("电脑控制模块未加载")
        self.controller = c
        return c

    def _browser(self):
        mods = getattr(self.trunk, "modules", {}) or {}
        b = mods.get("browser")
        if b is None:
            try:
                self.trunk.call("browser", "__no__")
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
            b = mods.get("browser")
        return b

    def _browser_info(self):
        b = self._browser()
        if b is None:
            return {}
        try:
            if hasattr(b, "current_info"):
                r = b.current_info()
                if isinstance(r, dict) and r.get("ok", True):
                    return r
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        return {}

    def _screen_info(self):
        c = self._ctrl()
        try:
            if hasattr(c, "screen_info"):
                return c.screen_info()
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        return {}

    def _run_base(self):
        raw = self._last_run_id or ("computer_" + str(int(time.time())))
        safe = re.sub(r'[<>:"/\\|?*]+', "_", str(raw)).strip(" .")[:120]
        base = os.path.join(getattr(self.trunk, "base", os.getcwd()),
                            "data", "agent_runs", safe or "computer_run")
        os.makedirs(base, exist_ok=True)
        return base

    def observe(self, *, include_screenshot=True, include_uia=True,
                include_browser=True):
        """按需观察屏幕。

        动态循环默认截图 + UIA；验证文本时只要 UIA，不重复截屏。
        """
        c = self._ctrl()
        snap = {"time": time.time(), "windows": [], "screenshot": "",
                "active_window": "", "elements": [], "browser": {},
                "screen": self._screen_info(), "ui_text": ""}
        try:
            snap["windows"] = c.list_windows()
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            snap["active_window"] = c.get_active_window()
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        if include_screenshot:
            try:
                shot_dir = self._run_base()
                path = os.path.join(
                    shot_dir, "observe_%s_%s.png" % (
                        time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex))
                ok, msg = c.screenshot(path)
                if ok:
                    snap["screenshot"] = path
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
        snap["window_titles"] = [
            w.get("title") if isinstance(w, dict) else str(w)
            for w in (snap.get("windows") or [])]
        if include_uia:
            try:
                win = snap.get("active_window") or None
                dump = c.ui_dump(window=win, depth=4) if hasattr(c, "ui_dump") else {}
                if isinstance(dump, dict) and dump.get("ok"):
                    snap["elements"] = parse_uia_lines(dump.get("结构", ""))
                    snap["ui_dump"] = dump.get("结构", "")
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
        self._element_map = {e.get("element_id"): e
                             for e in snap.get("elements") or []
                             if e.get("element_id")}
        if include_browser:
            snap["browser"] = self._browser_info()
        snap["ui_text"] = self._ui_signature(snap)
        return snap

    @staticmethod
    def _ui_signature(snapshot):
        parts = []
        for el in (snapshot or {}).get("elements") or []:
            parts.append("%s=%s" % (el.get("name", ""), el.get("value", "")))
        if (snapshot or {}).get("active_window"):
            parts.append(str(snapshot.get("active_window")))
        return "\n".join(parts)[:20000]

    def _ocr_text(self, snapshot):
        """调用 image_ocr / multimodal 对截图做文字和视觉理解。"""
        path = (snapshot or {}).get("screenshot")
        if not path or not os.path.isfile(path):
            return "", ""
        try:
            st = os.stat(path)
            cache_key = (path, st.st_size, st.st_mtime_ns)
        except OSError:
            cache_key = (path, 0, 0)
        if cache_key in self._ocr_cache:
            self._ocr_cache.move_to_end(cache_key)
            return self._ocr_cache[cache_key]
        text = vision = ""
        mods = getattr(self.trunk, "modules", {}) or {}
        ocr = mods.get("image_ocr")
        if ocr is not None and hasattr(ocr, "recognize"):
            try:
                r = ocr.recognize(path)
                if isinstance(r, dict):
                    text = str(r.get("文字") or r.get("text") or "")
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
        mm = mods.get("multimodal")
        if mm is not None and hasattr(mm, "describe_image"):
            try:
                r = mm.describe_image(path)
                if isinstance(r, dict):
                    vision = str(r.get("描述") or r.get("description") or "")
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
        self._ocr_cache[cache_key] = (text, vision)
        self._ocr_cache.move_to_end(cache_key)
        while len(self._ocr_cache) > 40:
            self._ocr_cache.popitem(last=False)
        return text, vision

    def ground(self, goal, snapshot=None, min_confidence=0.0,
               use_ocr=None, use_vision=None):
        snap = snapshot or self.observe()
        # 先用 UIA：有高置信可执行候选时，不调用 OCR/视觉模型。
        uia_hits = ground(goal, snap.get("elements") or [], top_k=8)
        need_visual = not any(
            h.get("confidence", 0) >= 0.65 and h.get("actionable", True)
            for h in uia_hits)
        if use_ocr is None:
            use_ocr = need_visual
        if use_vision is None:
            use_vision = need_visual
        ocr_text = vision_text = ""
        if use_ocr or use_vision:
            ocr_text, vision_text = self._ocr_text(snap)
            if not use_ocr:
                ocr_text = ""
            if not use_vision:
                vision_text = ""
        hits = fuse_grounding(goal, snap.get("elements") or [],
                              ocr_text=ocr_text, vision_text=vision_text,
                              top_k=8)
        if min_confidence > 0:
            hits = [x for x in hits
                    if x.get("confidence", 0) >= min_confidence]
        return hits

    def _candidate_prompt(self, snapshot, grounding=None, limit=60):
        items = list(grounding or []) or list((snapshot or {}).get("elements") or [])
        out = []
        for e in items[:limit]:
            out.append({
                "element_id": e.get("element_id", ""),
                "name": e.get("name", ""),
                "value": e.get("value", ""),
                "type": e.get("type", ""),
                "rect": e.get("rect") or [],
                "confidence": e.get("confidence"),
                "source": e.get("source", ""),
            })
        return out

    def _resolve_target(self, action, snapshot=None):
        target = dict(action.get("target") or {})
        eid = target.get("element_id")
        if eid and eid in self._element_map:
            resolved = dict(self._element_map[eid])
            resolved.update(target)
            return resolved
        if not target.get("rect") and snapshot:
            name = str(target.get("name") or "")
            if name:
                hits = ground(name, snapshot.get("elements") or [], top_k=1)
                if hits:
                    resolved = dict(hits[0])
                    resolved.update(target)
                    return resolved
        return target

    @staticmethod
    def _rect_center(rect):
        try:
            x, y, w, h = [int(v) for v in rect[:4]]
            return x + max(1, w) // 2, y + max(1, h) // 2
        except Exception:
            return None
