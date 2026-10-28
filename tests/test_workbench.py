# -*- coding: utf-8 -*-
"""工作台测试：编辑器 + AI 面板同屏（无功能页签）。"""

import os
import shutil
import subprocess
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QTabWidget  # noqa: E402


class _FakeTrunk:
    base = BASE
    config = {}

    def __init__(self):
        self.modules = {}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def wb(app):
    from gui.workbench_dialog import WorkbenchWindow
    w = WorkbenchWindow(_FakeTrunk())
    w.show()
    yield w
    w.close()


# ---------------- 结构 ----------------
def test_workbench_builds(wb):
    assert wb.windowTitle()
    assert wb._editor is not None, "编辑器应被嵌入"
    assert wb.ai_dock is not None


def test_no_feature_tabs(wb):
    """核心要求：不存在"编辑器/旅程/Agent"这种功能页签。"""
    tabs = wb.findChildren(QTabWidget)
    assert len(tabs) <= 1, "工作台不应有多个 QTabWidget"
    if tabs:
        names = [tabs[0].tabText(i) for i in range(tabs[0].count())]
        assert not any("旅程" in n or "Agent" in n for n in names), names


def test_ai_panel_on_right_of_editor(wb):
    """VS Code 风格：活动栏 | 编辑器 + 右侧 Secondary Side Bar（QDockWidget）。"""
    assert wb.splitter.count() == 2
    assert wb.splitter.widget(0) is wb.activity_list
    assert wb.ai_host.widget() is wb.ai_dock
    from PyQt5.QtCore import Qt
    assert wb.dockWidgetArea(wb.ai_host) == Qt.RightDockWidgetArea


def test_activity_bar_and_status_bar(wb):
    """活动栏是单色图标视图入口，底部状态栏展示分支/行列/语言。"""
    assert wb.activity_list.count() == 6
    assert wb.sidebar_stack is not None
    assert wb.sidebar_stack.count() == 3
    for i in range(wb.activity_list.count()):
        assert wb.activity_list.item(i).text() == ""
        assert not wb.activity_list.item(i).icon().isNull()
    assert wb.command is not None
    assert wb.status_label is not None
    assert wb.path_label is not None
    assert "UTF-8" in wb.path_label.text()
    assert wb.branch_label.text().startswith("⎇")
    assert wb.lang_label.text() == "Plain Text"
    assert wb.error_label.text().startswith("⚠")
    assert wb.pos_label.text() == "行 1, 列 1"
    assert wb._editor.breadcrumb is not None
    assert wb._editor.breadcrumb.text().startswith("📄 ")

    from PyQt5.QtGui import QTextCursor
    w = wb._editor.tabs.currentWidget()
    w.setPlainText("a\nbc")
    w.moveCursor(QTextCursor.End)
    assert wb.pos_label.text() == "行 2, 列 3", wb.pos_label.text()


def test_sidebar_not_collapsed(wb):
    """回归：QStackedWidget 最小宽度是 0，曾被 QSplitter 压成 0 宽。"""
    wb.resize(1440, 900)
    wb.show()
    QApplication.processEvents()
    assert wb.sidebar_stack.isVisible()
    assert wb.sidebar_stack.width() >= 200, wb.sidebar_stack.width()
    assert wb._editor.tree.isVisible()


def test_activity_views_and_command_center(wb):
    """搜索/Git 是左侧视图，命令中心能切到搜索。"""
    wb._on_activity_clicked(wb.activity_list.item(1))
    assert wb.sidebar_stack.currentIndex() == 1
    wb._on_activity_clicked(wb.activity_list.item(2))
    assert wb.sidebar_stack.currentIndex() == 2
    assert wb.scm_view.branch.text().startswith("分支：")
    wb.command.setText("搜索工作区")
    wb._run_command()
    assert wb.sidebar_stack.currentIndex() == 1


def test_syntax_error_status(wb):
    """语法错误数同步到状态栏；修好后归零。"""
    w = wb._editor.tabs.currentWidget()
    w.setPlainText("def broken(:\n")
    w._check_syntax()
    assert wb.error_label.text() == "⚠ 1", wb.error_label.text()
    w.setPlainText("")
    w._check_syntax()
    assert wb.error_label.text() == "⚠ 0"
    w._dirty = False
    wb._editor._update_tab_title(w)


# ---------------- P1：编辑器骨架 ----------------
def test_breadcrumb_is_between_tab_bar_and_editor(wb):
    """VS Code 顺序：标签栏 → 面包屑 → 编辑区。"""
    from PyQt5.QtCore import QPoint
    ed = wb._editor
    wb.resize(1440, 900)
    wb.show()
    QApplication.processEvents()
    tabs = ed.tabs
    y_bar = tabs.bar.mapTo(tabs, QPoint(0, 0)).y()
    y_crumb = ed.breadcrumb.mapTo(tabs, QPoint(0, 0)).y()
    y_edit = tabs.stack.mapTo(tabs, QPoint(0, 0)).y()
    assert y_bar < y_crumb < y_edit, (y_bar, y_crumb, y_edit)


def test_split_shares_document_and_closes(wb):
    """分屏是同一份文档的第二个视图，不是复制一份文本。"""
    ed = wb._editor
    w = ed.tabs.currentWidget()
    w.setPlainText("x = 1\n")
    ed.toggle_split()
    sec = ed.tabs.secondary()
    assert sec is not None
    assert sec.document() is w.document()
    w.setPlainText("y = 2\n")
    assert sec.toPlainText() == "y = 2\n"
    ed.toggle_split()
    assert ed.tabs.secondary() is None
    w.setPlainText("")
    w._dirty = False
    ed._update_tab_title(w)


def test_minimap_visible_by_default_and_toggle(wb):
    ed = wb._editor
    w = ed.tabs.currentWidget()
    assert w.is_minimap_visible() is True
    assert w.minimap_width() == w._minimap.WIDTH
    ed.toggle_minimap()
    assert w.is_minimap_visible() is False
    assert w.minimap_width() == 0
    ed.toggle_minimap()
    assert w.minimap_width() == w._minimap.WIDTH


