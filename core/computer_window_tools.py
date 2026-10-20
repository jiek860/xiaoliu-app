# -*- coding: utf-8 -*-
"""ComputerController 的窗口 / UI Automation mixin。"""
from __future__ import annotations

import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def _ih(pkg):
    try:
        from core.error_text import install_hint
        return install_hint(pkg)
    except Exception as e:
        _x6_swallowed(__name__, e)
        return ("py -3 -m pip install --target optional_libs %s "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple" % pkg)


class ComputerWindowToolsMixin:
    _UI_MAX = 40          # 单次最多返回多少个控件

    def _uia(self):
        """取 uiautomation 模块；没装就给出可操作的提示"""
        try:
            import uiautomation as auto
            return auto
        except Exception as e:
            return RuntimeError("没装 uiautomation。\n" + _ih("uiautomation") + "\n（原因: "
                                + str(e)[:50])

    def ui_available(self):
        a = self._uia()
        return not isinstance(a, Exception)

    def ui_windows(self):
        """列出顶层窗口（名字 / 控件类型 / 位置）—— 比 pygetwindow 版更准"""
        a = self._uia()
        if isinstance(a, Exception):
            return {"ok": False, "错误": str(a)}
        out = []
        try:
            root = a.GetRootControl()
            for w in root.GetChildren():
                try:
                    nm = (w.Name or "").strip()
                    if not nm:
                        continue
                    r = w.BoundingRectangle
                    out.append({"名称": nm, "类型": w.ControlTypeName,
                                "位置": [r.left, r.top, r.right, r.bottom]})
                except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                    continue
                if len(out) >= self._UI_MAX:
                    break
        except Exception as e:
            return {"ok": False, "错误": "枚举窗口失败: " + str(e)[:60]}
        self._log("ui_windows", "%d 个" % len(out))
        return {"ok": True, "窗口数": len(out), "窗口": out}

    def ui_find(self, name=None, control_type=None, window=None, depth=6):
        """按名字/类型找控件（不点击，只定位）

        name         控件名（支持子串匹配，不区分大小写）
        control_type ButtonControl / EditControl / ListItemControl ...
        window       限定在哪个窗口里找（窗口名子串）；不填则全桌面找
        depth        搜索深度，默认 6（越深越慢）
        """
        a = self._uia()
        if isinstance(a, Exception):
            return {"ok": False, "错误": str(a)}
        if not name and not control_type:
            return {"ok": False, "错误": "至少要给 name 或 control_type"}
        try:
            depth = max(1, min(12, int(depth)))
        except Exception:
            depth = 6

        root = None
        if window:
            root = self._ui_window(window, a)
            if root is None:
                return {"ok": False, "错误": "没找到窗口: " + str(window)}
        else:
            try:
                root = a.GetRootControl()
            except Exception as e:
                return {"ok": False, "错误": str(e)[:60]}

        want = str(name or "").strip().lower()
        ctype = str(control_type or "").strip()
        found = []
        try:
            for c in root.GetChildren():
                self._ui_walk(c, want, ctype, found, depth)
                if len(found) >= self._UI_MAX:
                    break
        except Exception as e:
            return {"ok": False, "错误": "搜索失败: " + str(e)[:60]}
        self._log("ui_find", "name=%s type=%s -> %d" % (name, control_type, len(found)))
        return {"ok": True, "找到": len(found), "控件": found}

    def _ui_walk(self, ctrl, want, ctype, found, depth):
        """深度优先遍历控件树（限深限量）"""
        if depth <= 0 or len(found) >= self._UI_MAX:
            return
        try:
            nm = (ctrl.Name or "")
            tn = ctrl.ControlTypeName or ""
            if want and want not in nm.lower():
                pass
            elif ctype and ctype.lower() != tn.lower():
                pass
            else:
                r = ctrl.BoundingRectangle
                found.append({"名称": nm[:60], "类型": tn,
                              "位置": [r.left, r.top, r.right, r.bottom]})
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            for c in ctrl.GetChildren():
                self._ui_walk(c, want, ctype, found, depth - 1)
                if len(found) >= self._UI_MAX:
                    return
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _ui_window(self, title, a):
        """按名字子串找顶层窗口，返回窗口控件"""
        want = str(title or "").strip().lower()
        try:
            for w in a.GetRootControl().GetChildren():
                try:
                    if want in (w.Name or "").lower():
                        return w
                except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                    continue
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        return None

    def ui_dump(self, window=None, depth=3):
        """把一个窗口的控件树打印成缩进文本 —— 让 AI"看见"程序的结构

        这是"盲点坐标"升级的关键：原来只能截图让视觉模型猜，
        现在能直接拿到「窗口 > 面板 > 按钮『确定』」这样的层级。
        """
        a = self._uia()
        if isinstance(a, Exception):
            return {"ok": False, "错误": str(a)}
        root = self._ui_window(window, a) if window else None
        if window and root is None:
            return {"ok": False, "错误": "没找到窗口: " + str(window)}
        if root is None:
            try:
                root = a.GetRootControl()
            except Exception as e:
                return {"ok": False, "错误": str(e)[:60]}
        try:
            depth = max(1, min(8, int(depth)))
        except Exception:
            depth = 3
        lines = []

        def walk(c, d):
            if d > depth or len(lines) >= self._UI_MAX * 4:
                return
            try:
                nm = (c.Name or "").strip()
                tn = c.ControlTypeName or "?"
                val = ""
                try:
                    if "Edit" in tn or "Document" in tn:
                        val = str(c.GetValuePattern().Value or "")[:200]
                except Exception:
                    val = ""
                r = c.BoundingRectangle
                lines.append("%s%s%s%s  @(%d,%d,%dx%d)"
                             % ("  " * d, tn,
                                ("  「%s」" % nm[:40]) if nm else "",
                                ("  = 「%s」" % val) if val else "",
                                r.left, r.top, r.right - r.left, r.bottom - r.top))
            except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                return
            try:
                for ch in c.GetChildren():
                    walk(ch, d + 1)
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")

        walk(root, 0)
        self._log("ui_dump", "window=%s depth=%d -> %d 行" % (window, depth, len(lines)))
        return {"ok": True, "窗口": str(window or "(桌面根)"),
                "行数": len(lines), "结构": "\n".join(lines)}

    def ui_click(self, name, control_type=None, window=None, depth=6):
        """按控件名点击 —— 不依赖坐标，窗口挪了也不怕"""
        a = self._uia()
        if isinstance(a, Exception):
            return {"ok": False, "错误": str(a)}
        root = self._ui_window(window, a) if window else None
        if window and root is None:
            return {"ok": False, "错误": "没找到窗口: " + str(window)}
        hit = None
        want = str(name or "").strip().lower()
        ctype = str(control_type or "").strip().lower()

        def walk(c, d):
            nonlocal hit
            if hit is not None or d <= 0:
                return
            try:
                nm = (c.Name or "").lower()
                tn = (c.ControlTypeName or "").lower()
                if want and want in nm and (not ctype or ctype == tn):
                    hit = c
                    return
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
            try:
                for ch in c.GetChildren():
                    walk(ch, d - 1)
                    if hit is not None:
                        return
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")

        try:
            base = root if root is not None else a.GetRootControl()
            walk(base, max(1, min(12, int(depth))))
        except Exception as e:
            return {"ok": False, "错误": "搜索失败: " + str(e)[:60]}
        if hit is None:
            return {"ok": False, "错误": "没找到控件「%s」%s"
                    % (name, ("（限在窗口 %s 内）" % window) if window else "")}
        if not self._confirm("按控件名点击", "「%s」" % name):
            return {"ok": False, "错误": "已取消"}
        try:
            hit.Click(simulateMove=False)
            self._log("ui_click", str(name))
            return {"ok": True, "已点击": str(name)[:50],
                    "类型": hit.ControlTypeName}
        except Exception as e:
            return {"ok": False, "错误": "点击失败: " + str(e)[:60]}

    def ui_type(self, name, text, window=None, depth=6):
        """往指定控件里输入文字（优先用 ValuePattern，退化为键盘输入）"""
        a = self._uia()
        if isinstance(a, Exception):
            return {"ok": False, "错误": str(a)}
        root = self._ui_window(window, a) if window else None
        hit = None
        want = str(name or "").strip().lower()

        def walk(c, d):
            nonlocal hit
            if hit is not None or d <= 0:
                return
            try:
                if want and want in (c.Name or "").lower():
                    hit = c
                    return
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
            try:
                for ch in c.GetChildren():
                    walk(ch, d - 1)
                    if hit is not None:
                        return
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")

        try:
            base = root if root is not None else a.GetRootControl()
            walk(base, max(1, min(12, int(depth))))
        except Exception as e:
            return {"ok": False, "错误": "搜索失败: " + str(e)[:60]}
        if hit is None:
            return {"ok": False, "错误": "没找到控件「%s」" % name}
        try:
            try:
                hit.GetValuePattern().SetValue(str(text))
            except Exception:
                hit.SetFocus()
                self.type_text(str(text))
            self._log("ui_type", "%s <= %s" % (name, str(text)[:30]))
            return {"ok": True, "控件": str(name)[:40], "文字": str(text)[:40]}
        except Exception as e:
            return {"ok": False, "错误": "输入失败: " + str(e)[:60]}

    def ui_value(self, name, window=None, depth=6):
        """读取控件当前值（Edit/Document 优先 ValuePattern）。"""
        a = self._uia()
        if isinstance(a, Exception):
            return ""
        root = self._ui_window(window, a) if window else None
        want = str(name or "").strip().lower()
        hit = None

        def walk(c, d):
            nonlocal hit
            if hit is not None or d <= 0:
                return
            try:
                if want and want in (c.Name or "").lower():
                    hit = c
                    return
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
            try:
                for ch in c.GetChildren():
                    walk(ch, d - 1)
                    if hit is not None:
                        return
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")

        try:
            walk(root if root is not None else a.GetRootControl(),
                 max(1, min(12, int(depth))))
            if hit is None:
                return ""
            try:
                return str(hit.GetValuePattern().Value or "")
            except Exception:
                return str(getattr(hit, "Name", "") or "")
        except Exception:
            return ""

    def _activate_hwnd(self, hwnd):
        g, con, api = self._win()
        if isinstance(g, Exception):
            return False
        try:
            if g.IsIconic(hwnd):
                g.ShowWindow(hwnd, con.SW_RESTORE)
            # 前台锁绕过：模拟按一下 Alt
            api.keybd_event(0x12, 0, 0, 0)
            api.keybd_event(0x12, 0, con.KEYEVENTF_KEYUP, 0)
            g.SetForegroundWindow(hwnd)
            g.BringWindowToTop(hwnd)
            return True
        except Exception:
            return False

    def activate_window(self, title):
        hwnd = self._find_window(title)
        if not hwnd:
            return False, "没找到包含「%s」的窗口" % title
        ok = self._activate_hwnd(hwnd)
        self._log("activate_window", title, ok)
        return ok, ("已切换到窗口: " + title) if ok else "切换窗口失败"

    def minimize_window(self, title):
        g, con, _ = self._win()
        if isinstance(g, Exception):
            return False, "缺少 win32 支持"
        hwnd = self._find_window(title)
        if not hwnd:
            return False, "没找到包含「%s」的窗口" % title
        try:
            g.ShowWindow(hwnd, con.SW_MINIMIZE)
            self._log("minimize_window", title)
            return True, "已最小化: " + title
        except Exception as e:
            return False, str(e)[:60]

    def close_window(self, title):
        g, con, _ = self._win()
        if isinstance(g, Exception):
            return False, "缺少 win32 支持"
        hwnd = self._find_window(title)
        if not hwnd:
            return False, "没找到包含「%s」的窗口" % title
        try:
            g.PostMessage(hwnd, con.WM_CLOSE, 0, 0)
            self._log("close_window", title)
            return True, "已发送关闭指令: " + title
        except Exception as e:
            return False, str(e)[:60]

