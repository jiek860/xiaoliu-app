# -*- coding: utf-8 -*-
"""电脑控制：应用启动、窗口枚举和窗口激活。"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from core import command_policy
from core.screen_geometry import screen_info, virtual_screen_rect

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class ComputerAppToolsMixin:
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

    def _launch_app_target(self, target, app=""):
        """按白名单校验后启动应用，禁止 shell=True。

        URI 用 os.startfile；lnk/bat/cmd 用系统关联；exe 用 argv 数组。
        任何带 shell 元字符的目标都直接拒绝。
        """
        ok, resolved = command_policy.validate_app_target(target)
        if not ok:
            return False, resolved
        try:
            low = str(resolved).lower()
            if low.startswith(command_policy.URI_PREFIXES):
                os.startfile(resolved)
            else:
                ext = os.path.splitext(str(resolved))[1].lower()
                if ext in (".lnk", ".bat", ".cmd"):
                    os.startfile(resolved)
                else:
                    subprocess.Popen([str(resolved)], shell=False,
                                     close_fds=True)
            self._log("open_app", "%s -> %s" % (app, resolved))
            return True, "已打开: " + (app or os.path.basename(str(resolved)))
        except Exception as e:
            return False, "启动失败: %s" % str(e)[:60]

    def open_app(self, app):
        """打开软件：先查常用表 -> 开始菜单 -> PATH，全部走白名单校验。"""
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
                    return self._launch_app_target(target, app)
            else:
                return self._launch_app_target(target, app)
        # 2. 开始菜单搜索
        path, score = self._search_startmenu(app)
        if path:
            return self._launch_app_target(path, app)
        # 3. PATH / 绝对路径兜底。绝不把用户输入直接交给 shell。
        exe = shutil.which(app)
        if exe:
            return self._launch_app_target(exe, app)
        candidate = os.path.abspath(os.path.expanduser(app))
        if os.path.isfile(candidate):
            return self._launch_app_target(candidate, app)
        return False, "没找到程序「%s」。试试：记事本/计算器/画图/浏览器/资源管理器" % app

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

    def get_active_window(self):
        """返回当前前台窗口标题；拿不到时返回空串。"""
        try:
            g, _, _ = self._win()
            if isinstance(g, Exception):
                return ""
            hwnd = g.GetForegroundWindow()
            return (g.GetWindowText(hwnd) or "").strip()
        except Exception:
            return ""