def test_minimap_paints_and_click_jumps(app):
    """minimap 真正画一次并且点击能跳行（paint/goto 之前完全没覆盖）。"""
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtGui import QMouseEvent

    from gui.code_editor_widget import CodeEditWidget

    w = CodeEditWidget()
    w.resize(400, 200)
    w.show()
    try:
        w.setPlainText("".join("line %d\n" % i for i in range(200)))
        app.processEvents()
        w._minimap.resize(76, 200)
        pix = w._minimap.grab()                 # 触发 paintEvent
        assert not pix.isNull()
        before = w.textCursor().blockNumber()
        w._minimap.mousePressEvent(QMouseEvent(
            QMouseEvent.MouseButtonPress, QPoint(5, 100),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        assert w.textCursor().blockNumber() > before
        w._minimap.mouseMoveEvent(QMouseEvent(
            QMouseEvent.MouseMove, QPoint(5, 10),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        w._minimap.resize(76, 0)               # 高度为 0 的提前返回分支
        w._minimap.grab()
    finally:
        w.close()
        w.deleteLater()


def test_bottom_panel_has_output_problem_terminal(wb):
    """底部面板是「输出 / 问题 / 终端 / 差异」四个页签。"""
    b = wb._editor.bottom
    assert b.bar.count() == 4
    assert b.bar.tabText(0) == "输出"
    assert b.bar.tabText(2) == "终端"
    assert b.bar.tabText(3).startswith("差异")
    w = wb._editor.tabs.currentWidget()
    w.setPlainText("def broken(:\n")
    w._check_syntax()
    assert b.problems.count() == 1
    assert "第 1 行" in b.problems.item(0).text()
    w.setPlainText("")
    w._check_syntax()
    assert b.problems.count() == 0
    w._dirty = False
    wb._editor._update_tab_title(w)


def test_bottom_diff_tab_shows_colored_lines(wb):
    """差异页按 +/- 着色并自动切过去。"""
    b = wb._editor.bottom
    text = b.show_diff("gui/x.py",
                       "--- a/gui/x.py\n+++ b/gui/x.py\n"
                       "@@ -1 +1 @@\n-print(1)\n+print(2)\n")
    assert b.bar.currentIndex() == b.diff_index
    assert b.bar.tabText(b.diff_index).startswith("差异 x.py")
    assert "+print(2)" in text
    assert "-print(1)" in text
    assert b.diff.isReadOnly()
    body = b.diff.toPlainText()
    assert "-print(1)" in body and "+print(2)" in body


def test_sidebar_diff_and_commit_signals_reach_editor(wb):
    """SidebarHost 的信号必须真的接到编辑器（差异页 + 输出页）。"""
    wb.sidebar_stack.diffRequested.emit("gui/y.py", "+added\n-removed\n")
    b = wb._editor.bottom
    assert b.bar.currentIndex() == b.diff_index
    assert "+added" in b.diff.toPlainText()
    wb.sidebar_stack.commitDone.emit("abc1234")
    assert "[git] 已提交 abc1234" in wb._editor.output.toPlainText()



def test_terminal_cd_and_clear_are_local(wb):
    b = wb._editor.bottom
    root = b.cwd
    b._change_dir("gui")
    assert b.cwd.endswith("gui")
    b._change_dir(root)
    b._echo("hello")
    b.run_terminal("cls")
    assert b.term.toPlainText() == ""


# ---------------- P2：资源管理器 ----------------
def test_git_status_colors_in_explorer(wb):
    """文件树用文件名颜色标出 Git 改动（不换图标）。"""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QBrush
    model = wb._editor.fs_model
    path = os.path.join(BASE, "run.py")
    model.refresh_git(BASE, {path: "M"})
    idx = model.index(path)
    assert idx.isValid()
    brush = model.data(idx, Qt.ForegroundRole)
    assert isinstance(brush, QBrush)
    assert brush.color().name() == model.STATUS_COLORS["M"]
    model.refresh_git(BASE, {})
    assert model.git_status_for(path) == ""


def test_git_status_entries_reads_repo():
    from gui.ide_sidebar import git_status_entries
    entries = git_status_entries(BASE)
    if entries is None:
        pytest.skip("本机没有 git")
    assert all(len(rel) > 0 for _s, rel in entries)
    # 中文路径必须保持原样：git 默认会把它们输出成 "docs/\344\270\255..."，
    # 那样既对不上文件树路径（不着色），SCM 列表也会是乱码。
    assert not any("\\3" in rel for _s, rel in entries), entries


def test_git_status_entries_uses_utf8_raw_paths(monkeypatch):
    """显式带 core.quotePath=false，中文路径原样返回。"""
    from gui import ide_explorer

    class _Done:
        returncode = 0
        stdout = " M docs/中文文档.md\n?? gui/新文件.py\n"

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return _Done()

    monkeypatch.setattr(ide_explorer.subprocess, "run", fake_run)
    entries = ide_explorer.git_status_entries(".")
    assert "core.quotePath=false" in seen["cmd"], seen["cmd"]
    assert entries == [("M", "docs/中文文档.md"),
                       ("??", "gui/新文件.py")], entries


# ---------------- P1：Git 暂存 / 提交 / 差异 ----------------
def _git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "core.quotePath=false"] + list(args),
        cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=20)


def _init_git_repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("本机没有 git")
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@example.com", cwd=tmp_path)
    _git("config", "user.name", "tester", cwd=tmp_path)
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    _git("add", "a.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "init", cwd=tmp_path)


def test_scm_stage_diff_and_commit(app, tmp_path):
    """真实仓库走一遍：看 diff → 暂存 → 提交。"""
    from PyQt5.QtCore import Qt

    from gui.ide_sidebar import ScmPanel
    _init_git_repo(tmp_path)
    panel = ScmPanel(str(tmp_path))
    try:
        (tmp_path / "a.py").write_text("print(2)\n", encoding="utf-8")
        panel.refresh()
        assert panel.changes.count() == 1
        item = panel.changes.item(0)
        assert item.data(Qt.UserRole + 1) == "a.py"
        assert item.data(Qt.UserRole + 2).strip() == "M"
        assert item.foreground().color().name() == "#9a6700"

        panel.changes.setCurrentRow(0)
        diffs = []
        panel.diffRequested.connect(lambda rel, text: diffs.append((rel, text)))
        panel.emit_diff()
        assert diffs and diffs[0][0] == "a.py"
        assert "+print(2)" in diffs[0][1]
        assert "-print(1)" in diffs[0][1]

        assert panel.commit("   ") is False          # 空提交信息
        assert panel.commit("还没暂存") is False      # 暂存区为空
        assert panel.stage("a.py") is True

        panel.changes.setCurrentRow(0)               # refresh 后重新选中
        panel.emit_diff()
        assert "+print(2)" in diffs[-1][1]           # 已暂存 → --cached

        done = []
        panel.commitDone.connect(done.append)
        assert panel.commit("改一行") is True
        assert done and done[0]
        assert _git("log", "-1", "--pretty=%s",
                    cwd=tmp_path).stdout.strip() == "改一行"
        assert panel.changes.count() == 0
        assert "已提交" in panel.hint.text()
    finally:
        panel.deleteLater()


def test_scm_untracked_placeholder_and_discard(app, tmp_path, monkeypatch):
    """未跟踪文件先给占位diff，放弃改动要能删掉它。"""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QMessageBox

    from gui.ide_sidebar import ScmPanel
    _init_git_repo(tmp_path)
    panel = ScmPanel(str(tmp_path))
    try:
        new = tmp_path / "new.py"
        new.write_text("x = 1\n", encoding="utf-8")
        panel.refresh()
        rows = {panel.changes.item(i).data(Qt.UserRole + 1): i
                for i in range(panel.changes.count())}
        assert "new.py" in rows
        panel.changes.setCurrentRow(rows["new.py"])
        seen = []
        panel.diffRequested.connect(lambda rel, text: seen.append(text))
        panel.emit_diff()
        assert "未跟踪" in seen[0]

        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.Yes))
        assert panel.discard("new.py") is True
        assert not new.exists()
    finally:
        panel.deleteLater()


def test_scm_stage_all_unstage_and_discard_tracked(app, tmp_path, monkeypatch):
    """全部暂存 / 取消暂存 / 放弃已跟踪文件的改动（含取消确认）。"""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QMessageBox

    from gui.ide_sidebar import ScmPanel
    _init_git_repo(tmp_path)
    panel = ScmPanel(str(tmp_path))
    try:
        (tmp_path / "a.py").write_text("print(9)\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("b = 1\n", encoding="utf-8")
        panel.refresh()
        assert panel.changes.count() == 2
        assert panel.stage_all() is True
        rows = {panel.changes.item(i).data(Qt.UserRole + 1):
                panel.changes.item(i).data(Qt.UserRole + 2).strip()
                for i in range(panel.changes.count())}
        assert rows["b.py"] == "A"
        assert rows["a.py"] == "M"
        assert panel.unstage("b.py") is True
        rows = {panel.changes.item(i).data(Qt.UserRole + 1):
                panel.changes.item(i).data(Qt.UserRole + 2).strip()
                for i in range(panel.changes.count())}
        assert rows["b.py"] == "??"

        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.No))
        assert panel.discard("a.py") is False
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "print(9)\n"

        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.Yes))
        # 已暂存的改动要连暂存区一起退回 HEAD，不能只从索引恢复
        assert panel.discard("a.py") is True
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "print(1)\n"

        # 新加入暂存区的文件：HEAD 里没有，放弃就等于取消暂存 + 删文件
        assert panel.stage("b.py") is True
        assert panel.discard("b.py") is True
        assert not (tmp_path / "b.py").exists()
    finally:
        panel.deleteLater()


