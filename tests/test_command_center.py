# -*- coding: utf-8 -*-
"""命令中心 NL 接入（批次 44.4）：决策层 + GUI 执行层 + 撤销。

默认 shadow 时 `_run_nl` 必须返回 False（继续旧的文件名逻辑），
只有 `nl.intent_v2=on` 才真正执行；撤销只认 patch_engine 的备份清单。
"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit, QWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.nl.command import (latest_manifest, plan_command,  # noqa: E402
                             undo_last)
from core.nl.entities import build_index  # noqa: E402
from gui.ide_command_center import CommandCenterMixin  # noqa: E402


def _write(root, rel, text):
    path = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return path


def _project(tmp):
    _write(tmp, "core/agent_router.py",
           "def route_goal(goal):\n    return goal\n")
    _write(tmp, "core/chat/state.py",
           "def classify_intent(text):\n    return 'chat'\n")
    _write(tmp, "tests/test_agent_router.py", "def test_a():\n    assert 1\n")
    return build_index(str(tmp), rebuild=True)


class _Ctx:
    def __init__(self):
        self.rows = []

    def record_shadow(self, payload):
        self.rows.append(payload)
        return True


class _Trunk:
    def __init__(self, mode="shadow"):
        self.mode = mode
        self.ctx = _Ctx()

    def rule(self, name, default=None):
        return self.mode if name == "nl.intent_v2" else default


class _View:
    def __init__(self):
        self.query = QLineEdit()


class _Host(CommandCenterMixin, QWidget):
    def __init__(self, root, trunk, search_view=None):
        super().__init__()
        self.root = str(root)
        self.trunk = trunk
        self.command = QLineEdit()
        self.status_label = QLabel()
        self._editor = None
        self.search_view = search_view
        self.opened = ""
        self.goal = ""
        self.ai = 0
        self.searched = 0

    def _command_items(self):
        return []

    def open_path(self, path):
        self.opened = path
        return True

    def _show_ai(self):
        self.ai += 1

    def set_goal(self, text):
        self.goal = text

    def _show_search(self):
        self.searched += 1


# ── 决策层 ──
def test_plan_open_file(tmp_path):
    index = _project(tmp_path)
    out = plan_command("打开 core/agent_router.py", root=str(tmp_path),
                       index=index)
    assert out["kind"] == "nl"
    assert out["action"] == {"action": "open",
                             "path": "core/agent_router.py"}


def test_plan_run_test(tmp_path):
    index = _project(tmp_path)
    out = plan_command("跑 tests/test_agent_router.py", root=str(tmp_path),
                       index=index)
    assert out["action"]["action"] == "run_test"
    assert out["action"]["path"] == "tests/test_agent_router.py"


def test_plan_search(tmp_path):
    out = plan_command("搜索 route_goal", root=str(tmp_path))
    assert out["action"]["action"] == "search"
    assert "route_goal" in out["action"]["query"]


def test_plan_ai_intent(tmp_path):
    index = _project(tmp_path)
    out = plan_command("修复 core/agent_router.py 的报错",
                       root=str(tmp_path), index=index)
    assert out["action"]["action"] == "ai"
    assert out["action"]["intent"] == "fix_error"
    assert out["action"]["goal"].startswith("修复")


def test_plan_slash_undo(tmp_path):
    out = plan_command("/undo", root=str(tmp_path))
    assert out["action"]["action"] == "undo"


def test_casual_text_falls_back_to_file(tmp_path):
    out = plan_command("今天天气怎么样", root=str(tmp_path))
    assert out["kind"] == "file"


def test_reference_file_and_symbol(tmp_path):
    index = _project(tmp_path)
    file_out = plan_command("@core/agent_router.py", root=str(tmp_path),
                            index=index)
    assert file_out["action"]["action"] == "open"
    sym_out = plan_command("@classify_intent", root=str(tmp_path), index=index)
    assert sym_out["action"]["action"] == "ai"
    assert sym_out["action"]["intent"] == "explain"


def test_missing_slot_asks_instead_of_executing(tmp_path):
    out = plan_command("帮我改一下这个", root=str(tmp_path))
    assert out["kind"] == "clarify"
    assert out["question"]
    assert out["options"] == []


def test_context_current_file_fills_slot(tmp_path):
    index = _project(tmp_path)
    out = plan_command("修复这个", root=str(tmp_path), index=index,
                       context={"current_file": "core/agent_router.py"})
    assert out["kind"] == "nl" and out["action"]["action"] == "ai"


def test_ambiguous_symbol_offers_options(tmp_path):
    index = _project(tmp_path)
    out = plan_command("重构 classify_inten", root=str(tmp_path), index=index)
    assert out["kind"] == "clarify"
    assert "classify_intent" in out["options"]


def test_unknown_file_reports_not_found(tmp_path):
    _project(tmp_path)
    out = plan_command("打开 nope_file.py", root=str(tmp_path))
    assert out["kind"] == "not_found"
    assert "没找到" in out["message"]


# ── 撤销清单 ──
def _manifest(root, pid, text, *, created, backup=None):
    folder = os.path.join(str(root), "data", "patch_backups", pid)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "manifest.json")
    item = {"path": "core/target.py", "op": "update", "existed": True}
    if backup:
        item["backup"] = backup
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"root": str(root), "created_at": created,
                   "files": [item]}, fp)
    return path


def test_latest_manifest_picks_newest(tmp_path):
    old = _manifest(tmp_path, "p1", "old", created=1)
    new = _manifest(tmp_path, "p2", "new", created=2)
    assert latest_manifest(str(tmp_path)) == new
    assert old != new


def test_undo_dry_run_does_not_restore(tmp_path):
    target = _write(tmp_path, "core/target.py", "改过的内容\n")
    backup = os.path.join(str(tmp_path), "data", "target.py.bak")
    _write(tmp_path, "data/target.py.bak", "原始内容\n")
    _manifest(tmp_path, "p1", "", created=1, backup=backup)
    out = undo_last(str(tmp_path), dry_run=True)
    assert out["ok"] is True and out["restored"] == []
    with open(target, encoding="utf-8") as fp:
        assert fp.read() == "改过的内容\n"


def test_undo_restores_latest_backup(tmp_path):
    target = _write(tmp_path, "core/target.py", "改过的内容\n")
    backup = _write(tmp_path, "data/target.py.bak", "原始内容\n")
    _manifest(tmp_path, "p1", "", created=1, backup=backup)
    out = undo_last(str(tmp_path))
    assert out["ok"] is True and out["restored"] == ["core/target.py"]
    with open(target, encoding="utf-8") as fp:
        assert fp.read() == "原始内容\n"


def test_undo_without_manifest_is_safe(tmp_path):
    out = undo_last(str(tmp_path))
    assert out["ok"] is False and "没有可撤销" in out["error"]


# ── GUI 执行层（headless） ──
def test_shadow_mode_keeps_old_behavior(tmp_path):
    _project(tmp_path)
    trunk = _Trunk("shadow")
    host = _Host(tmp_path, trunk)
    assert host._run_nl("打开 core/agent_router.py") is False
    assert trunk.ctx.rows and trunk.ctx.rows[-1]["kind"] == "nl_intent"
    assert host.opened == ""


def test_off_mode_does_not_record_or_execute(tmp_path):
    _project(tmp_path)
    trunk = _Trunk("off")
    host = _Host(tmp_path, trunk)
    assert host._run_nl("打开 core/agent_router.py") is False
    assert trunk.ctx.rows == []


def test_on_mode_opens_file(tmp_path):
    _project(tmp_path)
    host = _Host(tmp_path, _Trunk("on"))
    assert host._run_nl("打开 core/agent_router.py") is True
    assert host.opened.replace("\\", "/").endswith("core/agent_router.py")
    assert "已打开" in host.status_label.text()
    assert host.command.text() == ""


def test_on_mode_sends_goal_to_ai(tmp_path):
    _project(tmp_path)
    host = _Host(tmp_path, _Trunk("on"))
    host._run_nl("修复 core/agent_router.py 的报错")
    assert host.ai == 1
    assert host.goal.startswith("修复")


def test_on_mode_prefills_search_query(tmp_path):
    view = _View()
    host = _Host(tmp_path, _Trunk("on"), search_view=view)
    assert host._run_nl("搜索 route_goal") is True
    assert host.searched == 1
    assert "route_goal" in view.query.text()


def test_on_mode_clarify_only_sets_status(tmp_path):
    host = _Host(tmp_path, _Trunk("on"))
    assert host._run_nl("帮我改一下这个") is True
    assert "哪个文件或符号" in host.status_label.text()
    assert host.opened == "" and host.ai == 0


def test_on_mode_undo_restores_and_reports(tmp_path):
    target = _write(tmp_path, "core/target.py", "改过的内容\n")
    backup = _write(tmp_path, "data/target.py.bak", "原始内容\n")
    _manifest(tmp_path, "p1", "", created=1, backup=backup)
    host = _Host(tmp_path, _Trunk("on"))
    assert host._run_nl("撤销刚才的修改") is True
    assert "已撤销 1 个文件" in host.status_label.text()
    with open(target, encoding="utf-8") as fp:
        assert fp.read() == "原始内容\n"
