# -*- coding: utf-8 -*-
"""MCP 信任管理测试（解决"MCP 启动每次都弹窗"）。"""

import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SERVERS = [
    {"name": "文件系统", "command": "npx -y @modelcontextprotocol/server-filesystem ."},
    {"name": "SQLite", "command": 'uvx --with "mcp<2" mcp-server-sqlite --db-path data/chats.db'},
]


class _FakeTrunk:
    confirm_cb = None

    def __init__(self, base):
        self.base = base
        self.config = {"mcp_servers": SERVERS}

    def _load_lazy(self, _n):
        return None


def _client(tmp_path):
    from modules.installed.mcp_client import MCPClient
    c = MCPClient.__new__(MCPClient)
    c.trunk = _FakeTrunk(str(tmp_path))
    c.servers = SERVERS
    c._session_trusted = set()
    c.conn_errors = []
    return c


def _trust_file(tmp_path):
    return os.path.join(str(tmp_path), "data", "plugin_data",
                        "mcp_client", "mcp_trust.json")


# ---------------- trust_report ----------------
def test_trust_report_lists_all_servers(tmp_path):
    rep = _client(tmp_path).trust_report()
    assert len(rep["servers"]) == len(SERVERS)
    for r in rep["servers"]:
        assert r["hash"]
        assert r["trusted"] is False
        assert r["reason"]


def test_trust_report_skips_servers_without_command(tmp_path):
    c = _client(tmp_path)
    c.servers = SERVERS + [{"name": "本地工具", "command": None}]
    names = [r["name"] for r in c.trust_report()["servers"]]
    assert "本地工具" not in names


# ---------------- 一键全部信任 ----------------
def test_trust_all_writes_file(tmp_path):
    c = _client(tmp_path)
    r = c.trust_all_servers()
    assert r["ok"] is True
    assert r["已信任"] == len(SERVERS)
    assert os.path.isfile(_trust_file(tmp_path))
    data = json.load(open(_trust_file(tmp_path), encoding="utf-8"))
    assert len(data["trusted_commands"]) == len(SERVERS)


def test_trust_all_makes_report_trusted(tmp_path):
    c = _client(tmp_path)
    c.trust_all_servers()
    rep = c.trust_report()
    assert all(r["trusted"] for r in rep["servers"])


def test_trust_all_is_idempotent(tmp_path):
    c = _client(tmp_path)
    c.trust_all_servers()
    r2 = c.trust_all_servers()
    assert r2["ok"] is True
    data = json.load(open(_trust_file(tmp_path), encoding="utf-8"))
    assert len(data["trusted_commands"]) == len(SERVERS)   # 没有重复


def test_trust_all_returns_error_when_no_servers(tmp_path):
    c = _client(tmp_path)
    c.servers = []
    r = c.trust_all_servers()
    assert r["ok"] is False
    assert "没有可信任" in r["原因"]


def test_trust_all_gives_clear_error_on_unwritable_path(tmp_path):
    """写盘失败必须报错，不能假装成功 —— 否则用户下次还会被弹窗。"""
    c = _client(tmp_path)
    # 让 data 变成一个文件，导致无法创建目录
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(os.path.join(str(tmp_path), "data"), "w") as f:
        f.write("x")
    r = c.trust_all_servers()
    assert r["ok"] is False
    assert "失败" in r["原因"]


# ---------------- 撤销 ----------------
def test_revoke_all_clears_file(tmp_path):
    c = _client(tmp_path)
    c.trust_all_servers()
    assert os.path.isfile(_trust_file(tmp_path))
    r = c.revoke_trust(None)
    assert r["ok"] is True
    assert not os.path.isfile(_trust_file(tmp_path))
    assert not any(x["trusted"] for x in c.trust_report()["servers"])


def test_revoke_single_server(tmp_path):
    c = _client(tmp_path)
    c.trust_all_servers()
    r = c.revoke_trust("SQLite")
    assert r["ok"] is True
    rep = {x["name"]: x["trusted"] for x in c.trust_report()["servers"]}
    assert rep["SQLite"] is False
    assert rep["文件系统"] is True        # 其他不受影响


def test_revoke_unknown_server(tmp_path):
    c = _client(tmp_path)
    r = c.revoke_trust("不存在")
    assert r["ok"] is False


# ---------------- 哈希稳定性 ----------------
def test_command_hash_is_stable_across_calls(tmp_path):
    """同一命令必须得到同一哈希，否则"永久允许"永远不生效。"""
    c = _client(tmp_path)
    h1 = [r["hash"] for r in c.trust_report()["servers"]]
    h2 = [r["hash"] for r in c.trust_report()["servers"]]
    assert h1 == h2