def test_scm_non_git_dir_degrades(app, tmp_path):
    """不是 Git 仓库时给提示，不能抛异常。"""
    from gui.ide_sidebar import ScmPanel
    panel = ScmPanel(str(tmp_path))
    try:
        assert "未检测到" in panel.branch.text()
        assert panel.changes.count() == 0
        assert panel.commit("x") is False
        assert panel.stage_all() is False
        assert panel.emit_diff() == ""
    finally:
        panel.deleteLater()


def test_explorer_new_file(wb, monkeypatch, tmp_path):
    """右键「新建文件」走 QInputDialog；不新增 QAction。"""
    from PyQt5.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("note.md", True)))
    ed = wb._editor
    before = ed.tabs.count()
    ed._create_entry(str(tmp_path), make_dir=False)
    assert (tmp_path / "note.md").exists()
    assert ed.tabs.count() == before + 1
    # 关闭测试打开的标签，避免影响后续用例
    for i in range(ed.tabs.count()):
        w = ed.tabs.widget(i)
        if getattr(w, "filepath", "") == str(tmp_path / "note.md"):
            ed._close_tab(i)
            break


def test_explorer_new_folder(wb, monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("sub", True)))
    wb._editor._create_entry(str(tmp_path), make_dir=True)
    assert (tmp_path / "sub").is_dir()


def test_explorer_rename_entry(wb, monkeypatch, tmp_path):
    """右键「重命名」：改名后刷新 Git 标记。"""
    from PyQt5.QtWidgets import QInputDialog
    src = tmp_path / "old.txt"
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("new.txt", True)))
    wb._editor._rename_entry(str(src))
    assert not src.exists()
    assert (tmp_path / "new.txt").exists()


