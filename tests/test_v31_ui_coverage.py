# -*- coding: utf-8 -*-
"""v3.1 UI 与服务器覆盖测试。"""
import json
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402
_APP = QApplication.instance() or QApplication([])


class _T:
    def __init__(self, base):
        self.base = str(base)
        self.config = {"mcp_servers": []}
        self.modules = {}
    def save_config(self):
        return None


def _app():
    return _APP


def _quiet_boxes(monkeypatch):
    from PyQt5.QtWidgets import QMessageBox, QMenu, QInputDialog
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMenu, "exec_", lambda *a, **k: None)


def test_plan_confirm_dialog_actions():
    from gui.plan_confirm_dialog import PlanConfirmDialog
    d = PlanConfirmDialog("plan", "goal")
    assert not d.is_approved()
    d.editor.setPlainText("edited")
    d._on_approve()
    assert d.is_approved() and d.get_edited_plan() == "edited"
    d.close()


def test_skills_dialog_all_actions(monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QFileDialog, QInputDialog, QListWidgetItem, QMessageBox, QMenu
    from gui.skills_dialog import SkillsDialog
    from core.skill_registry import SkillRegistry

    _app(); _quiet_boxes(monkeypatch)
    cap = tmp_path / "data" / "plugin_data" / "skill_capture" / "skills"
    cap.mkdir(parents=True)
    (cap / "demo.md").write_text("demo", encoding="utf-8")
    t = _T(tmp_path)
    d = SkillsDialog(t)
    try:
        assert d.list.count() >= 1
        # 勾选/取消覆盖 _on_item_changed
        item = d.list.item(0)
        item.setCheckState(2)
        item.setCheckState(0)
        # 刷新 + 更多菜单
        d._refresh()
        d._show_actions()
        # 导出
        out = tmp_path / "demo.x6skill"
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(out), "")))
        d.list.setCurrentItem(d.list.item(0))
        d._export_skill()
        assert out.exists()
        # 导入
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(out), "")))
        d._import_skill()
        # 确认/拒绝：用假 skill_capture
        class SC:
            def confirm_skill(self, name): return {"已确认": name}
            def reject_skill(self, name): return {"已拒绝": name}
        t.modules["skill_capture"] = SC()
        d._confirm_skill()
        d._reject_skill()
        # 市场安装
        from core import skills_market
        monkeypatch.setattr(skills_market, "fetch_remote_catalog",
                            lambda: {"ok": True, "skills": [
                                {"name": "demo", "title": "Demo", "desc": "d",
                                 "local_path": str(out), "sha256": "x"}]})
        monkeypatch.setattr(skills_market, "download_skill",
                            lambda name, target_dir=None: {"ok": True, "zip_path": str(out)})
        monkeypatch.setattr(QInputDialog, "getItem",
                            staticmethod(lambda *a, **k: ("Demo — d", True)))
        d._install_market_skill()
        # 删除
        d.list.setCurrentItem(d.list.item(0))
        d._delete_selected()
    finally:
        d.close()


def test_ui_actions_upload_image_and_web_console(monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QTextEdit, QFileDialog, QMessageBox
    from gui.mixins.ui_actions_mixin import UIActionsMixin

    _app(); _quiet_boxes(monkeypatch)
    class Chat:
        def __init__(self): self.lines = []
        def append(self, s): self.lines.append(s)
    class MM:
        def describe_image(self, path): return {"描述": "图片内容"}
    class _Trunk:
        base = str(tmp_path)
        def __init__(self):
            self.modules = {"multimodal": MM()}
            self._server = None
        def _load_lazy(self, name):
            class Server:
                def start(self): return {"ok": True, "url": "http://127.0.0.1/x"}
            return Server()
    class W(UIActionsMixin):
        base = str(tmp_path)
        def __init__(self):
            self.trunk = _Trunk(); self.chat = Chat(); self.input = QTextEdit()
    w = W()
    img = tmp_path / "a.png"; img.write_bytes(b"x")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(img), "")))
    w.upload_image()
    assert "图片内容" in w.input.toPlainText()
    w.open_web_console()


def test_api_server_more_contract(monkeypatch):
    import socket, urllib.error, urllib.request
    from modules.installed.api_server import ApiServer

    class Tasks:
        def create(self, goal): return {"id": "t1", "status": "pending"}
        def start(self, tid): return {"ok": True}
        def get_task(self, tid): return {"id": tid, "status": "done"} if tid == "t1" else None
        def list_tasks(self): return []
    class T:
        def get_task_runtime(self): return Tasks()
        def reply(self, msg): return "reply:" + msg
    monkeypatch.setattr(ApiServer, "_run_websocket", lambda self: None)
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    s = ApiServer(T(), port=port); info = s.start(); token = s.auth_token
    try:
        def req(path, data=None):
            r = urllib.request.Request(
                "http://127.0.0.1:%d%s" % (port, path), data=data,
                headers={"Authorization": "Bearer " + token,
                         "Content-Type": "application/json"},
                method="POST" if data is not None else "GET")
            with urllib.request.urlopen(r, timeout=3) as x: return x.status, x.read()
        assert req("/v1/health")[0] == 200
        assert req("/?token=" + token)[0] == 200
        assert req("/tasks?token=" + token)[0] == 200
        assert req("/v1/chat", b'{"message":"hi"}')[1].find(b"reply:hi") >= 0
        assert req("/v1/tasks", b'{"goal":"x"}')[1].find(b"t1") >= 0
        assert req("/v1/tasks/t1")[0] == 200
        for path, data in (("/v1/tasks", b'{}'), ("/nope", None), ("/v1/chat", b'{}')):
            try:
                req(path, data)
            except urllib.error.HTTPError as e:
                assert e.code in (400, 404, 200)
        # 无 token
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=2)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        s.stop()


def test_mcp_dialog_helpers(monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from gui.mcp_dialog import MCPDialog, PRESETS
    _app(); _quiet_boxes(monkeypatch)
    monkeypatch.setattr(MCPDialog, "_update_catalog_async", lambda self: None)
    monkeypatch.setattr(MCPDialog, "_load_client_async", lambda self: None)
    t = _T(".")
    d = MCPDialog(t)
    try:
        d._refresh_presets_list()
        d._on_transport_changed(1)
        d._on_transport_changed(0)
        assert d.preset_list.count() == len(PRESETS)
        d._report("测试", {"ok": True, "服务器数": 0, "工具数": 0})
    finally:
        d.close()
