# -*- coding: utf-8 -*-
"""电脑控制：鼠标、键盘、拖拽、滚轮和剪贴板。"""
from __future__ import annotations

import re
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class ComputerInputToolsMixin:
    def _parse_xy(self, s):
        """把 '500,300' / '500 300' 解析成 (x, y)"""
        s = re.sub(r"[（(]", ",", s.strip())
        s = re.sub(r"[）)]", "", s)
        parts = re.split(r"[,，\s]+", s)
        nums = []
        for p in parts:
            p = p.strip()
            if p.lstrip("-").isdigit():
                nums.append(int(p))
        if len(nums) >= 2:
            return nums[0], nums[1]
        return None

    def _clamp(self, x, y):
        left, top, width, height = self._virtual_screen_rect()
        return (max(left, min(left + width - 1, int(x))),
                max(top, min(top + height - 1, int(y))))

    def mouse_move(self, x, y, duration=0.3):
        gui = self._gui()
        if isinstance(gui, Exception):
            return False, "缺少 pyautogui: %s" % gui
        x, y = self._clamp(int(x), int(y))
        try:
            gui.moveTo(x, y, duration=duration)
            self._log("mouse_move", "%d,%d" % (x, y))
            return True, "鼠标已移动到 (%d, %d)" % (x, y)
        except Exception as e:
            return False, str(e)[:60]

    def mouse_click(self, x=None, y=None, button="left", clicks=1):
        gui = self._gui()
        if isinstance(gui, Exception):
            return False, "缺少 pyautogui: %s" % gui
        try:
            if x is not None and y is not None:
                x, y = self._clamp(int(x), int(y))
                gui.moveTo(x, y, duration=0.2)
            btn = {"左": "left", "left": "left", "右": "right", "right": "right",
                   "中": "middle", "middle": "middle"}.get(button, button)
            gui.click(button=btn, clicks=clicks)
            px, py = gui.position()
            self._log("mouse_click", "%s x%d @(%d,%d)" % (btn, clicks, px, py))
            return True, "已%s点击(%d,%d)" % ("双击" if clicks > 1 else "", px, py)
        except Exception as e:
            return False, str(e)[:60]

    def mouse_drag(self, x1, y1, x2, y2, button="left", duration=0.5):
        gui = self._gui()
        if isinstance(gui, Exception):
            return False, "缺少 pyautogui: %s" % gui
        try:
            x1, y1 = self._clamp(int(x1), int(y1))
            x2, y2 = self._clamp(int(x2), int(y2))
            btn = "right" if button in ("右", "right") else "left"
            gui.moveTo(x1, y1, duration=0.2)
            gui.dragTo(x2, y2, duration=duration, button=btn)
            self._log("mouse_drag", "(%d,%d)->(%d,%d)" % (x1, y1, x2, y2))
            return True, "已拖动 (%d,%d) → (%d,%d)" % (x1, y1, x2, y2)
        except Exception as e:
            return False, str(e)[:60]

    def mouse_scroll(self, clicks=3, x=None, y=None):
        gui = self._gui()
        if isinstance(gui, Exception):
            return False, "缺少 pyautogui: %s" % gui
        try:
            if x is not None and y is not None:
                x, y = self._clamp(int(x), int(y))
                gui.moveTo(x, y, duration=0.2)
            gui.scroll(int(clicks))
            self._log("mouse_scroll", str(clicks))
            return True, "已滚动 %d 格" % int(clicks)
        except Exception as e:
            return False, str(e)[:60]

    def mouse_pos(self):
        gui = self._gui()
        if isinstance(gui, Exception):
            return False, "缺少 pyautogui: %s" % gui
        x, y = gui.position()
        return True, "当前鼠标位置: (%d, %d)" % (x, y)

    def type_text(self, text):
        """输入文字：非ASCII走剪贴板粘贴"""
        gui = self._gui()
        if isinstance(gui, Exception):
            return False, "缺少 pyautogui: %s" % gui
        try:
            text = text.strip().strip('"')
            if text.isascii():
                gui.typewrite(text, interval=0.02)
            else:
                import pyperclip
                pyperclip.copy(text)
                gui.hotkey("ctrl", "v")
            self._log("type_text", text[:50])
            return True, "已输入: " + text[:50] + ("…" if len(text) > 50 else "")
        except Exception as e:
            return False, str(e)[:60]

    def hotkey(self, keys):
        """快捷键：'ctrl+c' / 'ctrl+shift+s' / 'win+d'"""
        gui = self._gui()
        if isinstance(gui, Exception):
            return False, "缺少 pyautogui: %s" % gui
        try:
            parts = [p.strip().lower() for p in re.split(r"[+＋]", keys) if p.strip()]
            gui.hotkey(*parts)
            self._log("hotkey", "+".join(parts))
            return True, "已按快捷键: " + "+".join(parts)
        except Exception as e:
            return False, str(e)[:60]

    def press_key(self, key):
        gui = self._gui()
        if isinstance(gui, Exception):
            return False, "缺少 pyautogui: %s" % gui
        try:
            gui.press(key.strip())
            self._log("press_key", key)
            return True, "已按键: " + key
        except Exception as e:
            return False, str(e)[:60]

    def clipboard_get(self):
        try:
            import pyperclip
            txt = pyperclip.paste()
            return True, "剪贴板内容: " + (txt[:200] if txt else "（空）")
        except Exception as e:
            return False, str(e)[:60]

    def clipboard_set(self, text):
        try:
            import pyperclip
            text = text.strip().strip('"')
            pyperclip.copy(text)
            self._log("clipboard_set", text[:50])
            return True, "已复制到剪贴板: " + text[:100]
        except Exception as e:
            return False, str(e)[:60]