def test_explorer_delete_entry(wb, monkeypatch, tmp_path):
    """右键「删除」：确认后真的删掉；取消则保留。"""
    from PyQt5.QtWidgets import QMessageBox
    victim = tmp_path / "bye.txt"
    victim.write_text("x", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    wb._editor._delete_entry(str(victim))
    assert victim.exists()
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    wb._editor._delete_entry(str(victim))
    assert not victim.exists()


def test_editor_jump_to_line(wb):
    """问题页双击 / minimap 跳转共用的 _jump_to_line，越界不能崩。"""
    ed = wb._editor
    w = ed._current_edit()
    old = w.toPlainText()
    try:
        w.setPlainText("a\nb\nc\n")
        ed._jump_to_line(3)
        assert w.textCursor().blockNumber() == 2
        ed._jump_to_line(99)   # 越界保持原位
        assert w.textCursor().blockNumber() == 2
    finally:
        w.setPlainText(old)


def test_search_input_fits_its_text(wb, app):
    """搜索框不能用 stylesheet margin 吃高度。

    老写法 `margin:6px 8px` + 固定 26px：26-12(margin)-4(padding)-2(border)
    只剩 8px 给 12px 文字，截图里就是上下被裁一半。
    """
    q = wb.search_view.query
    fm = q.fontMetrics()
    assert "margin" not in q.styleSheet(), q.styleSheet()
    assert q.height() >= fm.height() + 10, (q.height(), fm.height())
    wb._show_search()
    wb._editor_splitter.setSizes([200, 900])   # 侧栏拖到最窄
    app.processEvents()
    assert q.width() >= fm.horizontalAdvance(q.placeholderText()) + 24, (
        q.width(), fm.horizontalAdvance(q.placeholderText()))
    wb._editor_splitter.setSizes([260, 840])
    app.processEvents()


def test_activity_ai_entry_is_the_star_icon(wb):
    """活动栏第 6 个「米」字图标 = AI 助手：点一下聚焦 AI 输入框。"""
    bar = wb.activity_list
    assert bar.count() == 6
    item = bar.item(5)
    assert "AI" in item.toolTip()
    wb._ai_shown = True
    wb._on_activity_clicked(item)
    assert wb._ai_shown is True


def test_activity_icons_are_single_color(wb):
    """6 个活动栏图标都必须单色：实心笔画像素只能是灰(普通)或蓝(选中)。"""
    from PyQt5.QtCore import QSize
    from PyQt5.QtGui import QIcon, QImage

    from gui.ide_sidebar import _ICON_PX, activity_icon

    assert wb.activity_list.iconSize() == QSize(_ICON_PX, _ICON_PX), (
        "图标尺寸要和绘制尺寸 1:1，否则会被缩放插值")
    for kind in ("explorer", "search", "scm", "run", "extensions", "ai"):
        icon = activity_icon(kind)
        assert icon.availableSizes() == [QSize(_ICON_PX, _ICON_PX)], kind
        for state, expect in ((QIcon.Normal, (0x57, 0x60, 0x6a)),
                              (QIcon.Selected, (0x1d, 0x4e, 0xd8))):
            img = icon.pixmap(QSize(_ICON_PX, _ICON_PX), state,
                              QIcon.Off).toImage().convertToFormat(
                                  QImage.Format_ARGB32)
            solid = 0
            for y in range(img.height()):
                for x in range(img.width()):
                    c = img.pixelColor(x, y)
                    if c.alpha() < 200:   # 只查实心笔画，半透明是抗锯齿
                        continue
                    solid += 1
                    # 允许 ±2 的预乘/反预乘取整误差
                    assert abs(c.red() - expect[0]) <= 2, (
                        kind, state, (c.red(), c.green(), c.blue()))
                    assert abs(c.green() - expect[1]) <= 2, (
                        kind, state, (c.red(), c.green(), c.blue()))
                    assert abs(c.blue() - expect[2]) <= 2, (
                        kind, state, (c.red(), c.green(), c.blue()))
            assert solid > 0, kind


def test_activity_run_icon_is_outline():
    """「运行」要和其它图标一样是线稿：三角形内部必须透明。"""
    from PyQt5.QtCore import QSize
    from PyQt5.QtGui import QIcon, QImage

    from gui.ide_sidebar import activity_icon

    img = activity_icon("run").pixmap(QSize(22, 22), QIcon.Normal,
                                      QIcon.Off).toImage().convertToFormat(
                                          QImage.Format_ARGB32)
    assert img.pixelColor(10, 11).alpha() == 0     # 三角内部
    assert img.pixelColor(12, 7).alpha() > 200     # 上边描边


# ---------------- 收起 / 展开 ----------------
def test_toggle_ai(wb):
    """Ctrl+J 收起/展开 AI 面板（不再占用界面按钮）。"""
    start = wb._ai_shown
    wb.toggle_ai()
    assert wb._ai_shown is (not start)
    wb.toggle_ai()
    assert wb._ai_shown is start


def test_no_redundant_buttons_in_workbench(wb):
    """界面按钮必须精简：只保留无法用一句话替代的动作控制。"""
    from PyQt5.QtWidgets import QPushButton
    texts = [b.text() for b in wb.findChildren(QPushButton)]
    # 动作控制必须有（执行中要能立即停手，不能靠打字）
    assert any("开始" in t for t in texts), texts
    assert any("取消" in t for t in texts), texts
    # 这些已改为快捷键/拖动，不应再有按钮
    assert not any("全屏" in t for t in texts), "全屏应改用 F11"
    assert not any("收起" in t for t in texts), "收起应改用 Ctrl+J"


# ---------------- 弹出 / 收回 ----------------
def test_popup_and_dock_back(wb):
    wb.toggle_ai_popup()
    assert wb._ai_popup is not None
    assert wb.ai_host.isFloating()
    assert "收回" in wb.ai_dock.expand_btn.text()
    wb.toggle_ai_popup()
    assert wb._ai_popup is None
    assert not wb.ai_host.isFloating()
    assert "弹出" in wb.ai_dock.expand_btn.text()
    # 右侧 AI 是 QDockWidget（标准 Secondary Side Bar），不在 splitter 里
    assert wb.splitter.count() == 2
    assert wb.ai_host.widget() is wb.ai_dock
    from PyQt5.QtCore import Qt
    assert wb.dockWidgetArea(wb.ai_host) == Qt.RightDockWidgetArea


def test_popup_repeated_toggle(wb):
    for _ in range(3):
        wb.toggle_ai_popup()
    assert wb._ai_popup is not None
    wb.toggle_ai_popup()
    assert wb._ai_popup is None


# ---------------- 文件上下文 ----------------
def test_open_and_list_files(wb):
    wb.open_path(os.path.join(BASE, "run.py"))
    files = wb.editor_open_files()
    assert any(f.endswith("run.py") for f in files), files


# ---------------- 自然语言写代码 ----------------
def test_natural_language_defaults_to_code_agent():
    """工作台里“帮我写个…/加个…”不能被路由成聊天。"""
    from gui.workbench_ai_dock import resolve_explicit
    assert resolve_explicit("帮我写一个贪吃蛇小游戏") == "code"
    assert resolve_explicit("给 main 加参数解析") == "code"
    assert resolve_explicit("做一个登录页面") == "code"
    # 显式前缀才切走
    assert resolve_explicit("/chat 你好") is None
    assert resolve_explicit("/pc 打开浏览器") is None
    assert resolve_explicit("/computer 点击开始菜单") is None


def test_applied_file_opens_in_editor_and_is_editable(wb, tmp_path):
    """Agent 落盘后：新文件要在编辑器里完整打开，并且能手动改。"""
    p = tmp_path / "ai_snake.py"
    p.write_text("print('snake')\n", encoding="utf-8")
    wb.ai_dock._on_event("applied", {"applied": [str(p)],
                                     "backup_manifest": ""})
    QApplication.processEvents()
    w = wb._editor.tabs.currentWidget()
    assert getattr(w, "filepath", "") == str(p), getattr(w, "filepath", "")
    assert w.toPlainText() == "print('snake')\n"
    assert w.isReadOnly() is False

    # 同一个文件再次落盘：已开的 tab 要刷新成最新完整内容
    p.write_text("print('snake v2')\n", encoding="utf-8")
    wb.ai_dock._on_event("applied", {"applied": [str(p)],
                                     "backup_manifest": ""})
    assert w.toPlainText() == "print('snake v2')\n"

    for i in range(wb._editor.tabs.count()):
        if wb._editor.tabs.widget(i) is w:
            wb._editor._close_tab(i)
            break


def test_chat_answer_is_shown_in_timeline(wb):
    """走 /chat 时模型回答要写进时间线，不能只显示“对话完成”。"""
    wb.ai_dock.timeline.clear()
    wb.ai_dock._on_event("done", {"step": "对话完成",
                                  "result": "这是模型的回答"})
    assert "这是模型的回答" in wb.ai_dock.timeline.toPlainText()


def test_run_job_passes_code_mode(wb, monkeypatch):
    """工作台启动任务时必须把 explicit 传给编排器，而不是靠关键词猜。"""
    import core.agent_orchestrator as orch_mod
    captured = {}

    class _FakeOrch:
        def __init__(self, *a, **k):
            pass

        def run(self, goal, **kw):
            captured.update(kw)
            captured["goal"] = goal
            return {"ok": True, "rounds_used": 1,
                    "stop_reason": "tests_green"}

    monkeypatch.setattr(orch_mod, "AgentOrchestrator", _FakeOrch)
    wb.ai_dock._run_job("帮我写一个贪吃蛇小游戏", open_files=[])
    assert captured.get("goal") == "帮我写一个贪吃蛇小游戏"
    assert captured.get("explicit") == "code"


def test_set_goal(wb):
    wb.set_goal("给 main 加参数解析")
    assert wb.ai_dock.goal.toPlainText() == "给 main 加参数解析"


# ---------------- AI 面板控件 ----------------
def test_agent_dock_controls(wb):
    dock = wb.ai_dock
    for attr in ("goal", "start_btn", "pause_btn", "cancel_btn", "timeline"):
        assert hasattr(dock, attr), "缺少 %s" % attr
    assert dock.pause_btn.isEnabled() is False
    assert dock.cancel_btn.isEnabled() is False


def test_empty_goal_is_rejected_without_dialog(wb):
    """空目标必须直接拒绝。

    ⚠️ 不能用 QMessageBox 做校验：offscreen 下它会阻塞并让进程崩溃
       （实测退出码 -1073741819）。所以校验逻辑必须与弹窗分离。
    """
    wb.ai_dock.goal.setPlainText("   ")
    assert wb.ai_dock.can_start() is False
    wb.ai_dock.start()                 # 不弹框、不抛异常
    assert "请先描述" in wb.ai_dock.timeline.toPlainText()


def test_non_empty_goal_can_start(wb):
    wb.ai_dock.goal.setPlainText("给 main 加参数")
    assert wb.ai_dock.can_start() is True


# ---------------- 旧入口兼容 ----------------
def test_legacy_entries_point_to_workbench():
    for rel in (os.path.join("gui", "mixins", "agent_launcher_mixin.py"),
                os.path.join("gui", "mixins", "dialog_mixin.py")):
        src = open(os.path.join(BASE, rel), encoding="utf-8").read()
        assert "open_workbench" in src, rel


# ---------------- 覆盖率补充：AgentDock / 快捷键 ----------------
def test_agent_dock_controls_disabled_before_start(wb):
    dock = wb.ai_dock
    assert dock.pause_btn.isEnabled() is False
    assert dock.cancel_btn.isEnabled() is False


def test_toggle_pause_without_orchestrator_is_safe(wb):
    wb.ai_dock.orchestrator = None
    wb.ai_dock.toggle_pause()      # 不应抛异常
    wb.ai_dock.cancel()            # 不应抛异常


def test_agent_event_appends_to_timeline(wb):
    wb.ai_dock.timeline.clear()
    wb.ai_dock._on_event("测试步骤")
    assert "测试步骤" in wb.ai_dock.timeline.toPlainText()
    wb.ai_dock._on_event("步骤", {"step": "来自 dict 的步骤"})
    assert "来自 dict 的步骤" in wb.ai_dock.timeline.toPlainText()


def test_open_files_returns_list(wb):
    files = wb.editor_open_files()
    assert isinstance(files, list)


def test_toggle_fullscreen_does_not_raise(wb):
    wb.toggle_fullscreen()
    wb.toggle_fullscreen()


def test_shortcuts_installed(wb):
    """Ctrl+J / F11 通过 QShortcut 注入，不作为按钮存在。"""
    from PyQt5.QtWidgets import QShortcut
    keys = []
    for sc in wb.findChildren(QShortcut):
        keys.append(sc.key().toString())
    assert any("Ctrl+J" in k for k in keys), keys
    assert any("F11" in k for k in keys), keys


def test_ai_panel_round_limit_and_queue_visible(wb):
    """轮次上限可配置 + 任务队列是面板的一等公民。"""
    spin = wb.ai_dock.rounds_spin
    assert spin.minimum() == 1 and spin.maximum() == 15
    assert 1 <= spin.value() <= 15
    assert wb.ai_dock.queue_list is not None
    assert wb.ai_dock.queue_list.toolTip()


def test_editor_toolbar_is_grouped(wb):
    """文件操作在资源管理器顶部；编辑器工具条只留运行 / AI / 关闭。"""
    from PyQt5.QtWidgets import QPushButton
    buttons = wb.findChildren(QPushButton)
    labels = [b.text() for b in buttons]
    for want in ("▶ 运行", "🔧 AI 修复", "✕ 关闭"):
        assert any(want in x for x in labels), labels
    tips = [b.toolTip() for b in buttons]
    for want in ("新建标签页", "打开文件", "保存当前文件", "另存为"):
        assert any(want in x for x in tips), tips


# ---------------- 覆盖率补充：AgentDock 执行路径 ----------------
class _FakeOrch:
    instances = []

    def __init__(self, trunk, root=None, event_cb=None, approval_cb=None,
                 open_files=None):
        self.trunk = trunk
        self.root = root
        self.event_cb = event_cb
        self.approval_cb = approval_cb
        self.open_files = list(open_files or [])
        self.paused = False
        self.cancelled = False
        self.result = {"ok": True}
        _FakeOrch.instances.append(self)

    def run(self, goal, **_kw):
        if self.event_cb:
            self.event_cb("步骤一", {"step": "步骤一"})
        return self.result

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def cancel(self):
        self.cancelled = True


def _install_fake_orch(monkeypatch):
    import core.agent_orchestrator as ao
    _FakeOrch.instances = []
    monkeypatch.setattr(ao, "AgentOrchestrator", _FakeOrch)
    return _FakeOrch


def test_start_runs_orchestrator(wb, monkeypatch):
    fake = _install_fake_orch(monkeypatch)
    wb.ai_dock.goal.setPlainText("给 main 加参数")
    wb.ai_dock.start()
    assert fake.instances, "应该创建了 orchestrator"
    text = wb.ai_dock.timeline.toPlainText()
    assert "目标: 给 main 加参数" in text
    assert "步骤一" in text
    assert wb.ai_dock.start_btn.isEnabled() is True


def test_start_reports_failure_result(wb, monkeypatch):
    fake = _install_fake_orch(monkeypatch)
    monkeypatch.setattr(_FakeOrch, "run", lambda self, g, **k: {"ok": False, "error": "boom"})
    wb.ai_dock.goal.setPlainText("x")
    wb.ai_dock.start()
    assert "未完成" in wb.ai_dock.timeline.toPlainText()


def test_start_is_rejected_while_a_job_is_running(wb, monkeypatch):
    """同一时刻只允许一个 Agent：否则两套 orchestrator 并发改同一份文件。"""
    fake = _install_fake_orch(monkeypatch)
    wb.ai_dock._running = True
    wb.ai_dock.timeline.clear()
    try:
        wb.ai_dock.goal.setPlainText("再来一个")
        wb.ai_dock.start()
        assert fake.instances == []
        assert "已有任务在运行" in wb.ai_dock.timeline.toPlainText()
    finally:
        wb.ai_dock._running = False


def test_on_done_releases_running_flag(wb):
    wb.ai_dock._running = True
    wb.ai_dock._on_done({"ok": True})
    assert wb.ai_dock._running is False
    assert wb.ai_dock.start_btn.isEnabled() is True


def test_start_handles_exception(wb, monkeypatch):
    _install_fake_orch(monkeypatch)

    def boom(self, goal, **_k):
        raise RuntimeError("炸了")

    monkeypatch.setattr(_FakeOrch, "run", boom)
    wb.ai_dock.goal.setPlainText("x")
    wb.ai_dock.start()
    assert "错误" in wb.ai_dock.timeline.toPlainText()
    assert wb.ai_dock.start_btn.isEnabled() is True


def test_pause_and_resume_cycle(wb, monkeypatch):
    _install_fake_orch(monkeypatch)
    wb.ai_dock.goal.setPlainText("x")
    wb.ai_dock.start()
    orch = wb.ai_dock.orchestrator
    wb.ai_dock.toggle_pause()
    assert orch.paused is True
    wb.ai_dock.toggle_pause()
    assert orch.paused is False


def test_cancel_marks_orchestrator(wb, monkeypatch):
    _install_fake_orch(monkeypatch)
    wb.ai_dock.goal.setPlainText("x")
    wb.ai_dock.start()
    orch = wb.ai_dock.orchestrator
    wb.ai_dock.cancel()
    assert orch.cancelled is True


def test_open_with_agent_passes_files(wb, monkeypatch):
    fake = _install_fake_orch(monkeypatch)
    import os as _os
    wb.open_path(_os.path.join(BASE, "run.py"))
    wb.ai_dock.open_with_agent.setChecked(True)
    wb.ai_dock.goal.setPlainText("改一下")
    wb.ai_dock.start()
    assert fake.instances[-1].open_files, "应把打开的文件传给 Agent"


def test_approve_returns_bool(wb):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.join(BASE, "gui"))
    # 审批回调必须返回布尔（失败时 fail-closed 为 False）
    r = wb.ai_dock._approve("code", "diff --git ...")
    assert r in (True, False)


