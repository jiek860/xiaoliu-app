# -*- coding: utf-8 -*-
"""RAG and team management dialog construction tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {"workspace_id": "default"}


def test_rag_dialog_constructs_and_reports_stats(tmp_path, qapp):
    from gui.rag_dialog import RAGDialog
    d = RAGDialog(_Trunk(tmp_path))
    try:
        assert "来源" in d.stats.text()
        assert d._kb().stats()["chunks"] == 0
    finally:
        d.close()


def test_team_dialog_constructs_and_lists_owner(tmp_path, qapp):
    from gui.team_dialog import TeamDialog
    d = TeamDialog(_Trunk(tmp_path))
    try:
        assert d.table.rowCount() >= 1
        assert d.table.item(0, 2).text() == "owner"
    finally:
        d.close()


def test_cloud_provider_dialog_reports_capabilities(tmp_path, qapp):
    from gui.cloud_provider_dialog import CloudProviderDialog
    class T:
        base = str(tmp_path)
        config = {"cloud_provider": "openai", "cloud_model": "gpt-4o-mini",
                  "cloud_url": "https://api.openai.com/v1", "cloud_key": "k"}
        def save_config(self):
            self.saved = dict(self.config)
    t = T()
    d = CloudProviderDialog(None, t)
    try:
        assert d.values()["cloud_provider"] == "openai"
        d.provider.setCurrentIndex(d.provider.findData("anthropic"))
        assert d.values()["cloud_provider"] == "anthropic"
        assert "tools=" in d.capability.text()
    finally:
        d.close()


def test_cloud_provider_dialog_can_test_connection_in_place(tmp_path, qapp):
    """换完 Key 要能当场验证，而不是等聊天报 401 才发现填错。"""
    from gui.cloud_provider_dialog import CloudProviderDialog

    class T:
        base = str(tmp_path)
        config = {"cloud_provider": "", "cloud_model": "glm-4-flash",
                  "cloud_url": "", "cloud_key": "dd95.demo"}
        def save_config(self):
            self.saved = dict(self.config)

    d = CloudProviderDialog(None, T())
    try:
        assert hasattr(d, "test_status")
        d._test_cloud()          # 没填地址：要给提示，且不发请求
        assert "API 地址" in d.test_status.text()

        d._show_test_result({"ok": True, "status": 200,
                             "message": "云端连通，模型「glm-4-flash」可以正常回复。"})
        assert "✅" in d.test_status.text()

        d._show_test_result({"ok": False, "code": "http_401", "status": 401,
                             "message": "Key 不对或已过期，去服务商后台重新复制一份。"})
        assert "401" in d.test_status.text()
        assert "❌" in d.test_status.text()
    finally:
        d.close()


def test_usage_dialog_constructs(tmp_path, qapp):
    from gui.usage_dialog import UsageDialog
    d = UsageDialog(_Trunk(tmp_path))
    try:
        assert "最近 7 天" in d.summary.text()
    finally:
        d.close()


def test_panel_registry_contains_new_admin_entries():
    from gui.panel_registry import build_panel_commands
    class Owner:
        rag_dialog = lambda self: None
        team_dialog = lambda self: None
        usage_dialog = lambda self: None
    cmds = build_panel_commands(Owner())
    assert cmds["RAG管理"] and cmds["团队管理"] and cmds["用量成本"]
    assert cmds["插件市场"] is None
