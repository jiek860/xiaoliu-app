# -*- coding: utf-8 -*-
"""工作台 IDE 侧栏：活动栏图标 + 搜索视图 + 源代码管理视图。

为什么单独一个文件
------------------
`workbench_dialog.py` 已经负责主布局/状态栏/AI 协作，继续塞搜索和 Git
会把主窗口推到 600 行上限。这里只放"侧栏视图"，不依赖工作台内部状态：
  * SearchPanel 发 openRequested(path, line)
  * ScmPanel    发 openRequested(path)
  * activity_icon(kind) 画单色活动栏图标，替代 emoji

约束：本文件不创建 QPushButton/QAction，活动栏图标是 QListWidget 项。
"""
from __future__ import annotations

import os
import shutil
import subprocess

from PyQt5.QtCore import QPointF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import (QCompleter, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QStackedWidget,
                             QVBoxLayout, QWidget)

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None

from gui.ide_explorer import git_status_entries  # noqa: E402


_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
              "modules_repo", "dist", "build", ".pytest_cache"}
_TEXT_EXT = {".py", ".md", ".txt", ".json", ".js", ".ts", ".html", ".css",
             ".yml", ".yaml", ".toml", ".ini", ".cfg", ".ps1", ".sh", ".sql"}
_LANG = {".py": "Python", ".md": "Markdown", ".json": "JSON",
         ".js": "JavaScript", ".ts": "TypeScript", ".html": "HTML",
         ".css": "CSS", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML",
         ".ini": "INI", ".cfg": "INI", ".ps1": "PowerShell", ".sh": "Shell",
         ".sql": "SQL", ".txt": "Plain Text"}

_HEADER_QSS = (
    "QWidget#sideHeader{background:#f6f8fa;border-bottom:1px solid #d0d7de;}")
_HEADER_TITLE_QSS = "font-weight:600;font-size:12px;color:#24292f;"
_HINT_QSS = "color:#667085;font-size:11px;"


def _header(title):
    host = QWidget()
    host.setObjectName("sideHeader")
    host.setAttribute(Qt.WA_StyledBackground, True)
    host.setStyleSheet(_HEADER_QSS)
    lay = QHBoxLayout(host)
    lay.setContentsMargins(8, 4, 6, 4)
    lab = QLabel(title)
    lab.setStyleSheet(_HEADER_TITLE_QSS)
    lay.addWidget(lab)
    lay.addStretch(1)
    return host, lay


_ICON_PX = 22


def activity_icon(kind):
    """单色活动栏图标；选中态用蓝色，避免 emoji 各家字体不一致。"""
    icon = QIcon()
    icon.addPixmap(_activity_pixmap(kind, "#57606a"), QIcon.Normal)
    icon.addPixmap(_activity_pixmap(kind, "#1d4ed8"), QIcon.Selected)
    return icon


def _activity_pixmap(kind, color):
    # 按 22px 画、活动栏也按 22px 显示，1:1 不缩放，线条才不会被插值糊掉
    pm = QPixmap(_ICON_PX, _ICON_PX)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    if kind == "explorer":
        p.drawRoundedRect(3, 7, 16, 11, 2, 2)
        p.drawLine(3, 9, 9, 9)
        p.drawLine(9, 7, 12, 7)
    elif kind == "search":
        p.drawEllipse(QPointF(9, 9), 5, 5)
        p.drawLine(13, 13, 18, 18)
    elif kind == "scm":
        p.drawEllipse(QPointF(5, 4), 2.2, 2.2)
        p.drawEllipse(QPointF(5, 18), 2.2, 2.2)
        p.drawEllipse(QPointF(17, 10), 2.2, 2.2)
        p.drawLine(5, 6, 5, 16)
        p.drawLine(7, 5, 15, 9)
        p.drawLine(7, 17, 15, 11)
    elif kind == "run":
        # 只描边、不填充：与其余 5 个线稿图标保持同样的视觉重量
        p.drawPolygon(QPolygonF([QPointF(6, 4), QPointF(18, 11),
                                 QPointF(6, 18)]))
    elif kind == "extensions":
        for x, y in ((3, 3), (12, 3), (3, 12), (12, 12)):
            p.drawRoundedRect(x, y, 7, 7, 1, 1)
    elif kind == "ai":
        # 四角星（闪光）线稿：原来是竖/横/两条对角线，看起来像「米」，
        # 会被误认成关闭或星号。
        c = _ICON_PX / 2.0
        p.drawPolygon(QPolygonF([
            QPointF(c, 2), QPointF(c + 2.4, c - 2.4),
            QPointF(20, c), QPointF(c + 2.4, c + 2.4),
            QPointF(c, 20), QPointF(c - 2.4, c + 2.4),
            QPointF(2, c), QPointF(c - 2.4, c - 2.4)]))
    p.end()
    return pm


