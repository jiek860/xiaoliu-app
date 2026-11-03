# -*- coding: utf-8 -*-
"""工作区（"代码写到哪个文件夹"）：选目录 / 记住上次 / 切换时同步面板。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui import workbench_workspace as ww  # noqa: E402


class _FakeTrunk:
    def __init__(self, base=BASE, config=None):
        self.base = base
        self.config = {} if config is None else config
        self.saved = 0

    def save_config(self):
        self.saved += 1


class _Label:
    def __init__(self, text=""):
        self.text = text
        self.tip = ""

    def setText(self, text):
        self.text = text

    def setToolTip(self, text):
        self.tip = text


class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        def _noop(*_a, **_k):
            return _Stub()
        return _noop


class _Timeline:
    def __init__(self):
        self.lines = []

    def appendPlainText(self, text):
        self.lines.append(text)


class _Dock:
    def __init__(self):
        self.queue = object()
        self.service = object()
        self.current_job_id = "job-1"
        self.timeline = _Timeline()
        self._running = False


class _View:
    def __init__(self, root):
        self.root = root
        self.cleared = 0
        self.refreshed = 0

    def _clear(self):
        self.cleared += 1

    def refresh(self):
        self.refreshed += 1


class _Host:
    def __init__(self, root):
        self.search_view = _View(root)
        self.scm_view = _View(root)


class _Editor:
    def __init__(self, root):
        self.root = root
        self.fs_model = _Stub()
        self.tree = _Stub()
        self.bottom = _Stub(root=root)
        self.git_marks = 0

    def refresh_git_marks(self):
        self.git_marks += 1


class _FakeWB:
    def __init__(self, root, trunk=None):
        self.root = root
        self.trunk = trunk or _FakeTrunk()
        self.root_label = _Label(root)
        self.branch_label = _Label()
        self.status_label = _Label()
        self._editor = _Editor(root)
        self.sidebar_stack = _Host(root)
        self.ai_dock = _Dock()


def _mkdir(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return str(path)


# ---------------------------------------------------------------- 记忆
def test_program_root_is_trunk_base(tmp_path):
    trunk = _FakeTrunk(base=_mkdir(tmp_path, "prog"))
    assert ww.program_root(trunk) == os.path.abspath(trunk.base)


def test_remembered_root_reads_config(tmp_path):
    target = _mkdir(tmp_path, "proj")
    trunk = _FakeTrunk(config={ww.CFG_KEY: target})
    assert ww.remembered_root(trunk) == os.path.abspath(target)


def test_remembered_root_ignores_missing_dir(tmp_path):
    trunk = _FakeTrunk(config={ww.CFG_KEY: str(tmp_path / "gone")})
    assert ww.remembered_root(trunk) == ""


def test_remembered_root_survives_bad_config():
    trunk = _FakeTrunk(config={"workbench_root": None})
    assert ww.remembered_root(trunk) == ""
    # config 不是 dict 时也不能炸
    assert ww.remembered_root(_FakeTrunk(config=["x"])) == ""


def test_resolve_root_prefers_remembered(tmp_path):
    prog = _mkdir(tmp_path, "prog")
    proj = _mkdir(tmp_path, "proj")
    trunk = _FakeTrunk(base=prog, config={ww.CFG_KEY: proj})
    assert ww.resolve_root(trunk) == os.path.abspath(proj)
    assert ww.resolve_root(_FakeTrunk(base=prog)) == os.path.abspath(prog)


def test_remember_root_writes_config_and_saves(tmp_path):
    target = _mkdir(tmp_path, "proj")
    trunk = _FakeTrunk()
    assert ww.remember_root(trunk, target) == os.path.abspath(target)
    assert trunk.config[ww.CFG_KEY] == os.path.abspath(target)
    assert trunk.saved == 1
    # 下次打开工作台直接用它
    assert ww.resolve_root(trunk) == os.path.abspath(target)


def test_root_hint_only_for_program_dir(tmp_path):
    prog = _mkdir(tmp_path, "prog")
    proj = _mkdir(tmp_path, "proj")
    trunk = _FakeTrunk(base=prog)
    assert "程序目录" in ww.root_hint(trunk, prog)
    assert "打开文件夹" in ww.root_hint(trunk, prog)
    assert ww.root_hint(trunk, proj) == ""


def test_show_root_hint_writes_status_and_timeline(tmp_path):
    prog = _mkdir(tmp_path, "prog")
    wb = _FakeWB(prog, _FakeTrunk(base=prog))
    text = ww.show_root_hint(wb)
    assert "程序目录" in wb.status_label.text
    assert text in wb.ai_dock.timeline.lines
    # 选过别的目录后不再提示
    wb.root = _mkdir(tmp_path, "proj")
    assert ww.show_root_hint(wb) == ""


# ---------------------------------------------------------------- 切换
def test_apply_root_rejects_missing_dir():
    wb = _FakeWB(BASE)
    result = ww.apply_root(wb, os.path.join(BASE, "不存在的目录"))
    assert result["ok"] is False
    assert wb.root == BASE


def test_apply_root_updates_every_panel(tmp_path):
    old = _mkdir(tmp_path, "old")
    new = _mkdir(tmp_path, "new")
    wb = _FakeWB(old)
    result = ww.apply_root(wb, new)
    assert result == {"ok": True, "root": os.path.abspath(new),
                      "previous": old}
    assert wb.root == os.path.abspath(new)
    assert wb.root_label.text == "new"
    assert wb.root_label.tip == os.path.abspath(new)
    # 文件树跟着换根
    assert wb._editor.root == os.path.abspath(new)
    # 搜索 / Git 面板换根并刷新
    assert wb.sidebar_stack.search_view.root == os.path.abspath(new)
    assert wb.sidebar_stack.scm_view.root == os.path.abspath(new)
    assert wb.sidebar_stack.search_view.cleared == 1
    assert wb.sidebar_stack.scm_view.refreshed == 1
    # AI 队列/服务必须丢旧引用，否则下一次"开始"还写旧目录
    assert wb.ai_dock.queue is None
    assert wb.ai_dock.service is None
    assert wb.ai_dock.current_job_id == ""
    assert any("工作区已切到" in x for x in wb.ai_dock.timeline.lines)


def test_apply_root_keeps_service_when_job_running(tmp_path):
    """任务还在跑时换目录：不能丢 service（审批应答要用），只提示。"""
    old = _mkdir(tmp_path, "old")
    new = _mkdir(tmp_path, "new")
    wb = _FakeWB(old)
    wb.ai_dock._running = True
    ww.apply_root(wb, new)
    assert wb.ai_dock.service is not None
    assert wb.ai_dock.queue is not None
    assert any("仍在旧工作区" in x for x in wb.ai_dock.timeline.lines)
    assert wb.root == os.path.abspath(new)


def test_apply_root_remembers_choice(tmp_path):
    new = _mkdir(tmp_path, "new")
    wb = _FakeWB(BASE)
    ww.apply_root(wb, new)
    assert wb.trunk.config[ww.CFG_KEY] == os.path.abspath(new)
    assert wb.trunk.saved == 1


def test_apply_root_can_skip_remembering(tmp_path):
    new = _mkdir(tmp_path, "new")
    wb = _FakeWB(BASE)
    ww.apply_root(wb, new, remember=False)
    assert ww.CFG_KEY not in wb.trunk.config
    assert wb.trunk.saved == 0


def test_open_folder_picker_cancel_keeps_root(monkeypatch):
    wb = _FakeWB(BASE)
    monkeypatch.setattr(ww, "choose_folder", lambda *_a, **_k: "")
    result = ww.open_folder_picker(wb)
    assert result == {"ok": False, "cancelled": True}
    assert wb.root == BASE


def test_open_folder_picker_switches_and_echoes(tmp_path, monkeypatch):
    new = _mkdir(tmp_path, "new")
    wb = _FakeWB(BASE)
    monkeypatch.setattr(ww, "choose_folder", lambda *_a, **_k: new)
    result = ww.open_folder_picker(wb)
    assert result["ok"] is True
    assert wb.root == os.path.abspath(new)
    assert "new" in wb.status_label.text


def test_open_folder_picker_reports_failure(tmp_path, monkeypatch):
    """目录不可用时要明说失败（否则用户以为"改不了"）。"""
    wb = _FakeWB(BASE)
    monkeypatch.setattr(ww, "choose_folder",
                        lambda *_a, **_k: str(tmp_path / "没有这个目录"))
    result = ww.open_folder_picker(wb)
    assert result["ok"] is False
    assert "失败" in wb.status_label.text
    assert wb.root == BASE


def test_open_folder_picker_cancel_has_feedback(tmp_path, monkeypatch):
    wb = _FakeWB(BASE)
    monkeypatch.setattr(ww, "choose_folder", lambda *_a, **_k: "")
    ww.open_folder_picker(wb)
    assert "已取消" in wb.status_label.text


def test_type_folder_path_returns_abs_dir(tmp_path, monkeypatch):
    """目录框起不来时的兜底：手输路径也能切换。"""
    from gui import folder_picker as fp
    target = _mkdir(tmp_path, "typed")
    monkeypatch.setattr(fp, "ask_text", lambda *_a, **_k: target)
    assert ww.type_folder_path(None, "") == os.path.abspath(target)


def test_type_folder_path_rejects_bad_input(tmp_path, monkeypatch):
    from gui import folder_picker as fp
    monkeypatch.setattr(fp, "ask_text", lambda *_a, **_k: "")
    assert ww.type_folder_path(None, "") == ""
    monkeypatch.setattr(fp, "ask_text", lambda *_a, **_k: "/没有/这个目录")
    assert ww.type_folder_path(None, "") == ""


def test_open_folder_picker_same_dir_is_noop(tmp_path, monkeypatch):
    old = _mkdir(tmp_path, "old")
    wb = _FakeWB(old)
    monkeypatch.setattr(ww, "choose_folder", lambda *_a, **_k: old)
    result = ww.open_folder_picker(wb)
    assert result == {"ok": True, "root": old, "unchanged": True}
    assert wb.trunk.saved == 0
