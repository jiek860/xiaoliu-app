# -*- coding: utf-8 -*-
"""内嵌本地工具服务（modules/installed/mcp_server.py）的回归测试

测的是「程序里自带一个能连本地工具的服务器」这件事：
起服务、按 mcp_client 期望的约定打接口、错误路径、停服务、以及
mcp_client 真的能连上它。

历史上这套东西是半成品，从没真正可用过：
  · /tools 返回 {"工具": [...]} 字典，客户端要的是列表 -> 永远 0 个工具
  · 没有 /call，客户端 POST 过去只能收到 501
  · 默认端口 8765 和 mobile_remote 撞车
  · start_http() 全项目没有调用点，服务从来没起来过
这里把上面每一条都钉住。
"""
import json
import os
import sys
import unittest.mock as mock
import urllib.error
import urllib.request

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))


@pytest.fixture(scope="module")
def trunk():
    """真 Trunk，但屏蔽后台服务（否则它 3 秒后会自己去连一遍 MCP，干扰观测）"""
    from core.trunk import Trunk
    with mock.patch.object(Trunk, "_start_background", lambda self: None), \
         mock.patch.object(Trunk, "_warmup", lambda self: None), \
         mock.patch.object(Trunk, "_auto_unload_loop", lambda self: None), \
         mock.patch.object(Trunk, "_warmup_ollama", lambda self: None):
        yield Trunk()


@pytest.fixture(scope="module")
def server(trunk):
    """起一个本地工具服务，用系统分配的端口（port=0）避免和真实服务撞"""
    s = trunk._load_lazy("mcp_server")
    r = s.start_http(port=0)
    assert "地址" in r, "服务没起来: %s" % r
    assert s.http_port > 0, "应当记录实际绑定的端口"
    yield s
    s.stop_http()


def _url(server, path):
    return "http://127.0.0.1:%d%s" % (server.http_port, path)


