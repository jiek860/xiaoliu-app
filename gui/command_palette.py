# -*- coding: utf-8 -*-
"""⌘ 命令面板（Ctrl+K）—— 一个搜索框取代一排按钮

为什么要有它
------------
实测（2026-10-13）GUI 里有 114 处控件创建，其中"实用工具"面板一个人就占 24 个
按钮，而那 24 条能力里 **23 条其实"说一句"就能用** —— 只是当时没有统一的调用入口，
只能一个功能配一个按钮。

这个面板把三类入口收进**一个可搜索的列表**：
    ① 能力注册表里的能力（core/module_caps）—— 模块自己声明就自动出现，不用手写表
    ② 主窗口能打开的面板（设置里那 19 个）
    ③ 极少数必须走对话框的（比如加密导出要输密码，密码不能进聊天日志）

它是"撤按钮"的前提：**先有替代入口，再撤**，否则用户找不到功能。

设计约束
--------
· 能力执行**复用 tool_caller._dispatch** —— readonly/confirm/danger 那套安全分级
  只有一处实现，面板不另起一套
· 所有动作在后台线程跑（BgWorker），界面不卡
· 任何异常只影响这一次执行，不崩面板
· 列表是**按需出现**的，不像 24 个按钮那样常驻占屏
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QPushButton, QTextEdit, QMessageBox, QInputDialog,
                             QFileDialog)

from gui.workers import BgWorker
from core.feature_registry import COMMAND_GROUPS, command_group_for


def _cap_group(name, info):
    source = str((info or {}).get("source", "")).lower()
    name = str(name or "").lower()
    if source == "plugin":
        return "插件/MCP"
    if any(k in name for k in ("security", "permission", "net_guard", "audit")):
        return "安全"
    return "工具"


def _group_rank(group):
    try:
        return COMMAND_GROUPS.index(group)
    except ValueError:
        return len(COMMAND_GROUPS)


def _fmt(r):
    """把模块返回值整理成可读文本（与旧面板保持一致）"""
    if isinstance(r, dict):
        lines = []
        for k, v in r.items():
            s = str(v)
            if len(s) > 300:
                s = s[:300] + " …"
            lines.append("· %s: %s" % (k, s))
        return "\n".join(lines) if lines else "(空结果)"
    if isinstance(r, (list, tuple)):
        if not r:
            return "(空列表)"
        out = []
        for i, x in enumerate(r[:30]):
            out.append("%2d. %s" % (i + 1, str(x)[:200]))
        if len(r) > 30:
            out.append("… 共 %d 条" % len(r))
        return "\n".join(out)
    return str(r) if r is not None else "(无返回)"


# 这两类参数名用"选文件"比手打路径顺手；其余一律让用户直接打字
_PATH_ARGS = ("out_path", "image_path", "path", "zip_path", "dest")
# 需要密码的：密码不能进聊天日志，必须走掩码输入框
_PASSWORD_CAPS = {("memory_crypto", "export_encrypted")}


class CommandPalette(QDialog):
    """命令面板：搜索 → 回车 → 执行"""

    def __init__(self, trunk, commands=None, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.commands = commands or {}      # {面板名: 可调用}
        self._worker = None
        self._entries = []                  # [(kind, label, info)]
        self.setWindowTitle("⌘ 命令面板")
        self.resize(720, 520)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._build()
        self._load_entries()

    # ---------------- 界面 ----------------
    def _build(self):
        root = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "输入关键词…（↑↓ 选择，回车执行。能力、面板、工具都在这里）")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_selected)
        root.addWidget(self.search)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#888;font-size:12px;")
        root.addWidget(self.hint)

        self.list_w = QListWidget()
        self.list_w.setStyleSheet(
            "QListWidget{font-family:'Microsoft YaHei';font-size:13px;}")
        self.list_w.itemActivated.connect(lambda _i: self._run_selected())
        self.list_w.itemDoubleClicked.connect(lambda _i: self._run_selected())
        root.addWidget(self.list_w, stretch=2)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet(
            "font-family:Consolas,'Microsoft YaHei';font-size:12px;")
        self.out.setPlainText(
            "搜索并回车执行。能力来自模块自己声明的 TOOLS（会随模块自动更新），\n"
            "不是一张手写的按钮表 —— 所以以后加能力不用再加按钮。")
        root.addWidget(self.out, stretch=2)

        row = QHBoxLayout()
        row.addStretch(1)
        b = QPushButton("关闭 (Esc)")
        b.setStyleSheet("padding: 4px 14px;")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        root.addLayout(row)

    # ---------------- 数据 ----------------
    def _load_entries(self):
        """汇总三类入口"""
        self._entries = []

        # ① 能力注册表
        try:
            from core import module_caps
            caps = module_caps.load_tools(getattr(self.trunk, "base", None))
            for name, info in caps.items():
                info = dict(info or {})
                info.setdefault("group", _cap_group(name, info))
                self._entries.append(("cap", name, info))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

        # ② 主窗口能打开的面板
        for label, fn in (self.commands or {}).items():
            if callable(fn):
                self._entries.append((
                    "panel", label,
                    {"fn": fn, "desc": "打开面板",
                     "group": command_group_for(label)}))

        self._filter("")

    def _matches(self, q):
        """过滤：能力走注册表的同一套匹配（hints/滑窗），面板按名字"""
        q = (q or "").strip().lower()
        if not q:
            return self._entries
        try:
            from core import module_caps
            caps = {n: i for k, n, i in self._entries if k == "cap"}
            picked = [n for n, _ in module_caps.shortlist(caps, q, 20)]
            order = {n: i for i, n in enumerate(picked)}
        except Exception:
            order = {}
        out = []
        for kind, label, info in self._entries:
            if kind == "cap":
                if label in order:
                    out.append((kind, label, info))
            else:
                if q in label.lower() or q in str(info.get("desc", "")).lower():
                    out.append((kind, label, info))
        # 组顺序固定：常用  任务  资料  工具  安全  插件/MCP  开发；
        # 同组内能力按匹配度、面板按名称补在后面。
        out.sort(key=lambda e: (
            _group_rank(e[2].get("group", "工具")),
            0 if e[0] == "cap" else 1,
            order.get(e[1], 99),
            e[1]))
        return out

    def _filter(self, text=""):
        q = (text or "").strip()
        hits = self._matches(q)
        self.list_w.clear()
        for kind, label, info in hits:
            if kind == "cap":
                src = {"plugin": "模块", "core": "内置"}.get(info.get("source"), "工具")
                ro = "只读" if info.get("readonly") else (
                    "需确认" if info.get("confirm") else "写入")
                txt = "⚙ %s  ·  %s  [%s/%s]" % (label, info.get("desc", ""), src, ro)
            else:
                txt = "🪟 %s  ·  打开面板" % label
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, (kind, label, info))
            self.list_w.addItem(it)
        if self.list_w.count():
            self.list_w.setCurrentRow(0)
        groups = []
        for _kind, _label, info in hits:
            g = info.get("group", "工具")
            if g not in groups:
                groups.append(g)
        self.hint.setText("共 %d 项（能力 %d / 面板 %d）  分组：%s"
                          % (len(hits),
                             sum(1 for e in hits if e[0] == "cap"),
                             sum(1 for e in hits if e[0] == "panel"),
                             "  ".join(groups)))

    # ---------------- 执行 ----------------
    def _current(self):
        it = self.list_w.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _run_selected(self):
        cur = self._current()
        if not cur:
            return
        kind, label, info = cur
        if kind == "panel":
            fn = info.get("fn")
            try:
                self.accept()               # 先关面板再开目标窗口，避免叠在一起
                if callable(fn):
                    fn()
            except Exception as e:
                QMessageBox.warning(self, "打开失败", str(e)[:200])
            return
        self._run_cap(label, info)

    def _ask_args(self, label, info):
        """按声明的参数逐个问；路径类给"选文件"，密码类走掩码框

        返回 (要不要继续, {参数名: 值})
        """
        args = info.get("args") or {}
        if not args:
            return True, {}
        mod, method = info.get("mod"), info.get("method")
        vals = {}
        for k, desc in args.items():
            if (mod, method) in _PASSWORD_CAPS and k == "password":
                v, ok = QInputDialog.getText(self, label, "设置一个密码：",
                                             QLineEdit.Password)
                if not ok or not v:
                    return False, {}
                vals[k] = v
                continue
            if k in _PATH_ARGS:
                p, _ = QFileDialog.getSaveFileName(
                    self, label, os.path.join(os.path.expanduser("~"), "Desktop"),
                    "所有文件 (*)")
                if not p:
                    return False, {}
                vals[k] = p
                continue
            v, ok = QInputDialog.getText(self, label, "%s（%s）" % (k, desc))
            if not ok:
                return False, {}
            if v.strip() or not desc:
                vals[k] = v.strip()
        return True, vals

    def _run_cap(self, label, info):
        mod, method = info.get("mod"), info.get("method")
        if not (mod and method):
            return
        if info.get("confirm"):
            r = QMessageBox.question(
                self, "确认", "%s\n\n%s\n\n确定要做吗？"
                % (label, info.get("desc", "")),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                self.out.setPlainText("已取消：%s" % label)
                return
        ok, vals = self._ask_args(label, info)
        if not ok:
            self.out.setPlainText("已取消：%s" % label)
            return

        self.out.setPlainText("▶ %s 运行中…（后台执行，界面不卡）" % label)

        def work():
            # 走 tool_caller 的统一分发：readonly/confirm/danger 那套只有一处实现
            tc = self.trunk.modules.get("tool_caller")
            if tc is None:
                self.trunk.call("tool_caller", "__no__")
                tc = self.trunk.modules.get("tool_caller")
            if tc is not None and hasattr(tc, "_dispatch"):
                return tc._dispatch(info, vals, "", label)
            # 兜底：直接调（老版本没有 _dispatch 时）
            self.trunk.call(mod, "__no__")
            m = self.trunk.modules.get(mod)
            fn = getattr(m, method, None) if m else None
            if fn is None:
                return "❌ 模块 %s 没有方法 %s" % (mod, method)
            return fn(**vals) if vals else fn()

        w = BgWorker(work)
        w.done.connect(lambda r: self.out.setPlainText(
            "%s\n\n%s" % (label, _fmt(r))))
        self._worker = w
        w.start()


def show_command_palette(trunk, commands=None, parent=None):
    d = CommandPalette(trunk, commands, parent)
    d.show()
    d.search.setFocus()
    return d
