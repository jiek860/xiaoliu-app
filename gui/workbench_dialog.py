# -*- coding: utf-8 -*-
"""小6 工作台：VS Code 风格编辑器 + AI Agent 同屏（无功能页签）。

为什么这样设计
--------------
原来有三个独立窗口：代码编辑器 / Agent 旅程 / AI 代码 Agent。
用户改完 AI 生成的代码想手动微调，必须关掉一个再开另一个 —— 文件、目录、
选中片段全丢。而且三者重复实现了线程、diff 审批、时间线。

本工作台按 IDE 惯例放在**同一屏**：

    +----+----------------------------+--------------+
    |活动| 资源管理器 | 编辑器 / 输出   | AI 面板       |
    |栏  |            |                |（可弹出）     |
    +----+----------------------------+--------------+
    | 状态栏：提示 / 当前文件 / 编码 / 换行               |
    +---------------------------------------------------+

* 没有"功能页签"：不存在"编辑器页/旅程页/Agent页"的切换
* 编辑器里的标签页只是**多个文件**，跟原来一样
* 文件操作在资源管理器顶部，编辑器工具条只留运行 / AI / 关闭
* AI 面板默认在右侧，可折叠、可弹出为独立窗口
* 活动栏只放真实可用的入口：资源管理器 / AI / 输出

兼容性：旧入口 open_code_editor / agent_journey_dialog / code_agent_dialog
全部改为打开本工作台并定位到对应区域，菜单文字与位置不变。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import (QDockWidget, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QListView, QMainWindow, QSplitter,
                             QStatusBar, QVBoxLayout, QWidget)

# AI 面板在 gui/workbench_ai_dock.py（本文件曾接近 600 行上限）。
# 继续从这里导出 AgentDock，保持旧导入路径可用。
from gui.workbench_ai_dock import AgentDock  # noqa: F401
# IDE 侧栏/命令中心单独放，避免主窗口超 600 行。
from gui.ide_sidebar import (CommandCenterMixin, SidebarHost, activity_icon,
                             git_branch, goto_line, open_plugin_market)
# 状态栏 / 快捷键 / AI 侧栏 / Git 回显拆到 workbench_shell（本文件要求 ≤500 行）。
from gui.workbench_shell import (WorkbenchAIHostMixin, WorkbenchSCMMixin,
                                 WorkbenchStatusMixin)

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None


class WorkbenchWindow(CommandCenterMixin, WorkbenchStatusMixin,
                      WorkbenchSCMMixin, WorkbenchAIHostMixin, QMainWindow):
    """统一工作台：编辑器 + AI 面板同屏，无功能页签。"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.root = os.path.abspath(
            getattr(trunk, "base", ".") or os.getcwd())
        self._ai_popup = None
        self._ai_shown = True          # AI 面板默认展开
        self._last_view_row = 0        # 活动栏当前左侧视图
        self._editor = None
        self._editor_splitter = None
        self.sidebar_stack = None
        self.search_view = None
        self.scm_view = None
        self.setWindowTitle("🧰 小6 工作台")
        self.resize(1440, 900)
        self._build()

    # ---------------------------------------------------------- 构建
    def _build(self):
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 顶部工具条：做成 IDE 常见的浅色标题栏，左边是工作区面包屑，右边是快捷键提示。
        bar_host = QWidget()
        bar_host.setObjectName("workbenchBar")
        bar_host.setAttribute(Qt.WA_StyledBackground, True)
        bar_host.setStyleSheet(
            "QWidget#workbenchBar{background:#f6f8fa;"
            "border-bottom:1px solid #d0d7de;}")
        bar = QHBoxLayout(bar_host)
        bar.setContentsMargins(10, 5, 10, 5)
        bar.setSpacing(8)
        self.title = QLabel("🧰 工作台")
        self.title.setStyleSheet("font-weight:700;font-size:13px;color:#101828;")
        bar.addWidget(self.title)
        _crumb = QLabel("›")
        _crumb.setStyleSheet("color:#98a2b3;font-size:12px;")
        bar.addWidget(_crumb)
        self.root_label = QLabel(os.path.basename(self.root) or self.root)
        self.root_label.setStyleSheet("color:#475467;font-size:12px;")
        self.root_label.setToolTip(self.root)
        bar.addWidget(self.root_label)
        bar.addSpacing(12)
        self.command = QLineEdit()
        self.command.setObjectName("commandCenter")
        self.command.setPlaceholderText("搜索命令或文件…")
        self.command.setClearButtonEnabled(True)
        self.command.setFixedHeight(24)
        self.command.setMinimumWidth(240)
        self.command.setMaximumWidth(420)
        self.command.setStyleSheet(
            "QLineEdit#commandCenter{background:#ffffff;color:#24292f;"
            "border:1px solid #d0d7de;border-radius:5px;padding:1px 7px;"
            "font-size:12px;}"
            "QLineEdit#commandCenter:focus{border-color:#84adff;}")
        self.command.returnPressed.connect(self._run_command)
        bar.addWidget(self.command, 1)
        bar.addStretch(1)
        hint = QLabel("Ctrl+Shift+P 命令 · Ctrl+J AI · F11 全屏")
        hint.setStyleSheet("color:#98a2b3;font-size:11px;")
        bar.addWidget(hint)
        # 收起/展开不占按钮：AI 是右侧 QDockWidget，可用关闭按钮或 Ctrl+J；
        # 快捷键见 _install_shortcuts。
        self.collapse_btn = None
        v.addWidget(bar_host)

        # 主体：活动栏 | 编辑器（内含资源管理器/编辑器/输出）
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self._make_activity_bar())
        self.splitter.addWidget(self._make_editor_slot())
        self._install_sidebar_views()
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([46, 1200])
        v.addWidget(self.splitter, 1)

        # 右侧 AI：用 QDockWidget 做成 VS Code 风格的 Secondary Side Bar，
        # 可拖动、可浮动、可关闭；不再是自己拼的 QSplitter 第三栏。
        self.ai_dock = AgentDock(self)
        self.ai_host = QDockWidget("AI 助手", self)
        self.ai_host.setObjectName("aiSecondarySideBar")
        self.ai_host.setAllowedAreas(Qt.LeftDockWidgetArea |
                                     Qt.RightDockWidgetArea)
        self.ai_host.setFeatures(QDockWidget.DockWidgetMovable |
                                 QDockWidget.DockWidgetFloatable |
                                 QDockWidget.DockWidgetClosable)
        self.ai_host.setWidget(self.ai_dock)
        self.ai_host.setMinimumWidth(280)
        self.addDockWidget(Qt.RightDockWidgetArea, self.ai_host)
        self.ai_host.visibilityChanged.connect(self._on_ai_visibility)

        # 底部状态栏：左边是编辑器消息，右边是当前文件 + 编码信息。
        self.status = QStatusBar()
        self.status.setSizeGripEnabled(False)
        self.status.setStyleSheet(
            "QStatusBar{background:#f6f8fa;border-top:1px solid #d0d7de;}"
            "QStatusBar::item{border:none;}")
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(
            "color:#475467;font-size:11px;padding:0 8px;")
        self.pos_label = QLabel("行 1, 列 1")
        self.pos_label.setStyleSheet(
            "color:#475467;font-size:11px;padding:0 8px;"
            "border-left:1px solid #d0d7de;")
        self.branch_label = QLabel("⎇ -")
        self.branch_label.setStyleSheet(
            "color:#475467;font-size:11px;padding:0 8px;")
        self.error_label = QLabel("⚠ 0")
        self.error_label.setStyleSheet(
            "color:#667085;font-size:11px;padding:0 8px;"
            "border-left:1px solid #d0d7de;")
        self.lang_label = QLabel("Plain Text")
        self.lang_label.setStyleSheet(
            "color:#667085;font-size:11px;padding:0 8px;"
            "border-left:1px solid #d0d7de;")
        self.path_label = QLabel("未保存 · UTF-8 · LF")
        self.path_label.setStyleSheet(
            "color:#667085;font-size:11px;padding:0 8px;"
            "border-left:1px solid #d0d7de;")
        self.status.addWidget(self.status_label, 1)
        self.status.addPermanentWidget(self.branch_label)
        self.status.addPermanentWidget(self.pos_label)
        self.status.addPermanentWidget(self.error_label)
        self.status.addPermanentWidget(self.lang_label)
        self.status.addPermanentWidget(self.path_label)
        v.addWidget(self.status)
        self.setCentralWidget(central)
        self.branch_label.setText("⎇ %s" % git_branch(self.root))
        self._wire_editor_status()
        self._install_shortcuts()
        self._setup_command_completer()
        # 把当前文件/选区送进右侧 AI（Ctrl+Shift+A / 标签页右键）
        from gui.workbench_context import install as install_ai_context
        install_ai_context(self)

    def _make_activity_bar(self):
        """最左侧 46px 活动栏：图标式导航，不占按钮预算。"""
        bar = QListWidget()
        bar.setObjectName("activityBar")
        bar.setFixedWidth(46)
        bar.setFrameShape(QFrame.NoFrame)
        bar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar.setFocusPolicy(Qt.NoFocus)
        bar.setViewMode(QListView.IconMode)
        bar.setFlow(QListView.TopToBottom)
        bar.setWrapping(False)
        bar.setMovement(QListView.Static)
        bar.setResizeMode(QListView.Adjust)
        # 图标按 22px 原尺寸绘制，这里也按 22px 显示：1:1 不缩放，
        # 线条与其它活动栏图标一致，不会因插值显得发虚。
        bar.setIconSize(QSize(22, 22))
        bar.setSpacing(0)
        bar.setStyleSheet(
            "QListWidget#activityBar{background:#f6f8fa;border:none;"
            "border-right:1px solid #d0d7de;outline:0;}"
            "QListWidget#activityBar::item{color:#57606a;"
            "border-left:2px solid transparent;}"
            "QListWidget#activityBar::item:hover{background:#eaeef2;}"
            "QListWidget#activityBar::item:selected{background:#ffffff;"
            "border-left:2px solid #1d4ed8;}")
        for kind, tip in (("explorer", "资源管理器"),
                          ("search", "搜索"),
                          ("scm", "源代码管理"),
                          ("run", "运行当前文件"),
                          ("extensions", "扩展 / 插件市场"),
                          ("ai", "AI 助手：点一下聚焦 AI 输入框（Ctrl+J 收起/展开）")):
            item = QListWidgetItem()
            item.setIcon(activity_icon(kind))
            item.setToolTip(tip)
            item.setTextAlignment(Qt.AlignCenter)
            item.setSizeHint(QSize(44, 44))
            bar.addItem(item)
        bar.setCurrentRow(0)
        bar.itemClicked.connect(self._on_activity_clicked)
        self.activity_list = bar
        return bar

    def _on_activity_clicked(self, item):
        """活动栏只做真实动作；搜索/Git 切换左侧视图，运行/扩展是动作。"""
        try:
            row = self.activity_list.row(item)
            if row in (0, 1, 2):
                self._last_view_row = row
                self._show_view(row)
            elif row == 3:
                self.activity_list.setCurrentRow(self._last_view_row)
                self._editor.run_current()
            elif row == 4:
                self.activity_list.setCurrentRow(self._last_view_row)
                self._open_extensions()
            elif row == 5:
                self.activity_list.setCurrentRow(self._last_view_row)
                if not self._ai_shown:
                    self.toggle_ai()
                self.ai_dock.goal.setFocus()
        except Exception as e:  # 静默是故意的 - 面板定位失败不影响主流程
            _x6_swallowed(__name__, e, "activity bar click")

    def _show_view(self, row):
        """切到左侧视图；行号对应活动栏 0/1/2。"""
        if self.sidebar_stack is not None:
            self.sidebar_stack.setCurrentIndex(row)
        if row == 0 and self._editor is not None:
            self._editor.tree.setFocus()
        elif row == 1 and self.search_view is not None:
            self.search_view.focus_query()
        elif row == 2 and self.scm_view is not None:
            self.scm_view.refresh()
            self.scm_view.changes.setFocus()

    def _install_sidebar_views(self):
        """把原资源管理器包进 QStackedWidget，追加搜索/Git 两个视图。"""
        if self._editor_splitter is None:
            return
        try:
            tree_panel = self._editor_splitter.widget(0)
            host = SidebarHost(self.root, self)
            host.attach(tree_panel, self._editor_splitter)
            host.openAtLineRequested.connect(self._open_at_line)
            host.openPathRequested.connect(self.open_path)
            host.diffRequested.connect(self._show_scm_diff)
            host.commitDone.connect(self._on_scm_commit_done)
            self.sidebar_stack = host
            self.search_view = host.search_view
            self.scm_view = host.scm_view
            # QStackedWidget 的最小宽度是 0，QSplitter 会先把侧栏压扁；
            # 给它一个下限，再固定"侧栏不伸缩、编辑器伸缩"。
            host.setMinimumWidth(200)
            self._editor_splitter.setStretchFactor(0, 0)
            self._editor_splitter.setStretchFactor(1, 1)
            self._editor_splitter.setSizes([260, 840])
        except Exception as e:  # 静默是故意的 - 侧栏失败不能拖垮编辑器
            _x6_swallowed(__name__, e, "install sidebar views")
            self.sidebar_stack = None

    def _open_at_line(self, path, line):
        """搜索结果跳转：打开文件并把光标放到指定行。"""
        if self.open_path(path):
            goto_line(self._editor.tabs.currentWidget(), line)

    def _show_explorer(self):
        self.activity_list.setCurrentRow(0)
        self._last_view_row = 0
        self._show_view(0)

    def _show_search(self):
        self.activity_list.setCurrentRow(1)
        self._last_view_row = 1
        self._show_view(1)

    def _show_scm(self):
        self.activity_list.setCurrentRow(2)
        self._last_view_row = 2
        self._show_view(2)

    def _show_ai(self):
        if not self._ai_shown:
            self.toggle_ai()
        self.ai_dock.goal.setFocus()

    def _show_output(self):
        ed = self._editor
        if ed is None or not hasattr(ed, "bottom"):
            return
        ed.bottom.select(0)
        ed.output.setFocus()

    def _show_terminal(self):
        ed = self._editor
        if ed is None or not hasattr(ed, "bottom"):
            return
        ed.bottom.select(2)
        ed.bottom.term_input.setFocus()

    def _toggle_split(self):
        if self._editor is not None:
            self._editor.toggle_split()

    def _toggle_minimap(self):
        if self._editor is not None:
            self._editor.toggle_minimap()

    def _open_extensions(self):
        """扩展入口：打开现有插件市场，不新做一套扩展系统。"""
        err = open_plugin_market(self, self.trunk)
        if err:
            self.status_label.setText("插件市场打开失败：%s" % err[:100])

    def _make_editor_slot(self):
        """中间：嵌入 CodeEditorDialog 的编辑区。

        复用 CodeEditorDialog 而不是重写 —— 语法高亮、jedi 补全、
        多文件标签、运行输出都已经在里面验证过。
        """
        slot = QWidget()
        lay = QVBoxLayout(slot)
        lay.setContentsMargins(0, 0, 0, 0)
        try:
            from gui.code_editor_dialog import CodeEditorDialog
            self._editor = CodeEditorDialog(self.trunk, self)
            # 把它拆成"普通 QWidget"，这样能嵌进布局而不是独立窗口
            widget = self._editor.centralWidget()
            if widget is not None:
                self._editor_splitter = widget if isinstance(widget, QSplitter) else None
                lay.addWidget(widget)
                self._editor.setCentralWidget(QWidget())   # 解绑，避免重复父级
            else:
                lay.addWidget(self._editor)
        except Exception as e:  # 静默是故意的 - 编辑器坏了也不能让工作台打不开
            _x6_swallowed(__name__, e, "best-effort fallback")
            lay.addWidget(QLabel("编辑器加载失败：%s" % str(e)[:200]))
        return slot

    # ---------------------------------------------------------- 对外
    def editor_open_files(self):
        """当前编辑器里打开的所有文件路径（供 AI 参考）。"""
        out = []
        try:
            tabs = getattr(self._editor, "tabs", None)
            if tabs is None:
                return out
            for i in range(tabs.count()):
                w = tabs.widget(i)
                path = getattr(w, "filepath", "") or ""
                if path:
                    out.append(path)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return out

    def open_path(self, path):
        """供外部（菜单/聊天/AI）打开某个文件。"""
        try:
            if self._editor is not None and hasattr(self._editor, "open_path"):
                self._editor.open_path(path)
                return True
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return False

    def show_diff_preview(self, root, patch, on_apply=None, on_undo=None):
        """编辑器内联 diff 预览（供 AI 面板 / 聊天调用）。"""
        try:
            if self._editor is not None and hasattr(self._editor, "show_diff_preview"):
                return self._editor.show_diff_preview(
                    root, patch, on_apply=on_apply, on_undo=on_undo)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "show workbench diff preview")
        return None

    def mark_diff_applied(self, manifest=""):
        try:
            if self._editor is not None and hasattr(self._editor, "mark_diff_applied"):
                self._editor.mark_diff_applied(manifest)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "mark diff applied")

    def reload_editor_path(self, path):
        """Agent 落盘后刷新 tab；新文件则直接在编辑器里打开。

        需求：AI 用自然语言写出来的完整代码必须出现在工作台里、
        能马上手动改，而不是只留在内联 diff 预览里。
        """
        root = getattr(self, "root", None) or "."
        if not path:
            return
        if not os.path.isabs(str(path)):
            path = os.path.join(root, str(path))
        path = os.path.normpath(str(path))
        if not os.path.isfile(path):
            return
        try:
            editor = self._editor
            if editor is None:
                return
            tabs = getattr(editor, "tabs", None)
            opened = False
            if tabs is not None:
                for i in range(tabs.count()):
                    w = tabs.widget(i)
                    fp = os.path.normpath(
                        str(getattr(w, "filepath", "") or ""))
                    if fp == path:
                        opened = True
                        break
            if opened and hasattr(editor, "reload_path"):
                editor.reload_path(path)
            elif not opened and hasattr(editor, "open_path"):
                editor.open_path(path)
            cur = tabs.currentWidget() if tabs is not None else None
            if cur is not None:
                cur.setFocus()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "reload editor path")

    def set_goal(self, text):
        try:
            self.ai_dock.goal.setPlainText(str(text or ""))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    # AI 面板的显隐/浮动逻辑已拆到 gui/workbench_shell.py:WorkbenchAIHostMixin
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event):
        try:
            if self._ai_popup is not None:
                self._close_ai_popup()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            # 终端是常驻 shell，关窗必须杀掉，否则留孤儿进程
            ed = getattr(self, "_editor", None)
            if ed is not None and getattr(ed, "bottom", None) is not None:
                ed.bottom.shutdown()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "shutdown terminal shell")
        super().closeEvent(event)