class SearchPanel(QWidget):
    """工作区内容搜索：Enter 搜索，双击结果跳转到行。"""

    openRequested = pyqtSignal(str, int)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = os.path.abspath(root or os.getcwd())
        self._build()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head, hl = _header("搜索")
        clear = QLabel('<a href="clear" style="color:#1d4ed8;'
                       'font-size:11px;text-decoration:none;">清空</a>')
        clear.linkActivated.connect(self._clear)
        hl.addWidget(clear)
        v.addWidget(head)

        self.query = QLineEdit()
        # 占位文字要能在侧栏被拖到最窄（200px）时完整显示，
        # 所以只留短句，Enter 提示放在 tooltip 和底部 hint 里。
        self.query.setPlaceholderText("搜索工作区内容")
        self.query.setToolTip("输入关键词后按 Enter 搜索")
        self.query.setClearButtonEnabled(True)
        self.query.setFixedHeight(28)
        # 外边距必须交给布局：写进 QLineEdit 的 stylesheet margin 后，
        # 26px 固定高减去 margin/padding/border 只剩 8px，12px 文字上下被裁掉。
        self.query.setStyleSheet(
            "QLineEdit{padding:0 6px;border:1px solid #d0d7de;"
            "border-radius:5px;background:#ffffff;font-size:12px;}")
        self.query.returnPressed.connect(self.run_search)
        row = QHBoxLayout()
        row.setContentsMargins(8, 6, 8, 0)
        row.addWidget(self.query)
        v.addLayout(row)

        self.results = QListWidget()
        self.results.setStyleSheet(
            "QListWidget{border:none;background:#ffffff;}"
            "QListWidget::item{padding:4px 8px;border-bottom:1px solid #f2f4f7;}"
            "QListWidget::item:selected{background:#eef4ff;color:#1d4ed8;}")
        self.results.itemDoubleClicked.connect(self._open_item)
        v.addWidget(self.results, 1)
        self.hint = QLabel("输入关键词后按 Enter")
        self.hint.setStyleSheet(_HINT_QSS + "padding:3px 8px;")
        v.addWidget(self.hint)

    def focus_query(self):
        self.query.setFocus()
        self.query.selectAll()

    def _clear(self, *_):
        self.query.clear()
        self.results.clear()
        self.hint.setText("输入关键词后按 Enter")

    def run_search(self):
        q = self.query.text().strip()
        if not q:
            return
        self.results.clear()
        hits = self._search(q)
        for path, line, text in hits:
            rel = os.path.relpath(path, self.root).replace("\\", "/")
            item = QListWidgetItem("%s:%d  %s" % (
                rel, line, str(text or "").strip()[:100]))
            item.setData(Qt.UserRole, (path, line))
            item.setToolTip(path)
            self.results.addItem(item)
        self.hint.setText("找到 %d 条" % len(hits) if hits else "没有匹配结果")

    def _search(self, q):
        rg = shutil.which("rg")
        if rg:
            hits = self._search_rg(rg, q)
            if hits is not None:
                return hits
        return self._search_walk(q)

    def _search_rg(self, rg, q):
        try:
            cp = subprocess.run(
                [rg, "--line-number", "--no-heading", "--color", "never",
                 "--max-filesize", "1M", "--max-count", "40",
                 "--glob", "!.git/**", "--glob", "!node_modules/**",
                 "--glob", "!.venv/**", "--glob", "!modules_repo/**",
                 q, "."],
                cwd=self.root, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=8)
            if cp.returncode not in (0, 1):
                return None
            hits = []
            for line in (cp.stdout or "").splitlines():
                parts = line.split(":", 2)
                if len(parts) != 3:
                    continue
                rel, no, text = parts
                path = os.path.join(self.root, rel.lstrip(".\\/"))
                try:
                    hits.append((path, int(no), text))
                except ValueError:
                    continue
                if len(hits) >= 100:
                    break
            return hits
        except Exception as e:  # 静默是故意的 - rg 不可用就走 Python 兜底
            _x6_swallowed(__name__, e, "ripgrep search")
            return None

    def _search_walk(self, q):
        hits = []
        needle = q.casefold()
        try:
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [d for d in dirnames
                               if d not in _SKIP_DIRS and not d.startswith(".")]
                for fn in filenames:
                    if os.path.splitext(fn)[1].lower() not in _TEXT_EXT:
                        continue
                    path = os.path.join(dirpath, fn)
                    try:
                        if os.path.getsize(path) > 1024 * 1024:
                            continue
                        with open(path, "r", encoding="utf-8",
                                  errors="replace") as f:
                            for no, line in enumerate(f, 1):
                                if needle in line.casefold():
                                    hits.append((path, no, line.rstrip()))
                                    if len(hits) >= 100:
                                        return hits
                    except OSError:
                        continue
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "python workspace search")
        return hits

    def _open_item(self, item):
        data = item.data(Qt.UserRole)
        if data:
            self.openRequested.emit(str(data[0]), int(data[1]))


