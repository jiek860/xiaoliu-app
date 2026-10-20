# -*- coding: utf-8 -*-
"""电脑 Agent 动作执行、浏览器动作和截图标注。"""
from __future__ import annotations

import json
import os
import time
from core.action_schema import action_summary, validate_action
from core.computer_shared import AgentCancelled
from core.agent_permissions import authorize_agent_action

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class ComputerExecutorMixin:
    def _click(self, action, target):
        c = self._ctrl()
        name = target.get("name") or target.get("uia_id")
        control_type = target.get("control_type")
        window = target.get("window")
        if name:
            r = c.ui_click(name=name, control_type=control_type, window=window)
            ok, text = self._normalize_result(r)
            if ok:
                return r
        rect = target.get("rect")
        if rect:
            xy = self._rect_center(rect)
            if xy:
                return c.mouse_click(xy[0], xy[1],
                                     button=(action.get("args") or {}).get("button", "left"),
                                     clicks=int((action.get("args") or {}).get("clicks", 1)))
        args = action.get("args") or {}
        if "x" in args and "y" in args:
            return c.mouse_click(int(args["x"]), int(args["y"]),
                                 button=args.get("button", "left"),
                                 clicks=int(args.get("clicks", 1)))
        return {"ok": False, "错误": "无法解析点击目标"}

    def _annotate_shot(self, path, target=None):
        """在截图里框出目标区域，让用户看得见 Agent 到底点了哪里。"""
        rect = (target or {}).get("rect")
        if not path or not rect or not os.path.isfile(path):
            return path
        try:
            from PIL import Image, ImageDraw
            img = Image.open(path).convert("RGB")
            x, y, w, h = [int(v) for v in rect[:4]]
            screen = self._screen_info() or {}
            x -= int(screen.get("left", 0) or 0)
            y -= int(screen.get("top", 0) or 0)
            draw = ImageDraw.Draw(img)
            draw.rectangle([x, y, x + max(1, w), y + max(1, h)],
                           outline=(255, 64, 64), width=3)
            label = str((target or {}).get("name")
                        or (target or {}).get("element_id") or "target")[:40]
            draw.text((max(0, x), max(0, y - 14)), label, fill=(255, 64, 64))
            img.save(path)
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        return path

    def _browser_execute(self, action):
        b = self._browser()
        if b is None:
            return {"ok": False, "错误": "浏览器模块未加载"}
        t = action["type"]
        args = action.get("args") or {}
        target = action.get("target") or {}
        selector = args.get("selector") or target.get("selector") or ""
        try:
            if t == "browser_open":
                return b.open(args.get("url") or target.get("url") or "",
                              headless=False)
            if t == "browser_click":
                return b.click(selector)
            if t == "browser_type":
                return b.type_text(selector, str(args.get("text") or ""))
            if t == "browser_text":
                return b.get_text(selector or None)
            if t == "browser_screenshot":
                return b.screenshot(args.get("path"))
            if t == "browser_wait":
                return b.wait(float(args.get("seconds") or 2))
        except Exception as e:
            return {"ok": False, "错误": str(e)[:300]}
        return {"ok": False, "错误": "未知浏览器动作"}

    def _backup_path(self, path):
        if self._rollback_store is None:
            return ""
        return self._rollback_store._backup_path(path)

    def _remember_file_action(self, action):
        """在真正写文件前记录可回滚快照。"""
        if self._rollback_store is None:
            from core.computer_rollback import FileRollbackStore
            self._rollback_store = FileRollbackStore(
                getattr(self.trunk, "base", os.getcwd()), self._run_dir)
        self._rollback_store.remember(action)
        self._rollback_items = self._rollback_store.items

    def execute(self, action):
        """执行一个已经过 schema 校验的动作。"""
        self._check_control()
        action = validate_action(action)
        approved = action.get("action_id") in self._approved_action_ids
        gate = authorize_agent_action(
            self.trunk, "computer_agent", action,
            title="电脑 Agent 请求执行动作",
            detail=action_summary(action) + "\n" + json.dumps(
                action, ensure_ascii=False, default=str)[:2500],
            already_approved=approved)
        if not gate.get("allow"):
            return {"ok": False, "output": gate.get("reason", "权限拒绝"),
                    "permission": gate, "raw": None}
        t = action["type"]
        target = self._resolve_target(action)
        args = dict(action.get("args") or {})
        c = self._ctrl()
        if t not in ("read_file", "list_windows", "screenshot", "browser_text",
                     "browser_screenshot"):
            self._remember_file_action(action)
        try:
            if t.startswith("browser_"):
                r = self._browser_execute(action)
            elif t == "click":
                r = self._click(action, target)
            elif t == "type":
                name = target.get("name") or target.get("element_id")
                if name:
                    r = c.ui_type(name=name,
                                  text=str(args.get("text") or ""),
                                  window=target.get("window"))
                else:
                    r = c.type_text(str(args.get("text") or ""))
            elif t == "hotkey":
                r = c.hotkey(args.get("keys") or [])
            elif t == "press_key":
                r = c.press_key(str(args.get("key") or ""))
            elif t == "scroll":
                r = c.mouse_scroll(int(args.get("clicks", 3)),
                                   x=args.get("x"), y=args.get("y"))
            elif t == "drag":
                r = c.mouse_drag(
                    int(args.get("x1", 0)), int(args.get("y1", 0)),
                    int(args.get("x2", 0)), int(args.get("y2", 0)),
                    button=args.get("button", "left"),
                    duration=float(args.get("duration", 0.5)))
            elif t == "open_app":
                r = c.open_app(args.get("name") or target.get("name"))
            elif t == "open_url":
                r = c.open_url(args.get("url") or target.get("url"))
            elif t == "activate_window":
                r = c.activate_window(args.get("name") or target.get("name"))
            elif t == "close_window":
                r = c.close_window(args.get("name") or target.get("name"))
            elif t == "list_windows":
                r = c.list_windows()
            elif t == "screenshot":
                r = c.screenshot(args.get("path"))
            elif t == "read_file":
                r = c.read_text(args.get("path") or target.get("path"))
            elif t == "write_file":
                r = c.create_file(args.get("path") or target.get("path"),
                                  args.get("content", ""))
            elif t == "edit_file":
                r = c.edit_text({
                    "path": args.get("path") or target.get("path"),
                    "old": args.get("old", ""),
                    "new": args.get("new", ""),
                })
            elif t == "delete_file":
                r = c.delete_file(args.get("path") or target.get("path"))
            elif t == "copy_file":
                r = c.copy_file(args.get("path") or target.get("path"),
                                args.get("dst") or args.get("destination"))
            elif t == "move_file":
                r = c.move_file(args.get("path") or target.get("path"),
                                args.get("dst") or args.get("destination"))
            elif t == "clipboard_get":
                r = c.clipboard_get()
            elif t == "clipboard_set":
                r = c.clipboard_set(str(args.get("text") or ""))
            elif t == "shell":
                r = c.shell(args.get("cmd"))
            elif t == "wait":
                self._sleep(float(args.get("seconds", 1)))
                r = {"ok": True, "结果": "等待完成"}
            elif t == "wait_for":
                condition = args.get("condition") or action.get("verify") or {}
                deadline = time.time() + float(args.get("timeout", 5))
                last = None
                while time.time() < deadline:
                    self._check_control()
                    last = self.verify({"type": "wait_for",
                                        "verify": condition,
                                        "args": args,
                                        "target": target}, {"ok": True})
                    if last.get("ok"):
                        break
                    self._sleep(0.25)
                r = {"ok": bool(last and last.get("ok")),
                     "结果": (last or {}).get("reason", "")}
            else:
                return {"ok": False, "output": "未实现动作: " + t, "raw": None}
            ok, output = self._normalize_result(r)
            after_path = ""
            try:
                shot_dir = self._run_base()
                after_path = os.path.join(
                    shot_dir, "after_%s.png" % str(time.time_ns()))
                shot_ok, _ = c.screenshot(after_path)
                if not shot_ok:
                    after_path = ""
                else:
                    self._annotate_shot(after_path, target)
            except Exception:
                after_path = ""
            return {"ok": ok, "output": output, "raw": r,
                    "target": target, "after_screenshot": after_path}
        except AgentCancelled:
            raise
        except Exception as e:
            return {"ok": False, "output": str(e)[:400], "raw": None}

    @staticmethod
    def _normalize_result(r):
        if isinstance(r, tuple) and len(r) >= 2:
            return bool(r[0]), str(r[1])
        if isinstance(r, dict):
            ok = bool(r.get("ok", r.get("成功", True)))
            text = (r.get("内容") or r.get("结果") or r.get("错误")
                    or r.get("output") or r)
            return ok, str(text)[:1200]
        if isinstance(r, bool):
            return r, ""
        return True, str(r)[:1200]