def test_plan_event_and_approval(wb, monkeypatch):
    """计划事件进时间线；plan 审批按确认/拒绝返回布尔。"""
    from PyQt5.QtWidgets import QMessageBox

    wb.ai_dock.timeline.clear()
    wb.ai_dock._on_event("plan", {
        "step": "执行计划已生成",
        "plan": {"summary": "重构计算", "steps": [
            {"title": "改文件", "files": ["a.py"], "risk": "low"}],
            "risks": ["回归风险"]},
    })
    text = wb.ai_dock.timeline.toPlainText()
    assert "执行步骤" in text and "改文件" in text

    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    assert wb.ai_dock._approve("plan", {"summary": "重构计算"}) is True
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    assert wb.ai_dock._approve("plan", {"summary": "重构计算"}) is False


# ---------------- 入口合并：只保留一个「工作台」 ----------------
def test_feature_registry_has_single_workbench():
    from core.feature_registry import FEATURES
    assert "workbench" in FEATURES
    f = FEATURES["workbench"]
    assert "工作台" in f.label
    assert f.action == "open_workbench"


def test_old_feature_ids_removed_from_menu():
    """三个旧入口必须从菜单里消失，只留 workbench。"""
    from core.feature_registry import MORE_MENU_GROUPS
    ids = [i for _g, group in MORE_MENU_GROUPS for i in group]
    for old in ("code_editor", "agent_journey", "code_agent"):
        assert old not in ids, "%s 仍在菜单里" % old
    assert "workbench" in ids