class ScmPanel(QWidget):
    """源代码管理：git 分支 + 工作区改动列表。"""

    openRequested = pyqtSignal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = os.path.abspath(root or os.getcwd())
        self._build()
        self.refresh()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head, hl = _header("源代码管理")
        refresh = QLabel('<a href="refresh" style="color:#1d4ed8;'
                         'font-size:11px;text-decoration:none;">刷新</a>')
        refresh.linkActivated.connect(self.refresh)
        hl.addWidget(refresh)
        v.addWidget(head)

        self.branch = QLabel("分支：-")
        self.branch.setStyleSheet(
            "color:#475467;font-size:11px;padding:5px 8px;"
            "border-bottom:1px solid #eaecf0;")
        v.addWidget(self.branch)

        self.changes = QListWidget()
        self.changes.setStyleSheet(
            "QListWidget{border:none;background:#ffffff;}"
            "QListWidget::item{padding:4px 8px;border-bottom:1px solid #f2f4f7;}"
            "QListWidget::item:selected{background:#eef4ff;color:#1d4ed8;}")
        self.changes.itemDoubleClicked.connect(self._open_item)
        v.addWidget(self.changes, 1)
        self.hint = QLabel("双击改动打开文件")
        self.hint.setStyleSheet(_HINT_QSS + "padding:3px 8px;")
        v.addWidget(self.hint)

    def _git(self, args):
        try:
            return subprocess.run(
                ["git"] + list(args), cwd=self.root, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=5)
        except Exception as e:  # 静默是故意的 - 没有 git 就显示不可用
            _x6_swallowed(__name__, e, "git command")
            return None

    def refresh(self, *_):
        self.changes.clear()
        cp = self._git(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = (cp.stdout or "").strip() if cp is not None else ""
        self.branch.setText("分支：%s" % (branch or "未检测到 Git 仓库"))
        entries = git_status_entries(self.root)
        if entries is None:
            self.hint.setText("当前目录不是 Git 仓库或未安装 git")
            return
        for status, rel in entries:
            item = QListWidgetItem("%s  %s" % (status, rel))
            item.setData(Qt.UserRole, os.path.join(self.root, rel))
            item.setToolTip(rel)
            self.changes.addItem(item)
        self.hint.setText("共 %d 个改动" % len(entries) if entries else "工作区干净")

    def _open_item(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(str(path)):
            self.openRequested.emit(str(path))


class SidebarHost(QStackedWidget):
    """资源管理器 + 搜索 + Git 三个左侧视图的容器。"""

    openAtLineRequested = pyqtSignal(str, int)
    openPathRequested = pyqtSignal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebarStack")
        self.explorer = None
        self.search_view = SearchPanel(root, self)
        self.search_view.openRequested.connect(self.openAtLineRequested)
        self.scm_view = ScmPanel(root, self)
        self.scm_view.openRequested.connect(self.openPathRequested)

    def attach(self, explorer, splitter):
        """把原资源管理器页放到 index 0，再追加搜索/Git。

        ⚠️ 不要用 `splitter.replaceWidget(0, self)`：Qt 会把返回的旧控件
           置成"显式隐藏"，它再被 `insertWidget` 收进栈里也不会显示，
           最后整个侧栏被 splitter 压成 0 宽。这里改成"先收养、再插入"。
        """
        self.insertWidget(0, explorer)     # 重新挂父级，自动脱离 splitter
        self.addWidget(self.search_view)
        self.addWidget(self.scm_view)
        splitter.insertWidget(0, self)
        self.explorer = explorer
        self.setCurrentIndex(0)
        explorer.show()
        self.show()


def language_for_path(path):
    if not path:
        return "Plain Text"
    return _LANG.get(os.path.splitext(str(path))[1].lower(), "Plain Text")


def git_branch(root):
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=3)
        return (cp.stdout or "").strip() or "-"
    except Exception:
        return "-"


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


def goto_line(editor_widget, line):
    try:
        from PyQt5.QtGui import QTextCursor
        block = editor_widget.document().findBlockByNumber(max(0, int(line) - 1))
        if block.isValid():
            editor_widget.setTextCursor(QTextCursor(block))
            editor_widget.centerCursor()
            editor_widget.setFocus()
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "goto line")


