# -*- coding: utf-8 -*-
from modules.base import BaseModule
"""电脑操作 v12.0 - 完整本地电脑操控
能力：打开应用/窗口管理/鼠标键盘/截屏/剪贴板/系统信息/文件白名单+确认
      + 开发者文件工具（读带行号 / 搜内容 / 精确替换并备份）
安全：文件操作限白名单，删除/关机等危险操作弹窗确认，全部动作留日志
"""
import os, re, time, json, shutil, subprocess
from datetime import datetime

class ComputerController(BaseModule):
    NAME = "computer_controller"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        # v16修复: 插件装到 modules/installed 后 __file__ 上推两级会错位到 modules/，
        # 导致白名单根目录与日志路径错位；优先用躯干的项目根
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.log_dir = os.path.join(self.base, "data", "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "computer_controller.log")
        self.whitelist = [
            self.base,

            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Documents"),
        ]
        # 允许用户在 config 里加白名单根目录，例如：
        #   "文件白名单": ["E:\\projects", "D:\\code"]
        # 不加的话 fs_read/fs_search 就只能读上面那四个根，用途很受限。
        try:
            for extra in (getattr(trunk, "config", {}) or {}).get("文件白名单", []) or []:
                if extra:
                    self.whitelist.append(os.path.expanduser(str(extra)))
        except Exception:
            pass
        # 常用软件表（名称 → 可执行/命令）
        self.known_apps = {
            "记事本": "notepad.exe", "notepad": "notepad.exe",
            "计算器": "calc.exe", "calculator": "calc.exe",
            "画图": "mspaint.exe", "mspaint": "mspaint.exe",
            "写字板": "write.exe", "wordpad": "write.exe",
            "命令提示符": "cmd.exe", "cmd": "cmd.exe", "命令行": "cmd.exe",
            "powershell": "powershell.exe",
            "任务管理器": "taskmgr.exe",
            "控制面板": "control.exe",
            "资源管理器": "explorer.exe", "此电脑": "explorer.exe",
            "设置": "ms-settings:",
            "截图工具": "snippingtool.exe", "截图": "snippingtool.exe",
            "浏览器": None,  # 运行时找默认浏览器
            "edge": None, "微软浏览器": None,
            "chrome": None, "谷歌浏览器": None,
            "steam": None,
            "qq": None, "微信": None,
            "word": None, "excel": None, "ppt": None, "wps": None,
        }

    # ---------- 基础 ----------
    def _log(self, action, detail="", ok=True, extra=""):
        try:
            line = "[%s] %s | 操作:%s | 详情:%s | 结果:%s %s" % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "✓" if ok else "✗", action, str(detail)[:120], "成功" if ok else "失败", extra)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except: pass

    def _enabled(self):
        """电脑控制总开关（聊天触发开关，GUI面板不受影响）"""
        if self.trunk:
            cfg = getattr(self.trunk, "config", {}) or {}
            return bool(cfg.get("电脑控制", True))
        return True

    def _confirm(self, action, detail):
        """危险操作确认：优先走 trunk.confirm（GUI 弹窗），无则放行；规则引擎可关"""
        try:
            if self.trunk and self.trunk.rule("电脑控制.覆盖确认", True) is False:
                return True  # 规则引擎关闭确认（仅限覆盖/写文件类；删文件/关机仍强制确认）
        except Exception:
            pass
        if self.trunk:
            try:
                return bool(self.trunk.confirm(action, detail))
            except Exception:
                pass
        return True

    def _check_path(self, path):
        """白名单检查（不区分大小写）"""
        path = os.path.normcase(os.path.abspath(path))
        return any(path.startswith(os.path.normcase(os.path.abspath(w))) for w in self.whitelist)

    def _safe_path(self, path):
        """把用户给的文件路径限制在白名单内；相对路径落到项目 data 目录"""
        p = path.strip().strip('"')
        if not p:
            return None
        p = os.path.expanduser(p)
        if not os.path.isabs(p):
            p = os.path.join(self.base, "data", p)
        p = os.path.abspath(p)
        return p if self._check_path(p) else None

    def _gui(self):
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1
            return pyautogui
        except Exception as e:
            return e

    def _win(self):
        try:
            import win32gui, win32con, win32api
            return win32gui, win32con, win32api
        except Exception as e:
            return e

    # ---------- 打开应用 / 程序 ----------
    def _find_default_browser(self):
        for exe in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]:
            if os.path.exists(exe):
                return exe
        for name in ["msedge.exe", "chrome.exe", "firefox.exe"]:
            w = shutil.which(name)
            if w:
                return w
        return None

    def _search_startmenu(self, name):
        """在开始菜单快捷方式里搜应用，返回 (路径, 匹配分)"""
        roots = [os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
                 r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"]
        best, best_score = None, 0
        name_l = name.lower()
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _, files in os.walk(root):
                for fn in files:
                    if fn.lower().endswith((".lnk", ".exe")):
                        stem = os.path.splitext(fn)[0].lower()
                        if stem == name_l:
                            score = 3
                        elif stem.startswith(name_l):
                            score = 2
                        elif name_l in stem:
                            score = 1
                        else:
                            continue
                        if score > best_score:
                            best_score = score
                            best = os.path.join(dirpath, fn)
                            if score == 3:
                                return best, score
        return best, best_score

    def open_app(self, app):
        """打开软件：先查常用表 → 开始菜单 → PATH → 直接启动"""
        if not self._enabled():
            return False, "电脑控制已关闭（设置里可打开）"
        app = (app or "").strip()
        if not app:
            return False, "要打开什么？比如：打开计算器"
        # 1. 常用表
        key = app.lower()
        if key in self.known_apps:
            target = self.known_apps[key]
            if target is None:  # 需要运行时确定
                if "浏览器" in key or key in ("edge", "chrome", "谷歌浏览器"):
                    target = self._find_default_browser()
                    if not target:
                        return False, "没找到浏览器"
                    subprocess.Popen([target], shell=False)
                    self._log("open_app", app)
                    return True, "已打开浏览器: " + os.path.basename(target)
            else:
                # Windows URI（如 ms-settings:）必须用 start 才能打开
                if str(target).startswith("ms-settings:"):
                    subprocess.Popen("start " + target, shell=True)
                else:
                    subprocess.Popen(target, shell=True)
                self._log("open_app", app)
                return True, "已打开: " + app
        # 2. 开始菜单搜索
        path, score = self._search_startmenu(app)
        if path:
            try:
                subprocess.Popen([path], shell=False)
                self._log("open_app", "%s -> %s" % (app, path))
                return True, "已打开: %s" % app
            except Exception as e:
                return False, "启动失败: %s" % str(e)[:60]
        # 3. PATH 直接命令
        exe = shutil.which(app)
        if exe or app.endswith(".exe"):
            try:
                subprocess.Popen(app if app.endswith(".exe") else exe, shell=True)
                self._log("open_app", app)
                return True, "已打开: " + app
            except Exception as e:
                return False, "启动失败: %s" % str(e)[:60]
        return False, "没找到程序「%s」。试试：记事本/计算器/画图/浏览器/资源管理器" % app

    # ---------- 窗口管理 ----------
    def _all_windows(self):
        """枚举可见窗口，返回 [(title, hwnd)]"""
        g, _, _ = self._win()
        if isinstance(g, Exception):
            return []
        out = []
        def cb(hwnd, _):
            if not g.IsWindowVisible(hwnd):
                return
            title = g.GetWindowText(hwnd)
            if title and title.strip():
                out.append((title.strip(), hwnd))
        g.EnumWindows(cb, None)
        return out

    def _find_window(self, title):
        """按标题模糊找窗口，返回 hwnd 或 None"""
        title_l = title.lower()
        for t, hwnd in self._all_windows():
            if title_l in t.lower():
                return hwnd
        return None

    def list_windows(self):
        wins = self._all_windows()
        if not wins:
            return ["（没有找到可见窗口）"]
        return [t for t, _ in wins]

    # ---------- UI 元素树（uiautomation）----------
    #
    # 为什么需要它：没有元素树时，GUI 操作只能"盲点坐标" ——
    # 要事先知道按钮在 (500, 300)，窗口一挪位置就失效，也没法说
    # "点那个叫『确定』的按钮"。接上 UI Automation 之后就能按**控件名/类型**
    # 定位，这是"详细操作程序"和"碰运气点坐标"的分界。
    #
    # 实测（本机 uiautomation 2.0.29）：
    #   GetRootControl()            0.29s
    #   枚举顶层窗口                 0.10s
    #   按类型找控件 searchDepth=6   0.04s
    # 所以每次调用都很快，但**深度搜索要限深限量**，否则在大程序里会慢。

    _UI_MAX = 40          # 单次最多返回多少个控件

    def _uia(self):
        """取 uiautomation 模块；没装就给出可操作的提示"""
        try:
            import uiautomation as auto
            return auto
        except Exception as e:
            return RuntimeError("没装 uiautomation（pip install uiautomation）: "
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
                except Exception:
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
        except Exception:
            pass
        try:
            for c in ctrl.GetChildren():
                self._ui_walk(c, want, ctype, found, depth - 1)
                if len(found) >= self._UI_MAX:
                    return
        except Exception:
            pass

    def _ui_window(self, title, a):
        """按名字子串找顶层窗口，返回窗口控件"""
        want = str(title or "").strip().lower()
        try:
            for w in a.GetRootControl().GetChildren():
                try:
                    if want in (w.Name or "").lower():
                        return w
                except Exception:
                    continue
        except Exception:
            pass
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
                r = c.BoundingRectangle
                lines.append("%s%s%s  @(%d,%d,%dx%d)"
                             % ("  " * d, tn,
                                ("  「%s」" % nm[:40]) if nm else "",
                                r.left, r.top, r.right - r.left, r.bottom - r.top))
            except Exception:
                return
            try:
                for ch in c.GetChildren():
                    walk(ch, d + 1)
            except Exception:
                pass

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
            except Exception:
                pass
            try:
                for ch in c.GetChildren():
                    walk(ch, d - 1)
                    if hit is not None:
                        return
            except Exception:
                pass

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
            except Exception:
                pass
            try:
                for ch in c.GetChildren():
                    walk(ch, d - 1)
                    if hit is not None:
                        return
            except Exception:
                pass

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

    # ---------- 鼠标键盘 ----------
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
        gui = self._gui()
        if isinstance(gui, Exception):
            return x, y
        w, h = gui.size()
        return max(0, min(w - 1, x)), max(0, min(h - 1, y))

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

    # ---------- 剪贴板 ----------
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

    # ---------- 截屏 ----------
    def screenshot(self, save_path=None, region=None, window_title=None):
        try:
            from PIL import ImageGrab
            if not save_path:
                save_path = os.path.join(self.base, "data", "screenshot_%s.png" % datetime.now().strftime("%Y%m%d_%H%M%S"))
            if window_title:
                g, _, _ = self._win()
                if not isinstance(g, Exception):
                    hwnd = self._find_window(window_title)
                    if hwnd:
                        try:
                            g.SetForegroundWindow(hwnd)
                        except: pass
                        time.sleep(0.3)
                        from win32gui import GetWindowRect
                        left, top, right, bottom = GetWindowRect(hwnd)
                        region = (left, top, right, bottom)
            if region:
                if isinstance(region, str):
                    xy = self._parse_xy(region)
                    if xy:
                        region = (0, 0, xy[0], xy[1])
                img = ImageGrab.grab(bbox=tuple(int(v) for v in region))
            else:
                img = ImageGrab.grab()
            img.save(save_path)
            self._log("screenshot", save_path)
            return True, "已截屏: " + save_path
        except Exception as e:
            return False, "截屏失败: %s" % str(e)[:60]

    # ---------- 系统信息 ----------
    def system_info(self):
        info = {}
        try:
            import psutil
            v = psutil.virtual_memory()
            info["内存"] = "已用 %d%% (%.1f/%.1f GB)" % (v.percent, v.used / 2**30, v.total / 2**30)
            info["CPU"] = "%d%%" % psutil.cpu_percent(interval=0.3)
            d = psutil.disk_usage(os.path.abspath(os.sep))
            info["磁盘"] = "已用 %d%% (剩 %.1f GB)" % (d.percent, d.free / 2**30)
            try:
                b = psutil.sensors_battery()
                if b:
                    info["电池"] = "%d%%%s" % (b.percent, "（充电中）" if b.power_plugged else "（未充电）")
            except: pass
        except Exception as e:
            info["错误"] = str(e)[:60]
        try:
            import platform
            info["系统"] = platform.system() + " " + platform.release()
        except: pass
        return True, info

    # ---------- 文件操作（白名单） ----------
    def list_dir(self, path=None):
        p = self._safe_path(path or self.base)
        if not p:
            return False, "路径不在白名单内（仅允许项目目录/桌面/下载/文档）"
        try:
            items = os.listdir(p)
            lines = []
            for it in sorted(items)[:50]:
                full = os.path.join(p, it)
                tag = "📁" if os.path.isdir(full) else "  "
                lines.append("%s %s" % (tag, it))
            return True, "目录 %s 共 %d 项：\n%s" % (p, len(items), "\n".join(lines))
        except Exception as e:
            return False, str(e)[:60]

    def create_file(self, path, content=""):
        p = self._safe_path(path)
        if not p:
            return False, "路径不在白名单内"
        # D4: 覆盖已存在文件必须弹窗确认（写错会丢数据）
        if os.path.exists(p) and not self._confirm("覆盖文件", p):
            return False, "已取消覆盖"
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            self._log("create_file", p)
            return True, "已创建文件: " + p
        except Exception as e:
            return False, str(e)[:60]

    def delete_file(self, path):
        p = self._safe_path(path)
        if not p:
            return False, "路径不在白名单内"
        if not os.path.exists(p):
            return False, "文件不存在: " + p
        if not self._confirm("删除文件", p):
            return False, "已取消删除"
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            self._log("delete_file", p, True, "已确认")
            return True, "已删除: " + p
        except Exception as e:
            return False, str(e)[:60]

    def copy_file(self, src, dst):
        s = self._safe_path(src)
        d = self._safe_path(dst)
        if not s or not d:
            return False, "路径不在白名单内"
        # D4: 覆盖已存在目标必须弹窗确认
        if os.path.exists(d) and not self._confirm("覆盖目标文件", d):
            return False, "已取消覆盖"
        try:
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
            self._log("copy_file", "%s -> %s" % (s, d))
            return True, "已复制: %s → %s" % (s, d)
        except Exception as e:
            return False, str(e)[:60]

    def move_file(self, src, dst):
        s = self._safe_path(src)
        d = self._safe_path(dst)
        if not s or not d:
            return False, "路径不在白名单内"
        # D4: 覆盖已存在目标必须弹窗确认
        if os.path.exists(d) and not self._confirm("覆盖目标文件", d):
            return False, "已取消覆盖"
        try:
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.move(s, d)
            self._log("move_file", "%s -> %s" % (s, d))
            return True, "已移动: %s → %s" % (s, d)
        except Exception as e:
            return False, str(e)[:60]

    # ---------- 开发者文件工具：读 / 搜 / 改 ----------
    #
    # 为什么加在这个模块里、而不是新建一个 file_tools 模块：
    # 白名单（self.whitelist）才是"AI 能碰哪些文件"的安全边界，
    # 另起模块就得复制一份白名单策略，两份策略迟早漂移 ——
    # 安全边界只该有一处定义。所以读/搜/改统一走这里的 _safe_path。

    _TEXT_EXT = (".py", ".md", ".txt", ".json", ".js", ".ts", ".html", ".css",
                 ".yml", ".yaml", ".toml", ".ini", ".cfg", ".bat", ".ps1",
                 ".vbs", ".sql", ".sh", ".log", ".csv", ".xml", ".jsx", ".tsx")
    _SKIP_DIRS = ("__pycache__", ".git", "node_modules", "libs", "optional_libs",
                  "backups", "staging", "browsers", ".venv", "venv", "dist",
                  "build", "data\\_trash_20261010")

    def read_text(self, path, start=1, limit=400):
        """读文件内容（带行号）

        必须支持只读一段 —— 长文件一次全读进来会直接塞爆上下文。
        返回 {"ok", "文件", "总行数", "范围", "内容"}。
        """
        p = self._safe_path(str(path or "").strip().strip('"'))
        if not p:
            return {"ok": False, "错误": "路径不在白名单内（仅允许项目目录/桌面/下载/文档；"
                                        "可在 config 的『文件白名单』里加根目录）"}
        if not os.path.isfile(p):
            return {"ok": False, "错误": "不是文件或不存在: " + p}
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception as e:
            return {"ok": False, "错误": "读失败: " + str(e)[:60]}
        try:
            start = max(1, int(start))
            limit = max(1, min(4000, int(limit)))
        except Exception:
            start, limit = 1, 400
        seg = lines[start - 1:start - 1 + limit]
        numbered = "\n".join("%5d| %s" % (start + i, s) for i, s in enumerate(seg))
        self._log("read_text", "%s [%d,%d]" % (p, start, start + len(seg) - 1))
        return {"ok": True, "文件": p, "总行数": len(lines),
                "范围": "%d-%d" % (start, start + len(seg) - 1),
                "内容": numbered}

    def search_text(self, keyword, path=None, max_hits=60):
        """在目录里搜文件内容，返回「文件:行号: 内容」

        纯 Python 实现（os.walk + re），不引入新依赖。
        只搜文本类扩展名、跳过依赖/备份/缓存目录、跳过 >2MB 的大文件。
        """
        kw = str(keyword or "").strip()
        if not kw:
            return {"ok": False, "错误": "没给关键词"}
        root = self._safe_path(str(path).strip()) if path else self.base
        if not root or not os.path.isdir(root):
            return {"ok": False, "错误": "目录不在白名单内或不存在: " + str(path)}
        try:
            pat = re.compile(kw, re.I)
        except Exception:
            pat = re.compile(re.escape(kw), re.I)

        hits, scanned = [], 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in self._SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if not fn.lower().endswith(self._TEXT_EXT):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(fp) > 2 * 1024 * 1024:
                        continue
                except Exception:
                    continue
                scanned += 1
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if pat.search(line):
                                hits.append("%s:%d: %s"
                                            % (os.path.relpath(fp, root), i, line.strip()[:120]))
                                if len(hits) >= max_hits:
                                    raise StopIteration
                except StopIteration:
                    break
                except Exception:
                    continue
            if len(hits) >= max_hits:
                break
        self._log("search_text", "%s in %s -> %d 命中" % (kw, root, len(hits)))
        return {"ok": True, "根目录": root, "扫描文件数": scanned,
                "命中数": len(hits), "结果": hits}

    def edit_text(self, spec):
        """精确替换文件内容（改前自动备份）

        spec 可以是 dict，也可以是 JSON 字符串（工具调用只传得进一个参数，
        见 tool_caller 的分发方式）：
            {"path": "a.py", "old": "原文", "new": "新文"}
        安全规则：old 必须在文件里**恰好出现一次** —— 出现 0 次或多次都拒绝，
        免得改错地方。这是 DSH edit 的核心语义，比"整体重写文件"安全得多。
        """
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except Exception as e:
                return {"ok": False, "错误": "参数不是合法 JSON: " + str(e)[:50]}
        if not isinstance(spec, dict):
            return {"ok": False, "错误": "参数应为 {path, old, new}"}
        p = self._safe_path(str(spec.get("path", "")).strip().strip('"'))
        old = spec.get("old", "")
        new = spec.get("new", "")
        if not p:
            return {"ok": False, "错误": "路径不在白名单内"}
        if not old:
            return {"ok": False, "错误": "old 不能为空（空串会匹配到任何位置）"}
        if not os.path.isfile(p):
            return {"ok": False, "错误": "文件不存在: " + p}
        try:
            content = open(p, encoding="utf-8").read()
        except Exception as e:
            return {"ok": False, "错误": "读失败: " + str(e)[:60]}
        n = content.count(old)
        if n == 0:
            return {"ok": False, "错误": "原文没找到（注意缩进和换行要完全一致）"}
        if n > 1:
            return {"ok": False, "错误": "原文出现 %d 次，不唯一；请多带几行上下文让它唯一" % n}
        # 备份
        try:
            bdir = os.path.join(self.base, "data", "backups")
            os.makedirs(bdir, exist_ok=True)
            bp = os.path.join(bdir, "%s.%s.bak"
                              % (os.path.basename(p), time.strftime("%Y%m%d_%H%M%S")))
            shutil.copy2(p, bp)
        except Exception as e:
            return {"ok": False, "错误": "备份失败，已放弃修改: " + str(e)[:50]}
        try:
            open(p, "w", encoding="utf-8").write(content.replace(old, new, 1))
        except Exception as e:
            return {"ok": False, "错误": "写入失败: " + str(e)[:60], "备份": bp}
        line_no = content[:content.index(old)].count("\n") + 1
        self._log("edit_text", "%s @L%d" % (p, line_no))
        return {"ok": True, "文件": p, "行": line_no, "备份": bp}

    def try_file(self, text):
        """文件工具的统一入口（收一句话自己解析）

        和 computer_controller.try_handle 同一形状 —— tool_caller 分发时
        只传 list(args.values())[0]，第二个参数传不进来。
        """
        t = str(text or "").strip()
        if not t:
            return {"ok": False, "错误": "没给指令"}
        # 改文件：{"path":…,"old":…,"new":…} 直接吃 JSON
        m = re.search(r"\{.*\}", t, re.S)
        if m and re.search(r"替换|改|修改|edit", t):
            return self.edit_text(m.group(0))
        # 搜内容
        m = re.search(r"(?:搜索|搜|查找|找一下|grep)\s*[：:]?\s*(.+)$", t)
        if m:
            kw = m.group(1).strip().strip('"')
            return self.search_text(kw)
        # 读文件
        m = re.search(r"(?:读|看看|打开|查看|read)\s*[：:]?\s*(.+)$", t)
        if m:
            return self.read_text(m.group(1).strip().strip('"'))
        return {"ok": False, "错误": "没听懂这条文件指令: " + t[:40],
                "可用": "读<路径> / 搜索<关键词> / 替换<JSON:{path,old,new}>"}

    def open_path(self, path):
        p = self._safe_path(path)
        if p and os.path.exists(p):
            try:
                os.startfile(p)
                self._log("open_path", p)
                return True, "已打开: " + p
            except Exception as e:
                return False, str(e)[:60]
        if p:
            return False, "路径不存在: " + p
        return False, "路径不在白名单内"

    def open_url(self, url):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            os.startfile(url)
            self._log("open_url", url)
            return True, "已在浏览器打开: " + url
        except Exception as e:
            return False, str(e)[:60]

    # ---------- 危险系统操作 ----------
    def shutdown(self, delay=30):
        if not self._danger_enabled("关机"):
            self._log("关机", "功能已禁用(规则引擎)", True)
            return False, "关机功能已禁用（可在规则引擎开启 电脑控制.允许关机）"
        if not self._confirm("关机", "系统将在 %d 秒后关机（执行 shutdown /s）" % delay):
            return False, "已取消关机"
        try:
            subprocess.Popen("shutdown /s /t %d" % int(delay), shell=True)
            self._log("shutdown", "delay=%d" % delay, True, "已确认")
            return True, "已安排 %d 秒后关机（可运行 shutdown /a 取消）" % int(delay)
        except Exception as e:
            return False, str(e)[:60]

    def restart(self, delay=30):
        if not self._danger_enabled("重启"):
            self._log("重启", "功能已禁用(规则引擎)", True)
            return False, "重启功能已禁用（可在规则引擎开启 电脑控制.允许关机）"
        if not self._confirm("重启", "系统将在 %d 秒后重启（执行 shutdown /r）" % delay):
            return False, "已取消重启"
        try:
            subprocess.Popen("shutdown /r /t %d" % int(delay), shell=True)
            self._log("restart", "delay=%d" % delay, True, "已确认")
            return True, "已安排 %d 秒后重启（可运行 shutdown /a 取消）" % int(delay)
        except Exception as e:
            return False, str(e)[:60]

    def cancel_shutdown(self):
        try:
            subprocess.Popen("shutdown /a", shell=True)
            self._log("cancel_shutdown", "", True)
            return True, "已取消关机/重启计划"
        except Exception as e:
            return False, str(e)[:60]

    # ---------- 状态 ----------
    def status(self):
        return {
            "白名单目录数": len(self.whitelist),
            "总开关(聊天触发)": "开" if self._enabled() else "关",
            "能力": "打开应用/窗口管理/鼠标键盘/截屏/剪贴板/系统信息/文件管理",
            "日志": self.log_path,
        }

    # ---------- 自然语言命令解析 ----------
    # 常见站点中文名 -> 域名。「打开百度」原来会走 open_app 去找一个叫"百度"的程序。
    _SITE_ALIAS = {
        "百度": "baidu.com", "谷歌": "google.com", "必应": "bing.com",
        "淘宝": "taobao.com", "京东": "jd.com", "知乎": "zhihu.com",
        "微博": "weibo.com", "哔哩哔哩": "bilibili.com", "b站": "bilibili.com",
        "贴吧": "tieba.baidu.com", "豆瓣": "douban.com", "网易": "163.com",
        "腾讯": "qq.com", "github": "github.com", "csdn": "csdn.net",
    }

    @staticmethod
    def _looks_path(s):
        """判断一段文字是不是"路径/文件名"而不是"要复制的文本"

        用在"复制 X 到 Y"的歧义上：
            「复制 D:\\a.txt 到 D:\\b.txt」 -> 路径 -> copy_file
            「复制 你好 到 剪贴板」        -> 不是路径 -> clipboard_set
        判据：含路径分隔符，或看起来有扩展名（.txt / .py / .png …）。
        """
        s = str(s or "").strip().strip("\"'")
        if not s:
            return False
        if re.search(r"[\\/]", s):
            return True
        return bool(re.search(r"\.[A-Za-z0-9]{1,6}$", s))

    def parse(self, text):
        """把用户的话解析成 (action, kwargs)；不匹配返回 None"""
        if not text:
            return None
        t = text.strip()
        tl = t.lower()
        # ============ UI 元素树指令（先于坐标类，因为"按名字点"比"点坐标"精确）============
        # 「点击名为确定的按钮」/「点击确定按钮」——按控件名点，不依赖坐标
        m = re.search(r"(?:点击|点一下|单击|按下)\s*(?:名为|名叫|叫做)?\s*[「\"']?"
                      r"([^」\"'，。]{1,24}?)[」\"']?\s*的?\s*"
                      r"(按钮|链接|菜单|选项|标签|输入框|控件)", t)
        if m:
            nm = m.group(1).strip()
            ct = {"按钮": "ButtonControl", "链接": "HyperlinkControl",
                  "菜单": "MenuItemControl", "选项": "ListItemControl",
                  "标签": "TabItemControl", "输入框": "EditControl",
                  "控件": ""}.get(m.group(2), "")
            return ("ui_click", {"name": nm, "control_type": ct or None})
        # 「看看记事本的控件」/「列出窗口结构」
        m = re.search(r"(?:看看|查看|列出|dump|显示)\s*[「\"']?([^」\"'，。]{1,24})[」\"']?\s*的?\s*"
                      r"(?:控件|界面结构|元素树|结构)", t)
        if m:
            return ("ui_dump", {"window": m.group(1).strip(), "depth": 3})
        if re.search(r"(界面结构|元素树|控件树|窗口结构)", t):
            return ("ui_dump", {"depth": 2})
        # 找控件 / 列出窗口（元素树版）
        m = re.search(r"(?:列出?|看看|查看)\s*(?:当前)?\s*(?:所有)?\s*窗口", t)
        if m:
            return ("ui_windows", {})
        # 「在搜索框里输入 你好」——按控件名输入
        m = re.search(r"(?:在|往)\s*[「\"']?([^」\"'，。]{1,24}?)[」\"']?\s*(?:框|控件)?\s*"
                      r"(?:里|中)?\s*(?:输入|填|打)\s*(.+)$", t)
        if m:
            return ("ui_type", {"name": m.group(1).strip(), "text": m.group(2).strip()})
        # 执行命令：「执行 git status」/「运行命令 dir」
        m = re.search(r"(?:执行命令|运行命令|跑命令|cmd|shell)\s*[：:]?\s*(.+)$", t, re.I)
        if m:
            return ("shell", {"cmd": m.group(1).strip()})
        # 打开网址/网站
        m = re.search(r"(?:打开|访问|去|上)\s*(?:网址|网站|网页)\s*[：: ]?\s*([\w\.\-:/]{4,80})", t)
        if m:
            return ("open_url", {"url": m.group(1).strip()})
        m = re.search(r"https?://[^\s，。]+", t)
        if m:
            return ("open_url", {"url": m.group(0).strip()})
        # 「打开 某网站」——原来只认带 http:// 的、"打开网站 X"这两种说法，
        # 于是「打开百度」「打开 github.com」都掉进下面的 open_app 分支，
        # 去找一个叫"百度"的程序（必然找不到）。这里补两条：
        #   域名形态（x.y.zz）直接按网址开；常见站点中文名走别名表。
        m = re.search(r"(?:打开|访问|去|上)\s*((?:[\w\-]+\.)+[A-Za-z]{2,6}(?:/[^\s，。]*)?)", t)
        if m:
            return ("open_url", {"url": m.group(1).strip()})
        m = re.search(r"(?:打开|访问|去|上)\s*(百度|谷歌|必应|淘宝|京东|知乎|微博|"
                      r"哔哩哔哩|b站|贴吧|豆瓣|网易|腾讯|github|csdn)", t, re.I)
        if m:
            k = m.group(1)
            return ("open_url", {"url": self._SITE_ALIAS.get(k)
                                 or self._SITE_ALIAS.get(k.lower()) or k})
        # 打开/查看 文件路径（先于应用，避免 "打开 E:\x" 被当成应用名）
        m = re.search(r"(?:打开|看看|浏览|查看|列出).{0,8}([A-Za-z]:\\[^\s，。]*)", t)
        if m:
            p = m.group(1).strip()
            if re.search(r"里有什么|有什么|有哪些|里面|列出|浏览|查看", t):
                return ("list_dir", {"path": p})
            return ("open_path", {"path": p}) if os.path.exists(self._safe_path(p) or p) else ("list_dir", {"path": p})
        m = re.search(r"(?:列出|看看|浏览|查看).{0,4}(?:目录|文件夹)", t)
        if m:
            return ("list_dir", {"path": None})
        # 打开应用
        m = re.search(r"(?:打开|启动|运行|开一下|帮我开)\s*([\w\u4e00-\u9fff\-\. ]{1,30})", t)
        if m and not re.search(r"网址|网站|文件|文件夹|目录|url", m.group(1)) \
                and ":" not in m.group(1) and "\\" not in m.group(1):
            return ("open_app", {"app": m.group(1).strip()})
        # 窗口
        m = re.search(r"(?:关闭|最小化|激活|切到|切换)\s*(?:窗口)?\s*[:：]?\s*([\w\u4e00-\u9fff\-\. ]{1,30})", t)
        if m and re.search(r"关闭|最小化|激活|切换|切到", t):
            wname = m.group(1).strip()
            if "关闭" in t:
                return ("close_window", {"title": wname})
            if "最小化" in t:
                return ("minimize_window", {"title": wname})
            return ("activate_window", {"title": wname})
        if re.search(r"列出?.*(窗口|运行中)|正在运行", t):
            return ("list_windows", {})
        # 截屏
        if re.search(r"截屏|截图|屏幕快照", t):
            return ("screenshot", {})
        # 鼠标（右键/双击先于普通点击判断）
        if re.search(r"右键\s*(?:点击|单击)?", t):
            m = re.search(r"[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
            return ("mouse_click", {"x": int(m.group(1)), "y": int(m.group(2)), "button": "right"}) if m else ("mouse_click", {"button": "right"})
        if re.search(r"双击", t):
            m = re.search(r"[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
            return ("mouse_click", {"x": int(m.group(1)), "y": int(m.group(2)), "clicks": 2}) if m else ("mouse_click", {"clicks": 2})
        m = re.search(r"鼠标\s*(?:移动)?\s*到?\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
        if m:
            return ("mouse_move", {"x": int(m.group(1)), "y": int(m.group(2))})
        m = re.search(r"移动到?\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
        if m:
            return ("mouse_move", {"x": int(m.group(1)), "y": int(m.group(2))})
        m = re.search(r"(?:拖动|拖拽)\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?\s*(?:到|->|至)\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
        if m:
            return ("mouse_drag", {"x1": int(m.group(1)), "y1": int(m.group(2)), "x2": int(m.group(3)), "y2": int(m.group(4))})
        m = re.search(r"(?:单击|点击|点一下)\s*[（(]?\s*([\-\d]+)\s*[,，\s]\s*([\-\d]+)\s*[)）]?", t)
        if m:
            return ("mouse_click", {"x": int(m.group(1)), "y": int(m.group(2))})
        if re.search(r"滚动", t):
            m = re.search(r"滚动\s*([\-\d]+)?", t)
            n = int(m.group(1)) if m and m.group(1) else 3
            return ("mouse_scroll", {"clicks": n})
        if re.search(r"鼠标.*(?:位置|坐标)|鼠标在哪", t):
            return ("mouse_pos", {})
        # 键盘
        m = re.search(r"(?:输入|打字|打出)\s*[：:]?\s*(.+)$", t)
        if m:
            return ("type_text", {"text": m.group(1).strip()})
        m = re.search(r"(?:按下|按)\s*([a-zA-Z]+(?:\+[a-zA-Z0-9]+)+)", t)
        if m:
            return ("hotkey", {"keys": m.group(1).strip()})
        m = re.search(r"快捷键?\s*[：:]?\s*([\w\-\+ ]{2,20})", t)
        if m:
            return ("hotkey", {"keys": m.group(1).strip()})
        m = re.search(r"按(?:一下)?\s*(enter|回车|esc|delete|空格|tab|方向键上|方向键下|方向键左|方向键右|up|down|left|right)\b", t)
        if m:
            key = {"enter": "enter", "回车": "enter", "esc": "esc", "delete": "delete",
                   "空格": "space", "tab": "tab", "方向键上": "up", "方向键下": "down",
                   "方向键左": "left", "方向键右": "right"}[m.group(1)]
            return ("press_key", {"key": key})
        # ============ 文件操作（必须排在剪贴板之前）============
        #
        # 原来顺序是反的：clipboard_set 的规则 `(?:复制|拷贝)\s*(.+?)\s*(?:到剪贴板)?$`
        # 贪婪匹配任何含"复制"的话，而且排在 copy_file 前面，于是
        #     「复制 a.txt 到 b.txt」-> clipboard_set({'text': 'a.txt 到 b.txt'})
        # 即：想复制文件，结果只改了剪贴板，还回一句"已复制到剪贴板: a.txt 到 b.txt"，
        # 看起来像成功了。copy_file 因此永远不可达（死规则）。
        # 另外这几条原本都要求 [A-Za-z]:\\ 盘符，相对路径/裸文件名一律不认。
        #
        # 现在：文件和剪贴板用 _looks_path 区分 —— 两端都像路径才是文件操作，
        # 目标是"剪贴板"或不像路径就还是剪贴板。
        m = re.search(r"(?:复制|拷贝)\s*[：:]?\s*(.+?)\s*(?:到|至)\s*(.+?)\s*$", t)
        if m:
            src, dst = m.group(1).strip(), m.group(2).strip()
            if dst in ("剪贴板", "粘贴板", "clipboard"):
                return ("clipboard_set", {"text": src})
            if self._looks_path(src) and self._looks_path(dst):
                return ("copy_file", {"src": src, "dst": dst})
        m = re.search(r"(?:移动|剪切)\s*[：:]?\s*(.+?)\s*(?:到|至)\s*(.+?)\s*$", t)
        if m:
            src, dst = m.group(1).strip(), m.group(2).strip()
            if self._looks_path(src) and self._looks_path(dst):
                return ("move_file", {"src": src, "dst": dst})
        m = re.search(r"(?:创建|新建)\s*(?:一个)?\s*文件\s*[：:]?\s*([^\s，。]+)"
                      r"\s*(?:内容[：:]?\s*(.+))?$", t)
        if m:
            return ("create_file", {"path": m.group(1).strip(),
                                    "content": (m.group(2) or "").strip()})
        m = re.search(r"(?:删除|删掉)\s*(?:文件|文档)?\s*[：:]?\s*([^\s，。]+)", t)
        if m and self._looks_path(m.group(1)):
            return ("delete_file", {"path": m.group(1).strip()})
        # 剪贴板（放在文件操作之后，只兜"把这段文字复制起来"这类）
        if re.search(r"剪贴板.*(?:有什么|内容|是什么)", t):
            return ("clipboard_get", {})
        m = re.search(r"(?:复制|拷贝|复制一下)\s*[：:]?\s*(.+?)\s*(?:到剪贴板)?\s*$", t)
        if m:
            return ("clipboard_set", {"text": m.group(1).strip()})
        # 系统信息
        if re.search(r"系统信息|电脑状态|系统状态|cpu|内存|磁盘|电池|硬件", t):
            return ("system_info", {})
        # 取消关机/重启（必须在“关机/重启”之前判断，否则“取消关机”会被误判成关机）
        if re.search(r"取消.*(关机|重启)", t):
            return ("cancel_shutdown", {})
        # 关机重启
        if re.search(r"关机", t):
            m = re.search(r"关机\s*(?:delay|延迟)?\s*(\d+)?", t)
            return ("shutdown", {"delay": int(m.group(1)) if m and m.group(1) else 30})
        if re.search(r"重启", t):
            m = re.search(r"重启\s*(\d+)?", t)
            return ("restart", {"delay": int(m.group(1)) if m and m.group(1) else 30})
        # 文件操作已上移到剪贴板之前（原来放这儿会被"复制…"的剪贴板规则截胡，
        # 且只认 [A-Za-z]:\ 绝对路径）。见本方法开头的 _looks_path 那段。
        return None

    # ---------- 命令执行（严格白名单，默认关闭）----------
    #
    # 设计取舍：code_runner 那边用"黑名单"挡危险代码
    #   dangerous = ["os.system", "subprocess", "shutil.rmtree", "open(", "eval(", "exec("]
    # 那套有两个毛病：① 字符串黑名单本身可绕过（getattr(os,"sys"+"tem")）；
    # ② 会误伤正常代码（open("a.txt").read() 直接被杀）。
    # 所以这里反过来做**白名单**，并且：
    #   · 默认关闭（规则「电脑控制.允许命令」默认 False，要用得显式打开）
    #   · 每条命令都要弹窗确认，和删文件同一级别
    #   · 拒绝一切串联/重定向（&& || | ; > < & ` $( ），只允许单条命令
    #   · 完整日志：命令 + 退出码 + 输出前若干字
    _SHELL_ALLOW = (
        # —— 只读/查询类 ——
        "dir", "type", "where", "tasklist", "whoami", "hostname", "ver",
        "ipconfig", "systeminfo", "tree", "findstr", "more", "fc",
        "python", "py", "git", "pip", "node", "npm", "pytest", "ruff",
        "ffmpeg", "curl", "ping", "nslookup", "netstat", "wmic", "reg",
    )
    # 任何串联/重定向/替换符一律拒绝 —— 单条命令是可控的前提
    _SHELL_META = ("&&", "||", "|", ";", ">", "<", "&", "`", "$(", "%(", "\n", "\r")

    def _shell_enabled(self):
        """命令执行总开关（规则引擎，默认关闭）"""
        try:
            if self.trunk:
                return bool(self.trunk.rule("电脑控制.允许命令", False))
        except Exception:
            pass
        return False

    def shell(self, cmd):
        """执行一条白名单内的命令

        默认**关闭**。要开启：data/rules/rules.json 里把
        「电脑控制.允许命令」的 value 改成 true（或在规则界面里开）。
        """
        c = str(cmd or "").strip()
        if not c:
            return {"ok": False, "错误": "没给命令"}
        if not self._shell_enabled():
            return {"ok": False,
                    "错误": "命令执行已禁用（规则引擎：电脑控制.允许命令 = false）",
                    "怎么开": "data/rules/rules.json 里把该规则 value 设为 true"}
        for meta in self._SHELL_META:
            if meta in c:
                return {"ok": False,
                        "错误": "不允许串联/重定向（检测到 %r）；一次只跑一条命令" % meta}
        first = re.split(r"\s+", c, 1)[0].lower()
        first = os.path.basename(first)
        if first.endswith(".exe"):
            first = first[:-4]
        if first not in self._SHELL_ALLOW:
            return {"ok": False,
                    "错误": "命令 %r 不在白名单内" % first,
                    "白名单": list(self._SHELL_ALLOW)}
        if not self._confirm("执行命令", c[:200]):
            return {"ok": False, "错误": "已取消"}
        t0 = time.time()
        try:
            r = subprocess.run(c, shell=True, capture_output=True, text=True,
                               timeout=60, cwd=self.base,
                               encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            self._log("shell", "%s -> 超时" % c[:80], True)
            return {"ok": False, "错误": "命令超过 60 秒未结束，已放弃"}
        except Exception as e:
            self._log("shell", "%s -> %s" % (c[:80], str(e)[:40]), True)
            return {"ok": False, "错误": str(e)[:80]}
        out = ((r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else ""))[:4000]
        self._log("shell", "%s -> exit=%s" % (c[:80], r.returncode), True,
                  "确认执行" if r.returncode == 0 else "非零退出")
        return {"ok": r.returncode == 0, "命令": c, "退出码": r.returncode,
                "耗时": round(time.time() - t0, 2), "输出": out}

    def _danger_enabled(self, action):
        """关机/重启默认禁用，规则引擎可开启（电脑控制.允许关机）"""
        try:
            if self.trunk:
                return bool(self.trunk.rule("电脑控制.允许关机", False))
        except Exception:
            pass
        return False

    def execute(self, action, kwargs):
        fn = getattr(self, action, None)
        if not fn:
            return False, "未知操作: " + action
        try:
            return fn(**kwargs)
        except Exception as e:
            return False, "执行失败: %s" % str(e)[:80]

    def try_handle(self, text):
        """聊天入口：能解析则执行并返回 (True, 结果文本)，否则 (False, None)"""
        if not self._enabled():
            return False, None
        parsed = self.parse(text)
        if not parsed:
            return False, None
        action, kwargs = parsed
        ok, result = self.execute(action, kwargs)
        if isinstance(result, dict):
            result = "\n".join("%s: %s" % (k, v) for k, v in result.items())
        return True, str(result)

    def run(self, action="", *args, **kwargs):
        """统一入口（工具调用/GUI 按钮）：传文本则解析执行，传 (action, kwargs) 则直接执行"""
        if isinstance(action, dict):
            kwargs = dict(action)
            action = kwargs.pop("action", "")
        if args:
            return self.try_handle(args[0])
        if action:
            if kwargs:
                return self.execute(action, kwargs)
            ok, r = self.try_handle(action)
            return r if ok else {"error": r}
        return self.status()

    def status_line(self):
        return "电脑控制 v11.0 已就绪 | 白名单目录: %d | 日志: %s" % (len(self.whitelist), self.log_path)

    # ========== 新增：操作记录 + 安全边界 + 视觉理解 ==========
    def get_action_history(self, count=10):
        """操作记录：记录做了什么，能撤销"""
        try:
            with open(self.log_path, encoding="utf-8") as f:
                lines = f.readlines()
            return {"最近操作": [l.strip()[:80] for l in lines[-count:]]}
        except:
            return {"操作记录": "无"}

    def safety_check(self, action):
        """安全边界：防止AI误删文件/误操作"""
        # 原来这张表里有 "shutdown" 和 "reboot"，但重启的方法是 restart ——
        # "reboot" in "restart" 是 False，于是 restart 一直被漏判成"不危险"。
        dangerous = ["delete", "remove", "format", "shutdown", "reboot",
                     "restart", "rmtree"]
        for d in dangerous:
            if d in str(action).lower():
                return {"危险": True, "操作": action, "提示": "这个操作很危险，需要确认"}
        return {"危险": False}

    def vision_understand(self, screenshot_path):
        """视觉理解：截图后让AI看懂屏幕内容再操作"""
        multimodal = self.trunk.modules.get("multimodal")
        if not multimodal:
            return {"错误": "多模态模块未加载"}
        return multimodal.describe_image(screenshot_path)


