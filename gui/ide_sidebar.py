# -*- coding: utf-8 -*-
"""工作台 IDE 侧栏：活动栏图标 + 搜索视图 + 侧栏容器。

为什么单独一个文件
------------------
`workbench_dialog.py` 已经负责主布局/状态栏/AI 协作，继续塞搜索和 Git
会把主窗口推到 600 行上限。这里只放"侧栏视图"，不依赖工作台内部状态：
  * SearchPanel 发 openRequested(path, line)
  * SidebarHost  三页侧栏容器（资源管理器 / 搜索 / 源代码管理）
  * activity_icon(kind) 画单色活动栏图标，替代 emoji
  * ScmPanel 已拆到 gui/ide_scm.py（本文件在这里 re-export，旧导入路径不变）

约束：本文件不创建 QPushButton/QAction，活动栏图标是 QListWidget 项。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

from PyQt5.QtCore import QPointF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox,
                             QStackedWidget, QVBoxLayout, QWidget)

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None

from gui.ide_explorer import git_status_entries  # noqa: F401,E402
from gui.ide_scm import ScmPanel, _HINT_QSS, _header  # noqa: F401,E402
# 命令中心已拆到 gui/ide_command_center.py（批次 44.4）；这里保留旧导入路径
from gui.ide_command_center import (CommandCenterMixin, _COMMANDS,  # noqa: F401,E402
                                    find_file)


_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
              "modules_repo", "dist", "build", ".pytest_cache"}
_TEXT_EXT = {".py", ".md", ".txt", ".json", ".js", ".ts", ".html", ".css",
             ".yml", ".yaml", ".toml", ".ini", ".cfg", ".ps1", ".sh", ".sql"}
_LANG = {".py": "Python", ".md": "Markdown", ".json": "JSON",
         ".js": "JavaScript", ".ts": "TypeScript", ".html": "HTML",
         ".css": "CSS", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML",
         ".ini": "INI", ".cfg": "INI", ".ps1": "PowerShell", ".sh": "Shell",
         ".sql": "SQL", ".txt": "Plain Text"}


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
        self.case_sensitive = False   # Aa 开关
        self.use_regex = False        # .* 开关
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

        # 选项行：Aa / .* / 替换。用 QLabel 链接而不是 QCheckBox —— 按钮预算已满
        opts = QHBoxLayout()
        opts.setContentsMargins(8, 6, 8, 0)
        opts.setSpacing(12)
        self.case_link = self._toggle_label("Aa", self._toggle_case,
                                            "区分大小写（默认不区分）")
        self.regex_link = self._toggle_label(".*", self._toggle_regex,
                                             "正则表达式（默认字面量）")
        self.replace_link = self._toggle_label("替换", self._toggle_replace,
                                               "展开替换输入行")
        for w in (self.case_link, self.regex_link, self.replace_link):
            opts.addWidget(w)
        opts.addStretch(1)
        v.addLayout(opts)

        self.replace_box = QWidget(self)
        rl = QHBoxLayout(self.replace_box)
        rl.setContentsMargins(8, 6, 8, 4)
        rl.setSpacing(6)
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("替换为…")
        self.replace_input.setToolTip("Enter 直接全部替换（会二次确认并备份）")
        self.replace_input.setFixedHeight(28)
        self.replace_input.setStyleSheet(
            "QLineEdit{padding:0 6px;border:1px solid #d0d7de;"
            "border-radius:5px;background:#ffffff;font-size:12px;}")
        self.replace_input.returnPressed.connect(self.replace_all)
        self.replace_all_link = QLabel(self._link_html("全部替换", False))
        self.replace_all_link.setToolTip("替换前会备份到 data/.x6_replace_backup/")
        self.replace_all_link.linkActivated.connect(
            lambda _href=None: self.replace_all())
        rl.addWidget(self.replace_input, 1)
        rl.addWidget(self.replace_all_link)
        self.replace_box.setVisible(False)
        v.addWidget(self.replace_box)

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
        self._paint_toggles()

    # ----- 选项开关（Aa / .* / 替换） -----
    def _link_html(self, text, on):
        return ('<a href="#" style="color:%s;font-size:11px;'
                'text-decoration:none;font-weight:%s;">%s</a>'
                % ("#1d4ed8" if on else "#57606a",
                   "bold" if on else "normal", text))

    def _toggle_label(self, text, slot, tip=""):
        link = QLabel(self._link_html(text, False))
        link.setToolTip(tip)
        link.linkActivated.connect(lambda _href=None: slot())
        return link

    def _paint_toggles(self):
        self.case_link.setText(self._link_html("Aa", self.case_sensitive))
        self.regex_link.setText(self._link_html(".*", self.use_regex))
        # 用 isHidden() 而不是 isVisible()：面板还没显示时 isVisible() 恒为 False
        self.replace_link.setText(
            self._link_html("替换", not self.replace_box.isHidden()))

    def _toggle_case(self):
        self.case_sensitive = not self.case_sensitive
        self._paint_toggles()
        if self.query.text().strip():
            self.run_search()

    def _toggle_regex(self):
        self.use_regex = not self.use_regex
        self._paint_toggles()
        if self.query.text().strip():
            self.run_search()

    def _toggle_replace(self):
        show = self.replace_box.isHidden()
        self.replace_box.setVisible(show)
        self._paint_toggles()
        if show:
            self.replace_input.setFocus()

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
        if hits is None:
            return      # 正则写错：_search_walk 已经写好了提示，别覆盖成"没有结果"
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

    def _matcher(self, q):
        """按开关编译匹配器：正则/字面量 + 大小写。两条搜索路径共用。"""
        flags = 0 if self.case_sensitive else re.IGNORECASE
        return re.compile(q if self.use_regex else re.escape(q), flags)

    def _rg_args(self, q):
        """rg 参数按开关拼：-i（默认不区分大小写）/ --fixed-strings（默认字面量）。

        模式一律用 `-e` 传，避免用户输入以 `-` 开头时被 rg 当成选项。
        """
        args = ["--line-number", "--no-heading", "--color", "never",
                "--max-filesize", "1M", "--max-count", "40",
                "--glob", "!.git/**", "--glob", "!node_modules/**",
                "--glob", "!.venv/**", "--glob", "!modules_repo/**"]
        if not self.case_sensitive:
            args.append("-i")
        if not self.use_regex:
            args.append("--fixed-strings")
        args += ["-e", q, "."]
        return args

    def _search_rg(self, rg, q):
        try:
            cp = subprocess.run(
                [rg] + self._rg_args(q),
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

    def _text_files(self):
        """工作区内可参与搜索/替换的文本文件（跳过 .git、非文本扩展名、>1MB）。"""
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
                except OSError:
                    continue
                yield path

    def _search_walk(self, q):
        try:
            rx = self._matcher(q)
        except re.error as e:
            self.hint.setText("正则写错了：%s" % e)
            return None
        hits = []
        try:
            for path in self._text_files():
                try:
                    with open(path, "r", encoding="utf-8",
                              errors="replace") as f:
                        for no, line in enumerate(f, 1):
                            if rx.search(line):
                                hits.append((path, no, line.rstrip()))
                                if len(hits) >= 100:
                                    return hits
                except OSError:
                    continue
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "python workspace search")
        return hits

    def replace_all(self):
        """全部替换：先备份、再原子写。替换文本按字面量处理（不解析 \\1）。

        返回替换的处数；0 表示没做（没搜索词 / 正则错 / 用户取消）。
        """
        q = self.query.text().strip()
        repl = self.replace_input.text()
        if not q:
            self.hint.setText("先输入要搜索的内容")
            return 0
        try:
            rx = self._matcher(q)
        except re.error as e:
            self.hint.setText("正则写错了：%s" % e)
            return 0
        targets = []
        total = 0
        for path in self._text_files():
            try:
                with open(path, "r", encoding="utf-8", newline="") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            if "\0" in text:
                continue
            found = len(rx.findall(text))
            if found:
                targets.append((path, text, found))
                total += found
        if not targets:
            self.hint.setText("没有可替换的内容")
            return 0
        if QMessageBox.question(
                self, "全部替换",
                "将在 %d 个文件里替换 %d 处，并先备份到 "
                "data/.x6_replace_backup/。\n确定继续？"
                % (len(targets), total)) != QMessageBox.Yes:
            self.hint.setText("已取消替换")
            return 0
        backup_dir = os.path.join(self.root, "data", ".x6_replace_backup",
                                  time.strftime("%Y%m%d-%H%M%S"))
        done = files = 0
        for path, text, _found in targets:
            rel = os.path.relpath(path, self.root).replace("\\", "/")
            try:
                os.makedirs(backup_dir, exist_ok=True)
                shutil.copy2(path, os.path.join(
                    backup_dir, rel.replace("/", "__")))
                new_text = rx.sub(lambda _m: repl, text)
                tmp = path + ".x6tmp"
                with open(tmp, "w", encoding="utf-8", newline="") as f:
                    f.write(new_text)
                os.replace(tmp, path)
                files += 1
                done += len(rx.findall(text))
            except OSError as e:  # 静默是故意的 - 单个文件失败不影响其它
                _x6_swallowed(__name__, e, "replace %s" % path)
        self.run_search()
        self.hint.setText("替换 %d 处 / %d 个文件，备份：%s"
                          % (done, files, backup_dir))
        return done

    def _open_item(self, item):
        data = item.data(Qt.UserRole)
        if data:
            self.openRequested.emit(str(data[0]), int(data[1]))


class SidebarHost(QStackedWidget):
    """资源管理器 + 搜索 + Git 三个左侧视图的容器。"""

    openAtLineRequested = pyqtSignal(str, int)
    openPathRequested = pyqtSignal(str)
    diffRequested = pyqtSignal(str, str)
    commitDone = pyqtSignal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebarStack")
        self.explorer = None
        self.search_view = SearchPanel(root, self)
        self.search_view.openRequested.connect(self.openAtLineRequested)
        self.scm_view = ScmPanel(root, self)
        self.scm_view.openRequested.connect(self.openPathRequested)
        self.scm_view.diffRequested.connect(self.diffRequested)
        self.scm_view.commitDone.connect(self.commitDone)

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