def open_plugin_market(parent, trunk):
    """扩展入口：复用现有插件市场，不新做一套扩展系统。"""
    try:
        from gui.plugin_dialog import show_plugin_dialog
        from PyQt5.QtWidgets import QDialog

        def dlg(title="", w=500, h=600, **kwargs):
            d = QDialog(parent)
            d.setWindowTitle(title or "窗口")
            d.resize(int(w or 500), int(h or 600))
            lay = QVBoxLayout(d)
            return d, lay

        show_plugin_dialog(parent, dlg, trunk)
    except Exception as e:  # 静默是故意的 - 插件市场打不开不能崩工作台
        _x6_swallowed(__name__, e, "open plugin market")
        return str(e)
    return ""


_COMMANDS = ("新建文件", "打开文件", "保存", "另存为", "运行当前文件",
             "搜索工作区", "源代码管理", "资源管理器", "输出", "终端",
             "插件市场", "AI 面板", "分屏", "minimap", "全屏")


class CommandCenterMixin:
    """顶部命令中心：一个 QLineEdit 覆盖高频动作，兼按文件名打开。

    为什么不用 QMenuBar：菜单项都是 `QAction` 创建点，会直接突破
    60 按钮预算。宿主窗口需要提供 `command / root / status_label /
    _editor` 和 `_show_* / _open_extensions / toggle_fullscreen`。
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
        """回车执行：先精确命令、再模糊命令、最后按文件名打开。"""
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
        path = find_file(self.root, text)
        if path:
            self.command.clear()
            self.open_path(path)
            self.status_label.setText("已打开 %s" % os.path.basename(path))
        else:
            self.status_label.setText("未找到命令或文件：%s" % text)