def test_old_feature_ids_still_resolve_as_alias():
    """旧 id 保留为别名，避免历史调用/文档失效。"""
    from core.feature_registry import get_feature
    for old in ("code_editor", "agent_journey", "code_agent"):
        f = get_feature(old)
        assert f is not None, "%s 解析失败" % old
        assert f.label == "工作台"


def test_toolbar_button_is_workbench(app):
    """主界面工具条只保留一个「工作台」按钮。"""
    import os as _os
    _os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from PyQt5.QtWidgets import QPushButton
    from gui.main_window import JarvisWindow
    w = JarvisWindow()
    try:
        w.show()
        app.processEvents()
        assert "工作台" in w.editor_btn.text()
        texts = [b.text() for b in w.findChildren(QPushButton)]
        for old in ("代码编辑器", "Agent 旅程", "AI 代码 Agent"):
            assert not any(old in x for x in texts), "残留旧按钮: %s" % old
        # 侧栏常驻入口必须是真按钮，而不是蓝色链接
        for attr, want in (("task_center_btn", "任务中心"),
                           ("command_palette_btn", "命令面板")):
            b = getattr(w, attr)
            assert isinstance(b, QPushButton), "%s 应为 QPushButton" % attr
            assert want in b.text(), (attr, b.text())
    finally:
        try:
            w.close()
        except Exception:  # 静默是故意的
            pass


