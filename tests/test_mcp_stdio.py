# -*- coding: utf-8 -*-
"""MCP stdio 传输测试（离线、不依赖 npx / uvx / 网络）

用 tests/fake_mcp_server.py 这个最小的 stdio MCP 服务器当对端，
覆盖握手、列工具、调工具、错误路径、进程死掉、命令不存在等情况。
"""
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.mcp_stdio import StdioMCPServer, _flatten_content  # noqa: E402

FAKE = os.path.join(BASE, "tests", "fake_mcp_server.py")


def _cmd(script, *args):
    """拼一条启动 python 脚本的命令行（Windows 会经 cmd.exe 执行）"""
    parts = ['"%s"' % sys.executable, '"%s"' % script]
    parts += list(args)
    return " ".join(parts)


@pytest.fixture
def server():
    s = StdioMCPServer("fake", _cmd(FAKE))
    ok = s.start()
    assert ok, "握手失败: %s" % s.diagnostics()
    yield s
    s.stop()


# ---------------------------------------------------------------- 正常路径

def test_handshake_ok(server):
    """initialize + notifications/initialized 走通"""
    assert server.alive()
    assert server.protocol_version == "2024-11-05"
    assert server.server_info.get("name") == "fake-mcp"


def test_list_tools(server):
    names = [t["name"] for t in server.tools]
    assert names == ["echo", "boom"], names
    for t in server.tools:
        assert t["_server"] == "fake"
        assert t["_transport"] == "stdio"
    assert server.tools[0]["inputSchema"]["required"] == ["text"]


def test_call_tool_echo(server):
    r = server.call_tool("echo", {"text": "你好"})
    assert r["ok"] is True
    assert "你好" in r["结果"], r


def test_call_tool_iserror_is_reported_as_failure(server):
    """服务端把 isError 放 result 里，不能当成成功"""
    r = server.call_tool("boom", {})
    assert r["ok"] is False
    assert "出错" in r["结果"]


def test_call_unknown_tool_returns_error(server):
    r = server.call_tool("not_a_tool", {})
    assert r["ok"] is False
    assert "未知工具" in str(r.get("错误", ""))


def test_ping_works(server):
    p = server.ping()
    assert p["ok"] is True
    assert p["工具数"] == 2


def test_non_json_banner_on_stdout_is_tolerated(server):
    """服务器往 stdout 打横幅是常事，不能因此失败"""
    assert server.alive()
    assert len(server.tools) == 2


def test_multiple_calls_reuse_one_process(server):
    """同一个进程反复调用，不应该每次都重启"""
    pid = server.proc.pid
    for i in range(5):
        r = server.call_tool("echo", {"text": "第%d次" % i})
        assert r["ok"] and ("第%d次" % i) in r["结果"]
    assert server.proc.pid == pid


# ---------------------------------------------------------------- 异常路径

def test_missing_command_fails_gracefully():
    s = StdioMCPServer("nope", "")
    assert s.start() is False
    assert "命令为空" in s.last_error
    assert not s.alive()


def test_bad_command_fails_with_diagnostics():
    """命令不存在时要给出可读原因，而不是卡住或抛异常"""
    s = StdioMCPServer("bad", "definitely-not-a-real-command-xyz")
    try:
        ok = s.start()
        assert ok is False
        d = s.diagnostics()
        assert d and d != "无", "应当给出诊断信息"
    finally:
        s.stop()


def test_process_death_wakes_pending_requests():
    """子进程中途死掉，等在途请求上的调用方不能被挂住"""
    s = StdioMCPServer("die", _cmd(FAKE))
    assert s.start()
    try:
        s.proc.kill()
        time.sleep(0.6)
        assert not s.alive()
        r = s.call_tool("echo", {"text": "x"})
        assert r["ok"] is False
        assert "退出" in str(r.get("错误", "")) or "未运行" in str(r.get("错误", ""))
    finally:
        s.stop()


def test_stop_is_idempotent():
    s = StdioMCPServer("fake", _cmd(FAKE))
    assert s.start()
    s.stop()
    s.stop()                    # 再来一次不该抛
    assert not s.alive()


def test_request_timeout_does_not_leak_pending():
    """超时的请求要能从待办表里摘掉，不能越积越多

    用一个"只读不回"的服务器来确定性地触发超时 ——
    把超时设得极短再指望服务器来不及回，是不可靠的。
    """
    s = StdioMCPServer("silent", _cmd(FAKE, "--silent"), timeout=1)
    assert s.start() is False, "只读不回的服务器不该握手成功"
    # 握手失败后进程会被停掉，这里手工起重来单独验超时
    s2 = StdioMCPServer("silent2", _cmd(FAKE, "--silent"), timeout=1)
    try:
        argv, use_shell = s2._popen_args()
        import subprocess
        s2.proc = subprocess.Popen(argv, shell=use_shell, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", bufsize=1)
        s2._alive = True
        import threading
        threading.Thread(target=s2._read_stdout, daemon=True).start()
        with pytest.raises(Exception):
            s2._request("tools/list", {}, timeout=0.3)
        assert len(s2._pending) == 0, "超时的请求没从待办表里摘掉"
    finally:
        s2.stop()


# ---------------------------------------------------------------- 辅助

def test_flatten_content():
    assert _flatten_content({"content": [{"type": "text", "text": "a"},
                                         {"type": "text", "text": "b"}]}) == "a\nb"
    assert "[image]" in _flatten_content({"content": [{"type": "image"}]})
    assert _flatten_content("裸字符串")