def _get(server, path):
    req = urllib.request.Request(_url(server, path))
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post(server, path, obj=None, raw=None):
    data = raw if raw is not None else json.dumps(obj or {}).encode("utf-8")
    req = urllib.request.Request(_url(server, path), data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


# ---------------------------------------------------------------- 正常路径

def test_start_is_idempotent(server):
    r = server.start_http(port=0)
    assert "已在运行" in r.get("状态", ""), r


def test_tools_endpoint_returns_a_list(server):
    """核心回归：必须是**列表**，不是 {"工具": [...]} 字典

    客户端是 `if isinstance(data, list)` 判断的，返回字典就永远 0 个工具。
    """
    code, data = _get(server, "/tools")
    assert code == 200
    assert isinstance(data, list), "返回了 %s，客户端要的是列表" % type(data).__name__
    assert data, "工具列表不该为空"


def test_tool_entries_have_expected_fields(server):
    _code, data = _get(server, "/tools")
    for t in data:
        assert t.get("name"), t
        assert "description" in t
        assert isinstance(t.get("inputSchema"), dict), t
    names = [t["name"] for t in data]
    for expect in ("chat", "search", "run_code", "backup"):
        assert expect in names, "缺少内置工具 %s（实际 %s）" % (expect, names)


def test_schema_declares_required_args(server):
    _code, data = _get(server, "/tools")
    by = {t["name"]: t for t in data}
    assert by["chat"]["inputSchema"].get("required") == ["message"]
    assert by["search"]["inputSchema"].get("required") == ["query"]
    assert by["run_code"]["inputSchema"].get("required") == ["code"]


def test_root_is_health_check(server):
    code, data = _get(server, "/")
    assert code == 200
    assert data.get("ok") is True
    assert data.get("工具数") == len(data.get("工具", []))


def test_call_endpoint_invokes_tool(server, trunk):
    """加一个只读工具再调它，验证 /call 这条链路真的到得了 trunk.call"""
    trunk.call("mcp_server", "add_tool", "只读统计", "向量库统计", "vector_store.run")
    try:
        code, data = _post(server, "/call", {"tool": "只读统计", "args": {}})
        assert code == 200
        assert data.get("ok") is True, data
        assert data.get("工具") == "只读统计"
        assert data.get("结果") is not None
    finally:
        trunk.call("mcp_server", "remove_tool", "只读统计")


def test_call_accepts_arguments_field(server, trunk):
    """payload 里写 arguments 也认（MCP 原生叫法）"""
    trunk.call("mcp_server", "add_tool", "回显", "回显", "vector_store.run")
    try:
        code, data = _post(server, "/call", {"name": "回显", "arguments": {}})
        assert code == 200 and data.get("ok") is True, data
    finally:
        trunk.call("mcp_server", "remove_tool", "回显")


# ---------------------------------------------------------------- 错误路径

def test_unknown_get_path_404(server):
    code, _data = _get(server, "/nope")
    assert code == 404


def test_unknown_post_path_404(server):
    code, _data = _post(server, "/nope", {})
    assert code == 404


def test_bad_json_body_400(server):
    code, data = _post(server, "/call", raw=b"{not json")
    assert code == 400
    assert "JSON" in str(data.get("错误", ""))


def test_unknown_tool_reports_error(server):
    code, data = _post(server, "/call", {"tool": "肯定不存在", "args": {}})
    assert code == 200
    assert data.get("ok") is False
    assert "工具不存在" in str(data.get("错误", ""))


def test_tool_pointing_at_missing_module(server, trunk):
    """工具指向不存在的模块时，错误要能传回客户端，而不是静默变成"成功"

    注意 trunk.call 自身是优雅降级的（返回 {'ok': False, ...} 而不是抛异常），
    所以这里断言的是内层 ok 为 False、错误信息能透出来。
    """
    trunk.call("mcp_server", "add_tool", "坏的", "指向不存在的模块", "no_such_mod.run")
    try:
        code, data = _post(server, "/call", {"tool": "坏的", "args": {}})
        assert code == 200
        inner = data.get("结果") or {}
        assert inner.get("ok") is False, data
        assert ("错误" in json.dumps(inner, ensure_ascii=False)
                or "error" in json.dumps(inner, ensure_ascii=False)), inner
    finally:
        trunk.call("mcp_server", "remove_tool", "坏的")


# ---------------------------------------------------------------- 客户端接入

def test_mcp_client_connects_to_local_server(server, trunk):
    """mcp_client 按 MCP 的 HTTP 约定连本地服务，应当拉到工具"""
    from modules.installed.mcp_client import MCPClient
    orig = list(trunk.config.get("mcp_servers", []) or [])
    trunk.config["mcp_servers"] = [
        {"name": "本地工具", "url": "http://127.0.0.1:%d" % server.http_port,
         "enabled": True}]
    try:
        c = MCPClient(trunk)
        names = [t.get("name") for t in c.tools]
        assert c.conn_errors == [], c.conn_errors
        for expect in ("chat", "search", "run_code", "backup"):
            assert expect in names, "%s 没被拉到（实际 %s）" % (expect, names)
        assert all(t.get("_transport") == "http" for t in c.tools)
    finally:
        trunk.config["mcp_servers"] = orig


def test_test_server_succeeds_against_local(server):
    """面板上的「测试选中」用的就是 test_server()"""
    r = server.trunk.call("mcp_client", "test_server",
                          "http://127.0.0.1:%d" % server.http_port)
    assert r.get("ok") is True, r


def test_stop_http_makes_it_unreachable(trunk):
    """停掉之后应当连不上（这条以前没验证过，服务其实一直没起来）"""
    s = trunk._load_lazy("mcp_server")
    s.stop_http()                     # 先把 fixture 起的那个停掉
    r = s.start_http(port=0)
    assert "地址" in r, r
    port = s.http_port
    assert s.stop_http().get("状态") == "已停止"
    with pytest.raises(Exception):
        urllib.request.urlopen("http://127.0.0.1:%d/tools" % port, timeout=3)
    s.stop_http()          # 幂等