# ---------------- 文字不被压扁（全局 padding 回归） ----------------
def test_global_button_padding_leaves_room_for_text(app):
    """回归：全局 QPushButton 的 padding 曾经是 10px。

    工作台工具条按钮高度只有 24~27px，24 - 20(上下padding) - 2(边框)
    = 2px 留给文字，中文被压成一条横线（"文字显示不全"）。
    这里断言 padding 不超过 6px，且最小高度够放一行 13px 中文。
    """
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QPushButton
    from gui.style import STYLE

    app.setStyleSheet(STYLE)
    assert "padding: 10px" not in STYLE, "全局按钮 padding 又变回 10px 了"
    b = QPushButton("▶ 开始")
    b.show()
    app.processEvents()
    fm = QFontMetrics(b.font())
    assert b.height() >= fm.height() + 8, (
        "按钮高度 %d 放不下一行 %dpx 文字" % (b.height(), fm.height()))
    b.close()


def test_workbench_buttons_have_enough_height(app):
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QAbstractButton

    from gui.style import STYLE
    from gui.workbench_dialog import WorkbenchWindow

    app.setStyleSheet(STYLE)

    class T:
        base = BASE
        config = {}

        def __init__(self):
            self.modules = {}

    wb = WorkbenchWindow(T())
    try:
        wb.show()
        app.processEvents()
        tight = []
        for b in wb.findChildren(QAbstractButton):
            if not b.text():
                continue
            fm = QFontMetrics(b.font())
            if b.height() < fm.height() + 4:
                tight.append((b.text()[:16], b.height(), fm.height()))
        assert not tight, "这些按钮高度不足以显示文字: %s" % tight
    finally:
        try:
            wb.close()
        except Exception:  # 静默是故意的
            pass
        QCoreApplication.processEvents()