def test_command_change_produces_new_hash(tmp_path):
    """命令被改动必须换哈希 —— 这是防止命令被替换的安全设计。"""
    c = _client(tmp_path)
    before = c.trust_report()["servers"][0]["hash"]
    c.servers = [{"name": "文件系统",
                  "command": "npx -y @modelcontextprotocol/server-filesystem /etc"}]
    after = c.trust_report()["servers"][0]["hash"]
    assert before != after


# ---------------- 设置界面 ----------------
def test_trust_panel_has_actions():
    pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from gui.mcp_trust_view import MCPTrustPanel
    for name in ("refresh", "trust_all", "revoke_all", "_load_in_background"):
        assert hasattr(MCPTrustPanel, name), "缺少 %s" % name


def test_trust_panel_does_not_load_client_on_init():
    """⚠️ 关键回归：构造信任页**不能**同步加载 mcp_client。

    历史 bug：构造期调 refresh() -> _load_lazy("mcp_client")
    -> 同步连 4 个服务器 -> 界面卡 120 秒。
    """
    pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841

    calls = []

    class _FakeTrunk2:
        base = "."
        config = {"mcp_servers": []}
        modules = {}

        def _load_lazy(self, name):
            calls.append(name)
            return None

    from gui.mcp_trust_view import MCPTrustPanel
    MCPTrustPanel(_FakeTrunk2())
    assert calls == [], "构造信任页时不应加载任何模块，实际加载了 %s" % calls


def test_trust_all_works_without_loading_client(tmp_path):
    """即使 mcp_client 没加载，也能写入信任（不去连服务器）。"""
    from gui.mcp_trust_view import _trust_all_from_config
    from core.mcp_trust import load_trusted

    class _FakeTrunk2:
        base = str(tmp_path)
        config = {"mcp_servers": SERVERS}

    r = _trust_all_from_config(_FakeTrunk2())
    assert r["ok"] is True
    assert r["已信任"] == len(SERVERS)
    assert len(load_trusted(str(tmp_path))) == len(SERVERS)


# ---------------- 覆盖率补充：信任面板 ----------------
def test_panel_rows_from_config_without_client():
    """client.servers 为空时从配置读，表格仍能显示。"""
    import pytest as _pytest
    _pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from gui.mcp_trust_view import _rows_from_config

    class T:
        base = str(__import__("tempfile").mkdtemp())
        config = {"mcp_servers": SERVERS}

    rows = _rows_from_config(T())
    assert len(rows) == len(SERVERS)
    assert all("hash" in r for r in rows)


def test_panel_trust_all_without_client(tmp_path):
    import pytest as _pytest
    _pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from gui.mcp_trust_view import _trust_all_from_config
    from core.mcp_trust import load_trusted

    class T:
        base = str(tmp_path)
        config = {"mcp_servers": SERVERS}

    r = _trust_all_from_config(T())
    assert r["ok"] is True
    assert len(load_trusted(str(tmp_path))) == len(SERVERS)


def test_panel_trust_all_reports_when_no_servers(tmp_path):
    from gui.mcp_trust_view import _trust_all_from_config

    class T:
        base = str(tmp_path)
        config = {"mcp_servers": []}

    r = _trust_all_from_config(T())
    assert r["ok"] is False
    assert "没有" in r["原因"]


# ---------------- 覆盖率补充：面板操作（不触发真实连接） ----------------

def test_panel_rows_from_config_marks_trusted(tmp_path):
    from gui.mcp_trust_view import _rows_from_config
    from core.mcp_trust import save_trusted
    from core.mcp_sandbox import startup_manifest

    class T:
        base = str(tmp_path)
        config = {"mcp_servers": SERVERS}

    hashes = {startup_manifest(dict(s, cwd=None))["command_sha256"]
              for s in SERVERS}
    save_trusted(str(tmp_path), hashes)
    rows = _rows_from_config(T())
    assert rows and all(r["trusted"] for r in rows)


def test_panel_empty_config_returns_no_rows(tmp_path):
    from gui.mcp_trust_view import _rows_from_config

    class T:
        base = str(tmp_path)
        config = {}

    assert _rows_from_config(T()) == []


def test_panel_skips_servers_without_command(tmp_path):
    from gui.mcp_trust_view import _rows_from_config

    class T:
        base = str(tmp_path)
        config = {"mcp_servers": [{"name": "本地工具", "command": None}] + SERVERS}

    rows = _rows_from_config(T())
    assert all(r["name"] != "本地工具" for r in rows)
