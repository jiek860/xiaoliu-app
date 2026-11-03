# -*- coding: utf-8 -*-
"""第 7 批：编辑器保存链路 + 语言服务入口的 GUI 验收。

验收条目原文（诊断与优化方案.md 7.3 第 7 批）：
「装 LSP 可跳转/引用/诊断、没装不报错；保存自动格式化且可撤销。」

这里不构造整个 CodeEditorDialog（会拉起 git 模型 / 资源管理器），
而是用真 `EditorSaveMixin` + 真 `CodeEditWidget` + 假 trunk，验证：
  * 保存格式化：磁盘是格式化后的内容、编辑器一次 Ctrl+Z 退回手写版、留快照；
  * 保存格式化默认 off：原样落盘；
  * 没装语言服务：所有入口只提示一句、返回 None，绝不抛异常；
  * 右键菜单确实挂上 5 个语言服务动作（不新增按钮预算）。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from PyQt5.QtGui import QTextCursor  # noqa: E402
from PyQt5.QtWidgets import QMenu  # noqa: E402

from core import code_format as cf  # noqa: E402
from gui.code_editor_widget import CodeEditWidget  # noqa: E402
from gui.editor_save import EditorSaveMixin  # noqa: E402


class _Trunk:
    """假躯干：只要 rule()，没有 base/get_workspace_index 也照样跑。"""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def rule(self, name, default=None):
        return self.values.get(name, default)


class _Host(EditorSaveMixin):
    """最小宿主：只补齐 _save_w 需要的那几个回调。"""

    def __init__(self, widget, root="", trunk=None):
        self.widget = widget
        self.root = str(root or "")
        self.trunk = trunk
        self.statuses = []
        self.breadcrumb = 0
        self.git_marks = 0

    def _current_edit(self):
        return self.widget

    def _update_breadcrumb(self, *_):
        self.breadcrumb += 1

    def refresh_git_marks(self):
        self.git_marks += 1

    def _status(self, message, timeout=0):
        self.statuses.append(str(message))


def _fake_formatter(tmp_path, body="sys.stdout.write(text.replace('x = 1', 'x=1'))"):
    """真子进程假格式化器：读 stdin、按 body 变换、写 stdout。"""
    script = tmp_path / "fake_fmt.py"
    script.write_text(
        "import sys\ntext = sys.stdin.read()\n" + body + "\n", encoding="utf-8")
    return [sys.executable, str(script)]


def _patch_formatter(monkeypatch, argv):
    monkeypatch.setattr(cf, "_exe", lambda _fmt: list(argv))


def _widget(qtbot, tmp_path, text="x = 1\n", name="a.py"):
    root = tmp_path / "p"
    root.mkdir(exist_ok=True)
    target = root / name
    target.write_text(text, encoding="utf-8")
    w = CodeEditWidget()
    qtbot.addWidget(w)
    w.setPlainText(text)
    w.filepath = str(target)   # 真路径（语言服务/快照都要用到）
    return w, root, target


def test_dialog_save_comes_from_mixin():
    """搬家后 CodeEditorDialog 的保存动作必须解析到 EditorSaveMixin。"""
    from gui.code_editor_dialog import CodeEditorDialog
    assert EditorSaveMixin in CodeEditorDialog.__mro__
    assert CodeEditorDialog._save_w.__qualname__.startswith("EditorSaveMixin.")
    assert CodeEditorDialog.save_file.__qualname__.startswith("EditorSaveMixin.")


def test_save_without_switch_writes_raw(tmp_path, qtbot, monkeypatch):
    """规则默认 off：就算装了格式化工具也不动用户文件。"""
    _patch_formatter(monkeypatch, _fake_formatter(tmp_path))
    w, root, target = _widget(qtbot, tmp_path)
    host = _Host(w, root, _Trunk())          # 没有 编辑.保存格式化 → off
    host._save_w(w)
    assert target.read_text(encoding="utf-8") == "x = 1\n"
    assert w.toPlainText() == "x = 1\n"
    assert "格式化" not in host.statuses[-1]
    assert not (root / "backups" / "format").exists()


def test_save_formats_and_undoes_when_switch_on(tmp_path, qtbot, monkeypatch):
    """规则 on：落盘是格式化结果，编辑器里一次 Ctrl+Z 回到手写样子。"""
    _patch_formatter(monkeypatch, _fake_formatter(tmp_path))
    w, root, target = _widget(qtbot, tmp_path)
    host = _Host(w, root, _Trunk({"编辑.保存格式化": "on"}))
    host._save_w(w)
    assert target.read_text(encoding="utf-8") == "x=1\n", "磁盘要是格式化后的"
    assert w.toPlainText() == "x=1\n"
    assert "格式化" in host.statuses[-1] and "Ctrl+Z" in host.statuses[-1]
    # 一次撤销就回到原文（验收要求"可撤销"）
    assert w.document().isUndoAvailable()
    w.undo()
    assert w.toPlainText() == "x = 1\n"
    # 快照兜底：撤销历史丢了也能救回来
    snaps = list((root / "backups" / "format").glob("*.bak"))
    assert snaps and snaps[0].read_text(encoding="utf-8") == "x = 1\n"


def test_save_survives_missing_formatter(tmp_path, qtbot, monkeypatch):
    """开着开关但机器上没有格式化工具：保存照常完成，不弹错误。"""
    monkeypatch.setattr(cf, "formatter_for", lambda path, preferred="auto": None)
    w, root, target = _widget(qtbot, tmp_path)
    host = _Host(w, root, _Trunk({"编辑.保存格式化": "on"}))
    host._save_w(w)
    assert target.read_text(encoding="utf-8") == "x = 1\n"
    assert w.toPlainText() == "x = 1\n"


def test_save_format_failure_keeps_user_text(tmp_path, qtbot, monkeypatch):
    """格式化把代码弄成语法错误 → 拒绝采用，按原文落盘。"""
    _patch_formatter(monkeypatch, _fake_formatter(
        tmp_path, 'sys.stdout.write("def f(:\n")'))
    w, root, target = _widget(qtbot, tmp_path)
    host = _Host(w, root, _Trunk({"编辑.保存格式化": "on"}))
    host._save_w(w)
    assert target.read_text(encoding="utf-8") == "x = 1\n"
    assert w.toPlainText() == "x = 1\n"


def test_lsp_entries_degrade_without_server(tmp_path, qtbot, monkeypatch):
    """没装语言服务：每个入口都返回 None/空，只提示一句，不抛异常。"""
    import core.lsp_client as lsp
    monkeypatch.setattr(lsp, "client_for",
                        lambda root, path, autostart=True: None)
    monkeypatch.setattr(lsp, "available_for", lambda path: False)
    w, _root, _target = _widget(qtbot, tmp_path)
    assert w._lsp_client() is None
    assert w._lsp_in_service() is False
    assert w.lsp_goto_definition() is False
    assert w.lsp_find_references() == []
    assert w.lsp_hover() == ""
    assert w.lsp_rename_symbol() is False


def test_context_menu_gets_lsp_actions():
    """右键菜单：5 个语言服务动作 + 至少 1 个分隔符（不新增按钮预算）。"""
    widget = CodeEditWidget()
    menu = QMenu()
    widget._lsp_add_menu(menu)
    acts = menu.actions()
    seps = [a for a in acts if a.isSeparator()]
    real = [a for a in acts if not a.isSeparator()]
    assert len(real) == 5, "跳定义/引用/重命名/符号信息/格式化"
    assert seps, "语言服务项要和原有右键项分开"
    texts = [a.text() for a in real]
    assert any("定义" in t for t in texts) and any("格式化" in t for t in texts)


def test_lsp_format_document_uses_selection(tmp_path, qtbot, monkeypatch):
    """Ctrl+Alt+F：有选区就带上行范围，整篇替换一次撤销可退。"""
    _patch_formatter(monkeypatch, _fake_formatter(tmp_path))
    w, root, target = _widget(qtbot, tmp_path, text="x = 1\nprint(x)\n")
    cur = QTextCursor(w.document())
    cur.movePosition(QTextCursor.Start)
    cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
    w.setTextCursor(cur)
    res = w.lsp_format_document()
    assert res["ok"] and res["changed"]
    assert w.toPlainText() == "x=1\nprint(x)\n"
    w.undo()
    assert w.toPlainText() == "x = 1\nprint(x)\n"
    assert list((root / "backups" / "format").glob("*.bak"))
