# -*- coding: utf-8 -*-
"""工作台顶部命令中心（批次 44.4 从 ide_sidebar 拆出）。

为什么单独拆
------------
`ide_sidebar.py` 已经 591 行，再塞 NL 命令会越过 600 行硬上限；命令中心
本来就不依赖侧栏视图，拆出来职责更清。旧导入路径依旧可用：
``from gui.ide_sidebar import CommandCenterMixin``（那边 re-export）。

执行顺序：精确命令 → 模糊命令 → NL 意图 → 文件名。
NL 默认 shadow：只记影子日志，继续走旧的“按文件名打开”，行为不变。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCompleter

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
              "modules_repo", "dist", "build", ".pytest_cache"}

_COMMANDS = ("新建文件", "打开文件", "保存", "另存为", "运行当前文件",
             "搜索工作区", "源代码管理", "资源管理器", "输出", "终端",
             "插件市场", "AI 面板", "分屏", "minimap", "全屏")


def find_file(root, needle):
    """按文件名找第一个匹配；跳过依赖/缓存目录。"""
    needle = needle.casefold()
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in _SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if needle in fn.casefold():
                    return os.path.join(dirpath, fn)
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "find file by name")
    return ""


class CommandCenterMixin:
    """顶部命令中心：一个 QLineEdit 覆盖高频动作，兼按文件名打开。

    宿主窗口需要提供 `command / root / status_label / _editor` 和
    `_show_* / _open_extensions / toggle_fullscreen`。
    """

    def _setup_command_completer(self):
        try:
            comp = QCompleter(list(_COMMANDS), self.command)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            self.command.setCompleter(comp)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "command completer")

    def _focus_command(self):
        self.command.setFocus()
        self.command.selectAll()

    def _command_items(self):
        ed = self._editor
        return [
            ("新建文件", lambda: ed and ed.new_tab()),
            ("打开文件", lambda: ed and ed.open_file()),
            ("保存", lambda: ed and ed.save_file()),
            ("另存为", lambda: ed and ed.save_as()),
            ("运行当前文件", lambda: ed and ed.run_current()),
            ("搜索工作区", self._show_search),
            ("源代码管理", self._show_scm),
            ("资源管理器", self._show_explorer),
            ("输出", self._show_output),
            ("终端", self._show_terminal),
            ("插件市场", self._open_extensions),
            ("AI 面板", self._show_ai),
            ("分屏", lambda: ed and ed.toggle_split()),
            ("minimap", lambda: ed and ed.toggle_minimap()),
            ("全屏", self.toggle_fullscreen),
        ]

    def _run_command(self):
        """回车执行：精确命令 → 模糊命令 → NL 意图 → 文件名。"""
        text = self.command.text().strip()
        if not text:
            return
        low = text.casefold()
        items = self._command_items()
        for name, fn in items:
            if low == name.casefold():
                self.command.clear()
                fn()
                return
        for name, fn in items:
            if low in name.casefold():
                self.command.clear()
                fn()
                return
        if self._run_nl(text):
            return
        path = find_file(self.root, text)
        if path:
            self.command.clear()
            self.open_path(path)
            self.status_label.setText("已打开 %s" % os.path.basename(path))
        else:
            self.status_label.setText("未找到命令或文件：%s" % text)

    # ── NL 意图（批次 44.4） ──
    def _nl_context(self):
        """当前文件 / 选区，用来少问一句。"""
        ctx = {}
        try:
            ed = getattr(self, "_editor", None)
            cur = ed.tabs.currentWidget() if ed is not None else None
            path = str(getattr(cur, "filepath", "") or "")
            root = os.path.abspath(self.root)
            if path and os.path.abspath(path).startswith(root):
                ctx["current_file"] = os.path.relpath(
                    path, root).replace("\\", "/")
            if cur is not None and hasattr(cur, "textCursor"):
                ctx["selection"] = cur.textCursor().selectedText()[:200]
        except Exception as e:
            _x6_swallowed(__name__, e, "nl context")
        return ctx

    def _run_nl(self, text):
        """返回 True 表示已处理；False 交回旧的文件名逻辑。"""
        trunk = getattr(self, "trunk", None)
        if trunk is None:
            return False
        try:
            from core.nl.command import plan_command
            from core.nl.intent import mode, record_shadow
            how = mode(trunk)
            if how == "off":
                return False
            result = plan_command(text, root=self.root,
                                  context=self._nl_context())
            if how == "shadow":
                record_shadow(trunk, result.get("info") or {}, text)
                return False
            return self._apply_nl(result, text)
        except Exception as e:
            _x6_swallowed(__name__, e, "command center nl")
            return False

    def _apply_nl(self, result, text):
        kind = result.get("kind")
        if kind == "file":
            return False
        self.command.clear()
        if kind in ("clarify", "not_found"):
            self.status_label.setText(
                result.get("question") or result.get("message") or "")
            return True
        if kind != "nl":
            return False
        action = result.get("action") or {}
        name = action.get("action")
        if name == "open":
            path = self._abs(action.get("path"))
            self.open_path(path)
            self.status_label.setText("已打开 %s" % os.path.basename(path))
        elif name == "run_test":
            path = self._abs(action.get("path"))
            if path:
                self.open_path(path)
            ed = getattr(self, "_editor", None)
            if ed is not None and hasattr(ed, "run_current"):
                ed.run_current()
            self.status_label.setText(
                "运行测试：%s" % (os.path.basename(path) if path else "当前文件"))
        elif name == "search":
            self._show_search()
            view = getattr(self, "search_view", None)
            if view is not None and hasattr(view, "query"):
                view.query.setText(action.get("query") or "")
            self.status_label.setText(
                "搜索：%s（回车开始）" % (action.get("query") or ""))
        elif name == "ai":
            goal = action.get("goal") or text
            if hasattr(self, "set_goal"):
                self.set_goal(goal)
            self._show_ai()
            self.status_label.setText("AI 已接收：%s" % action.get("intent", ""))
        elif name == "undo":
            from core.nl.command import undo_last
            res = undo_last(self.root)
            if res.get("ok"):
                self.status_label.setText(
                    "已撤销 %d 个文件" % len(res.get("restored") or []))
            else:
                self.status_label.setText("撤销失败：%s" % (res.get("error") or ""))
        else:
            return False
        return True

    def _abs(self, path):
        path = str(path or "")
        if not path:
            return ""
        return path if os.path.isabs(path) else os.path.join(self.root, path)
