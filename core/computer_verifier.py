# -*- coding: utf-8 -*-
"""电脑 Agent 动作验证和截图差异判断。"""
from __future__ import annotations

import os
import time
from core.action_schema import validate_action

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class ComputerVerifierMixin:
    def _wait_verify(self, action, result, before, timeout=1.5):
        deadline = time.time() + max(0.0, float(timeout or 0))
        last = None
        while True:
            last = self._verify_once(action, result, before)
            if last.get("ok") or time.time() >= deadline:
                return last
            self._sleep(0.2)

    def verify(self, action, result, before=None):
        action = validate_action(action)
        if not result.get("ok"):
            return {"ok": False, "reason": result.get("output", "动作失败")}
        v = action.get("verify") or {"type": "none"}
        timeout = 0 if v.get("type") == "none" else float(v.get("timeout", 1.5))
        return self._wait_verify(action, result, before, timeout)

    def _verify_once(self, action, result, before):
        v = action.get("verify") or {"type": "none"}
        vtype = v.get("type", "none")
        if vtype == "none":
            return {"ok": True, "reason": "无需额外验证"}
        if vtype == "exit_code":
            raw = result.get("raw")
            code = None
            if isinstance(raw, dict):
                code = raw.get("退出码", raw.get("exit_code", raw.get("returncode")))
            expected = int(v.get("expected", 0))
            return {"ok": code == expected,
                    "reason": "退出码 %s，期望 %s" % (code, expected)}
        if vtype in ("file_exists", "file_changed", "file_contains"):
            path = (v.get("path") or (action.get("args") or {}).get("path")
                    or (action.get("target") or {}).get("path"))
            if not path:
                return {"ok": False, "reason": "验证缺少路径"}
            exists = os.path.isfile(path)
            if vtype == "file_exists":
                return {"ok": exists, "reason": "文件%s" %
                        ("存在" if exists else "不存在")}
            if vtype == "file_contains":
                expected = str(v.get("expected") or "")
                try:
                    content = open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    content = ""
                return {"ok": exists and expected in content,
                        "reason": "文件%s包含预期文本" %
                        ("已" if expected in content else "未")}
            before_snap = (before or {}).get("file") or {}
            sig = self._file_sig(path)
            changed = exists and sig != before_snap
            return {"ok": changed, "reason": "文件%s发生变化" %
                    ("已" if changed else "未")}
        if vtype == "window_title":
            expected = str(v.get("expected") or "")
            try:
                wins = self._ctrl().list_windows()
                titles = [str(w.get("title") if isinstance(w, dict) else w)
                          for w in wins]
            except Exception:
                titles = []
            found = any(expected.lower() in t.lower() for t in titles)
            return {"ok": found, "reason": "窗口标题%s包含 %s" %
                    ("已" if found else "未", expected)}
        if vtype == "screenshot_diff":
            before_path = (before or {}).get("screenshot")
            after_path = result.get("after_screenshot") or (before or {}).get("after_screenshot")
            if not after_path:
                try:
                    after_path = os.path.join(
                        self._run_base(),
                        "verify_%s.png" % str(time.time_ns()))
                    ok, _ = self._ctrl().screenshot(after_path)
                    if not ok:
                        after_path = ""
                except Exception:
                    after_path = ""
            changed, ratio = self._image_changed(before_path, after_path)
            threshold = float(v.get("threshold", 0.001))
            return {"ok": bool(after_path and changed and ratio >= threshold),
                    "reason": "屏幕变化比例 %.4f" % ratio}
        if vtype == "control_visible":
            name = v.get("name") or (action.get("target") or {}).get("name")
            try:
                r = self._ctrl().ui_find(
                    name=name, control_type=v.get("control_type"),
                    window=v.get("window"))
                if isinstance(r, dict):
                    visible = bool(r.get("ok")) and (
                        int(r.get("找到") or 0) > 0 or bool(r.get("控件")))
                else:
                    visible = bool(r)
                return {"ok": visible, "reason": "控件%s" %
                        ("可见" if visible else "未找到")}
            except Exception as e:
                return {"ok": False, "reason": str(e)[:120]}
        if vtype in ("text_changed", "element_value"):
            expected = str(v.get("expected") or "")
            after_snap = self.observe(
                include_screenshot=False, include_browser=False)
            after_text = after_snap.get("ui_text", "")
            before_text = (before or {}).get("ui_text", "")
            if vtype == "element_value":
                name = v.get("name") or (action.get("target") or {}).get("name")
                value = ""
                c = self._ctrl()
                if name and hasattr(c, "ui_value"):
                    try:
                        value = str(c.ui_value(name=name,
                                               window=v.get("window")) or "")
                    except Exception:
                        value = ""
                if not value and name:
                    for e in after_snap.get("elements") or []:
                        if name.lower() in str(e.get("name", "")).lower():
                            value = str(e.get("value") or "")
                            break
                return {"ok": bool(value) and (not expected or expected in value),
                        "reason": "控件值=%s" % value[:200]}
            if expected:
                ok = expected in after_text
                return {"ok": ok, "reason": "界面文本%s包含预期内容" %
                        ("已" if ok else "未")}
            changed = bool(after_text and after_text != before_text)
            return {"ok": changed, "reason": "界面文本%s变化" %
                    ("已" if changed else "未")}
        if vtype == "url_contains":
            expected = str(v.get("expected") or "")
            info = self._browser_info()
            url = str(info.get("url") or info.get("当前网址") or "")
            return {"ok": expected.lower() in url.lower(),
                    "reason": "当前 URL=%s" % url[:300]}
        if vtype == "wait_for":
            condition = v.get("condition") or v
            probe = {"type": "wait_for", "verify": condition,
                     "args": action.get("args") or {},
                     "target": action.get("target") or {}}
            return self._verify_once(probe, {"ok": True}, before)
        return {"ok": True, "reason": "验证类型 %s 已跳过" % vtype}

    @staticmethod
    def _file_hash(path):
        try:
            import hashlib
            with open(path, "rb") as f:
                return hashlib.sha1(f.read(), usedforsecurity=False).hexdigest()
        except OSError:
            return ""

    @staticmethod
    def _file_sig(path):
        try:
            st = os.stat(path)
            return (st.st_size, st.st_mtime)
        except (OSError, TypeError):
            return None

    @staticmethod
    def _image_changed(before_path, after_path):
        if not before_path or not after_path:
            return False, 0.0
        if not (os.path.isfile(before_path) and os.path.isfile(after_path)):
            return False, 0.0
        try:
            from PIL import Image, ImageChops, ImageStat
            a = Image.open(before_path).convert("RGB")
            b = Image.open(after_path).convert("RGB")
            if a.size != b.size:
                return True, 1.0
            diff = ImageChops.difference(a, b)
            stat = ImageStat.Stat(diff)
            mean = sum(stat.mean) / max(1, len(stat.mean))
            return mean > 1.0, mean / 255.0
        except Exception:
            return ComputerVerifierMixin._file_hash(before_path) != \
                ComputerVerifierMixin._file_hash(after_path), 0.01