# ---------------- P2：静态检查（桌面上真的跑一次 ruff / ast 兜底） ----------------
def _pump_until(app, cond, timeout=10.0):
    """等后台 QProcess 回调：一边 pump 事件循环，一边轮询条件。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_ruff_json_parser_and_command(monkeypatch):
    """ruff JSON → (行, 列, 规则码, 描述)；没装 ruff 时退回 python -m ruff。"""
    from gui import code_editor_widget as cew

    sample = ('[{"code":"F401","message":"`os` imported but unused",'
              '"location":{"row":3,"column":8}}]')
    assert cew.parse_ruff_json(sample) == [(3, 8, "F401", "`os` imported but unused")]
    assert cew.parse_ruff_json("不是 JSON") is None
    assert cew.parse_ruff_json('{"not": "a list"}') is None

    monkeypatch.setattr(cew.shutil, "which", lambda _n: None)
    cmd = cew.ruff_command("x.py")
    assert cmd[:3] == [cew.sys.executable, "-m", "ruff"], cmd
    assert cmd[-2:] == ["--", "x.py"], cmd

    monkeypatch.setattr(cew.shutil, "which", lambda _n: "C:/bin/ruff.exe")
    assert cew.ruff_command("x.py")[0] == "C:/bin/ruff.exe"


def test_ast_problems_is_the_fallback():
    from gui.code_editor_widget import ast_problems

    rows = ast_problems("def broken(:\n")
    assert rows and rows[0][0] == 1 and rows[0][2] == "SyntaxError"
    assert rows[0][1] >= 1
    assert ast_problems("x = 1\n") == []


def test_static_check_fills_problem_list(app, tmp_path):
    """打开/保存即检查：问题列表带 行/列/规则码，状态栏计数与之一致。"""
    from gui.code_editor_widget import CodeEditWidget

    path = tmp_path / "bad.py"
    path.write_text("import os\ndef broken(:\n", encoding="utf-8")
    w = CodeEditWidget()
    seen = []
    w.problemsChanged.connect(seen.append)
    try:
        w.filepath = str(path)          # setter 触发检查
        assert _pump_until(app, lambda: seen and seen[-1]), "静态检查没有回调"
        rows = seen[-1]
        assert rows, "含语法错误的文件应当至少报一条"
        assert rows[0][0] == 2, rows          # 语法错误在第 2 行
        assert rows[0][1] >= 1 and rows[0][2], rows
        assert w.problems() == rows
        assert w._syntax_errors == len(rows)
    finally:
        w.close()
        w.deleteLater()


def test_problem_page_shows_line_column_and_rule(wb):
    """问题页条目必须是「第 L 行:C  规则码  描述」，双击仍然只跳行。"""
    b = wb._editor.bottom
    b.set_problems([(2, 5, "F401", "`os` imported but unused")])
    text = b.problems.item(0).text()
    assert text.startswith("第 2 行:5"), text
    assert "F401" in text and "imported but unused" in text
    assert b.bar.tabText(1) == "问题 1"
    got = []
    b.jumpRequested.connect(got.append)
    b.problems.itemDoubleClicked.emit(b.problems.item(0))
    assert got == [2]
    b.set_problems([(7, "旧格式：只有行号和描述")])
    assert b.problems.item(0).text() == "第 7 行  旧格式：只有行号和描述"
    b.set_problems([])
    assert b.bar.tabText(1) == "问题"


def test_dialog_problems_follow_widget_problems(wb):
    """编辑器的事件只负责刷新，问题列表以控件自己的 problems() 为准。"""
    ed = wb._editor
    w = ed.tabs.currentWidget()
    w._set_problems([(4, 9, "E501", "行太长")])
    ed._refresh_problems(w)
    assert ed.bottom.problems.count() == 1
    assert "E501" in ed.bottom.problems.item(0).text()
    w._set_problems([])
    ed._refresh_problems(w)
    assert ed.bottom.problems.count() == 0
    w._dirty = False
    ed._update_tab_title(w)


# ---------------- P2：本地补全（本文件符号 + 关键字，不做 LSP） ----------------
def test_python_symbols_from_ast():
    from gui.code_editor_widget import python_symbols

    code = ("import os\nimport numpy as np\nfrom typing import List as L\n"
            "CONST = 1\nclass Widget:\n    def paint(self):\n"
            "        local = 2\n")
    syms = python_symbols(code)
    assert {"os", "np", "L", "CONST", "Widget", "paint", "local"} <= syms
    # 写到一半的语法错误：ast 整体失败，退回正则至少还能补 def/class
    assert "paint" in python_symbols("class A:\n    def paint(self,},\n")


def test_js_symbols_and_completion_words():
    from gui.code_editor_widget import completion_words, js_symbols

    code = "function draw() {}\nconst canvas = 1;\nclass Scene {}\n"
    assert {"draw", "canvas", "Scene"} <= js_symbols(code)
    js = completion_words(code, "app.js")
    assert {"function", "draw", "canvas"} <= set(js)
    assert "def" not in js
    py = completion_words("def main():\n    pass\n", "a.py")
    assert {"main", "print", "def"} <= set(py)


def test_completion_popup_uses_local_symbols(app):
    from gui.code_editor_widget import CodeEditWidget

    w = CodeEditWidget()
    try:
        w.setPlainText("def paint_event(self):\n    pass\n\npri")
        tc = w.textCursor()
        tc.movePosition(tc.End)
        w.setTextCursor(tc)
        w._try_complete()
        assert w._completer.completionPrefix() == "pri"
        assert "print" in w._completer.model().stringList()
        assert w._completer.completionCount() >= 1
        # 只有 1 个字符时不弹（避免每敲一个键就刷候选）
        w._completer.setCompletionPrefix("zzz")
        w.setPlainText("p")
        tc = w.textCursor(); tc.movePosition(tc.End); w.setTextCursor(tc)
        w._try_complete()
        assert w._completer.completionPrefix() == "zzz"
    finally:
        w.close()
        w.deleteLater()


def test_completion_skipped_in_comment_and_string(app):
    from gui.code_editor_widget import CodeEditWidget

    w = CodeEditWidget()
    try:
        w.setPlainText("x = 1  # pri")
        tc = w.textCursor(); tc.movePosition(tc.End); w.setTextCursor(tc)
        assert w._in_comment_or_string() is True
        w._completer.setCompletionPrefix("zzz")
        w._try_complete()
        assert w._completer.completionPrefix() == "zzz"

        w.setPlainText('s = "pri')
        tc = w.textCursor(); tc.movePosition(tc.End); w.setTextCursor(tc)
        assert w._in_comment_or_string() is True

        w.setPlainText('s = "abc" + pri')
        tc = w.textCursor(); tc.movePosition(tc.End); w.setTextCursor(tc)
        assert w._in_comment_or_string() is False
    finally:
        w.close()
        w.deleteLater()


def test_completion_inserts_word_and_only_for_code_files(app, tmp_path):
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QKeyEvent

    from gui.code_editor_widget import CodeEditWidget

    w = CodeEditWidget()
    try:
        w.setPlainText("pri")
        tc = w.textCursor(); tc.movePosition(tc.End); w.setTextCursor(tc)
        w._try_complete()
        w._insert_completion("print")
        assert w.toPlainText() == "print"

        # Ctrl+Space 手动触发（1 个字符也弹）
        w.setPlainText("pri")
        tc = w.textCursor(); tc.movePosition(tc.End); w.setTextCursor(tc)
        w._completer.setCompletionPrefix("")
        ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.ControlModifier, " ")
        w.keyPressEvent(ev)
        assert w._completer.completionPrefix() == "pri"

        # Markdown 不启用补全
        w.setPlainText("pri")
        w.filepath = str(tmp_path / "note.md")
        assert w._completion_enabled() is False
    finally:
        w.close()
        w.deleteLater()
