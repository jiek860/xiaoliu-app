# -*- coding: utf-8 -*-
r"""MCP stdio 接入 mcp_client 的回归测试（离线，用假服务器）

守的坑：
  · stdio 服务器能真的起进程、握手、列工具、调工具
  · 服务端 isError 要当成失败
  · 停用 / 重连时子进程要被收掉，不能留孤儿
  · 同名条目会导致 self.stdio 槽位覆盖、前一个进程变孤儿
  · stop() 之后没有活着的连接
"""
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))

FAKE = os.path.join(BASE, "tests", "fake_mcp_server.py")
CMD = '"%s" "%s"' % (sys.executable, FAKE)


class _Shim:
    """假 trunk：只要 config / _log / save_config"""
    base = BASE

    def __init__(self, servers=None):
        self.config = {"mcp_servers": servers if servers is not None else []}
        self.saved = 0

    def _log(self, m):
        pass

    def save_config(self):
        self.saved += 1


def _client(servers=None):
    from modules.installed.mcp_client import MCPClient
    return MCPClient(_Shim(servers))


@pytest.fixture
def stdio_client():
    c = _client([{"name": "假MCP", "command": CMD, "enabled": True}])
    yield c
    c.stop()


def test_stdio_server_connects(stdio_client):
    assert "假MCP" in stdio_client.stdio
    assert [t["name"] for t in stdio_client.tools] == ["echo", "boom"]
    assert all(t["_transport"] == "stdio" for t in stdio_client.tools)
    assert stdio_client.conn_errors == []


def test_call_stdio_tool(stdio_client):
    r = stdio_client.call("echo", {"text": "你好"})
    assert r.get("ok") is True
    assert "你好" in r.get("结果", "")


def test_stdio_iserror_is_failure(stdio_client):
    r = stdio_client.call("boom", {})
    assert "错误" in r, r


def test_unknown_tool(stdio_client):
    r = stdio_client.call("nope", {})
    assert "工具不存在" in str(r.get("错误", ""))


def test_stats_reports_transport(stdio_client):
    st = stdio_client.stats()
    assert st["按传输"] == {"stdio": 1}
    assert st["stdio 进程数"] == 1


def test_disable_stops_process():
    c = _client([{"name": "假MCP", "command": CMD, "enabled": True}])
    assert c.stdio
    c.trunk.config["mcp_servers"] = [{"name": "假MCP", "command": CMD,
                                      "enabled": False}]
    r = c.reload_servers()
    assert c.stdio == {}, "停用后 stdio 连接应当被收掉"
    # 配置里还有条目、只是被停用了 —— 就该一个都不连，
    # 不能悄悄回退到那个内置的默认服务器
    assert c.servers == [], "全部停用后不该回退去连默认服务器"
    assert c.tools == []
    assert r["服务器数"] == 0


def test_empty_config_falls_back_to_default():
    """从来没配过服务器时，才用内置的默认地址兜底"""
    c = _client([])
    try:
        assert len(c.servers) == 1
        assert "3742" in c.servers[0].get("url", "")
    finally:
        c.stop()


def test_duplicate_names_do_not_orphan_processes():
    """两个同名 stdio 条目只应留一个进程

    原来 self.stdio 是按名字索引的，后一个会覆盖前一个的槽位，
    前一个子进程就再也没人管了（实测确实会留下孤儿）。
    """
    from core.mcp_stdio import live_count
    before = live_count()
    c = _client([{"name": "同名", "command": CMD, "enabled": True},
                 {"name": "同名", "command": CMD, "enabled": True}])
    try:
        assert len(c.servers) == 1, "同名条目应当去重"
        assert len(c.stdio) == 1
        assert live_count() == before + 1, "不该多出一个没人管的进程"
    finally:
        c.stop()


def test_stop_clears_everything():
    from core.mcp_stdio import live_count
    before = live_count()
    c = _client([{"name": "假MCP", "command": CMD, "enabled": True}])
    assert live_count() == before + 1
    r = c.stop()
    assert r["已收"] == 1
    time.sleep(0.3)
    assert live_count() == before, "stop() 之后不该还有活连接"
    assert c.stdio == {}


def test_bad_command_reports_diagnostic():
    """命令不存在时要把原因记进 conn_errors，而不是静默失败"""
    c = _client([{"name": "坏的", "command": "definitely-not-real-cmd-xyz",
                  "enabled": True}])
    try:
        assert c.tools == []
        assert c.conn_errors, "应当有失败诊断"
        assert "坏的" in c.conn_errors[0]
    finally:
        c.stop()


def test_mixed_http_and_stdio():
    """HTTP 连不上不能影响 stdio 那条"""
    c = _client([{"name": "连不上的HTTP", "url": "http://127.0.0.1:1", "enabled": True},
                 {"name": "假MCP", "command": CMD, "enabled": True}])
    try:
        assert [t["name"] for t in c.tools] == ["echo", "boom"]
        assert any("HTTP" in e for e in c.conn_errors)
        assert c.stats()["按传输"] == {"http": 1, "stdio": 1}
    finally:
        c.stop()


def test_add_stdio_server_persists_and_connects():
    c = _client([])
    try:
        r = c.add_stdio_server("新加的", CMD)
        assert r.get("ok")
        assert c.trunk.saved >= 1, "应当写盘"
        cfg = c.trunk.config["mcp_servers"]
        assert cfg and cfg[-1]["command"] == CMD
        assert "新加的" in c.stdio
    finally:
        c.stop()


def test_connect_landing_after_stop_is_cleaned_up():
    """stop() 之后才落地的连接要自己收掉（退出时的真实竞态）

    不能靠 sleep 去碰运气 —— 直接构造"已经 stop 过、又有一条连接落地"
    的状态，确定性地验那个守卫。
    """
    from core.mcp_stdio import live_count

    before = live_count()
    c = _client([])                      # 空配置，不连任何 stdio
    c.stop()                             # 置位 _stopped，模拟程序正在退出
    assert c._stopped is True
    c._connect_stdio({"name": "假X", "command": CMD, "transport": "stdio"})
    time.sleep(0.5)
    assert c.stdio == {}, "stop 之后落地的连接不该被登记"
    assert live_count() == before, "stop 之后落地的连接没被收掉，成了孤儿进程"


def test_reload_after_stop_works_again():
    """显式重连视为"又开始工作了"，守卫要复位"""
    c = _client([])
    c.stop()
    assert c._stopped is True
    c.trunk.config["mcp_servers"] = [{"name": "假MCP", "command": CMD,
                                      "enabled": True}]
    try:
        c.reload_servers()
        assert c._stopped is False
        assert "假MCP" in c.stdio, "重连之后应当能正常工作"
    finally:
        c.stop()
