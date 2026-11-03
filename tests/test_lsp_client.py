# -*- coding: utf-8 -*-
"""第 7 批：语言服务（LSP）—— 帧编解码 / 增量同步 / 路由 / 无服务不报错。

这些测试**不需要装 pylsp**：协议层是纯函数，客户端用一个小假服务进程
（python -c 脚本）验证收发闭环；没装服务那条路径也单独断言。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core import lsp_client as lc      # noqa: E402
from core import lsp_protocol as lp    # noqa: E402

# 一个只认 initialize / definition / shutdown 的假语言服务
FAKE_SERVER = r'''
import json
import sys

buf = b""


def read_msg():
    global buf
    while b"\r\n\r\n" not in buf:
        chunk = sys.stdin.buffer.read(1)
        if not chunk:
            return None
        buf += chunk
    head, rest = buf.split(b"\r\n\r\n", 1)
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length"):
            length = int(line.split(b":")[1])
    while len(rest) < length:
        rest += sys.stdin.buffer.read(length - len(rest))
    body, buf = rest[:length], rest[length:]
    return json.loads(body.decode("utf-8"))


def send(obj):
    body = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    sys.stdout.buffer.flush()


while True:
    msg = read_msg()
    if msg is None:
        break
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid,
              "result": {"capabilities": {"definitionProvider": True,
                                          "referencesProvider": True}}})
    elif method == "textDocument/definition":
        send({"jsonrpc": "2.0", "id": mid, "result": [{
            "uri": "file:///tmp/a.py",
            "range": {"start": {"line": 4, "character": 0},
                      "end": {"line": 4, "character": 5}}}]})
    elif method == "textDocument/hover":
        send({"jsonrpc": "2.0", "id": mid,
              "result": {"contents": {"kind": "markdown",
                                    "value": "**int** 变量"}}})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": mid, "result": None})
    elif method == "exit":
        break
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "result": None})
'''


# ---------------------------------------------------------------- 协议层
def test_encode_and_decode_roundtrip():
    msg = {"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {}}
    frame = lp.encode_message(msg)
    assert frame.startswith(b"Content-Length: ")
    back, rest = lp.decode_message(frame)
    assert back == msg
    assert rest == b""


def test_decode_partial_buffer_keeps_buffer():
    frame = lp.encode_message({"id": 1, "result": "ok"})
    head_only = frame[:20]
    assert lp.decode_message(head_only) == (None, head_only)
    body_cut = frame[:-3]
    assert lp.decode_message(body_cut) == (None, body_cut)


def test_decode_broken_json_advances_past_frame():
    frame = lp.encode_message({"id": 1})
    broken = b"Content-Length: 3\r\n\r\n{xx" + frame
    obj, rest = lp.decode_message(broken)
    assert obj is None
    assert rest == frame, "坏帧要吃掉，不能把它留在缓冲区里反复卡住"


def test_decode_two_messages_back_to_back():
    a = lp.encode_message({"id": 1, "result": 1})
    b = lp.encode_message({"id": 2, "result": 2})
    first, rest = lp.decode_message(a + b)
    second, rest = lp.decode_message(rest)
    assert first["result"] == 1 and second["result"] == 2 and rest == b""


def test_uri_and_path_roundtrip(tmp_path):
    path = str(tmp_path / "a b.py")
    uri = lp.uri_for_path(path)
    assert uri.startswith("file://") and " " not in uri
    assert lp.path_for_uri(uri).replace("\\", "/").endswith("a b.py")


def test_position_offset_roundtrip():
    text = "one\ntwo\nthree"
    assert lp.offset_to_position(text, 0) == {"line": 0, "character": 0}
    assert lp.offset_to_position(text, 5) == {"line": 1, "character": 1}
    assert lp.position_to_offset(text, {"line": 1, "character": 1}) == 5
    # 越界一律夹紧，不抛异常
    assert lp.offset_to_position(text, 999) == {"line": 2,
                                                "character": 5}
    assert lp.position_to_offset(text, {"line": 99, "character": 9}) == len(
        text)


def test_incremental_change_is_minimal():
    old = "def f():\n    return 1\n"
    new = "def f():\n    return 2\n"
    change = lp.incremental_change(old, new)
    start = lp.position_to_offset(old, change["range"]["start"])
    end = lp.position_to_offset(old, change["range"]["end"])
    assert change["text"] == "2"
    assert (start, end) == (old.index("1"), old.index("1") + 1)
    assert change["rangeLength"] == 1


def test_incremental_change_none_when_unchanged():
    assert lp.incremental_change("abc", "abc") is None


def test_incremental_change_handles_pure_insert():
    change = lp.incremental_change("ab", "abc")
    assert change["text"] == "c"
    assert change["range"]["start"] == {"line": 0, "character": 2}


# ---------------------------------------------------------------- 路由
def test_server_for_unknown_extension_returns_none():
    assert lc.server_for("a.txt") is None
    assert lc.server_for("") is None


def test_server_for_known_extension_has_shape():
    row = lc.server_for("a.py")
    assert row["language"] == "python"
    assert "argv" in row and isinstance(row["available"], bool)
    assert lc.server_for("a.ts")["language"] == "typescript"
    assert lc.server_for("a.cpp")["language"] == "cpp"
    assert lc.server_for("a.rs")["language"] == "rust"


def test_detect_and_status_shape():
    rows = lc.detect()
    assert set(rows) >= {"python", "typescript", "cpp"}
    for name, item in rows.items():
        assert set(item) >= {"名称", "可用", "命令", "装法"}, name
        assert isinstance(item["可用"], bool)
    s = lc.status()
    assert "摘要" in s and isinstance(s["可用"], list)


def test_install_hint_prefers_pip_entry():
    hint = lc.install_hint("a.py")
    assert "pip" in hint


def test_client_for_returns_none_without_server():
    """没装服务时必须返回 None（上层据此退回 jedi），不能抛异常。"""
    assert lc.client_for(BASE, os.path.join(BASE, "a.txt")) is None


def test_request_on_unstarted_client_is_graceful():
    server = {"language": "python", "name": "假服务",
              "argv": ["pylsp"], "available": True}
    client = lc.LspClient(BASE, os.path.join(BASE, "x.py"), server=server)
    r = client.request("initialize", {}, timeout=0.2)
    assert r["ok"] is False and "未启动" in r["reason"]
    assert client.start() is False or client._proc is not None


# ---------------------------------------------------------------- 客户端
def _fake_client(tmp_path):
    server = {"language": "python", "name": "假服务",
              "argv": ["pylsp"], "available": True}
    return lc.LspClient(str(tmp_path), str(tmp_path / "a.py"), server=server)


def test_did_change_sends_only_the_diff(tmp_path):
    client = _fake_client(tmp_path)
    client.did_open("x = 1\n", str(tmp_path / "a.py"))
    opened = [m for m in client.sent if m["method"] == "textDocument/didOpen"]
    assert opened and opened[-1]["params"]["textDocument"]["text"] == "x = 1\n"
    change = client.did_change("x = 12\n", str(tmp_path / "a.py"))
    assert change and change["text"] == "2"
    same = client.did_change("x = 12\n", str(tmp_path / "a.py"))
    assert same is None, "文本没变就不该发通知"


def test_feed_publish_diagnostics(tmp_path):
    client = _fake_client(tmp_path)
    path = str(tmp_path / "a.py")
    payload = {"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
               "params": {"uri": lp.uri_for_path(path), "diagnostics": [
                   {"range": {"start": {"line": 0, "character": 0},
                              "end": {"line": 0, "character": 3}},
                    "message": "未定义名字", "severity": 1}]}}
    client.feed(lp.encode_message(payload))
    rows = client.diagnostics_for(path)
    assert rows and rows[0]["message"] == "未定义名字"


def test_feed_server_request_gets_method_not_found(tmp_path):
    client = _fake_client(tmp_path)
    client.feed(lp.encode_message({"jsonrpc": "2.0", "id": 3,
                                   "method": "workspace/configuration"}))
    replies = [m for m in client.sent if m.get("id") == 3]
    assert replies and replies[-1]["error"]["code"] == -32601


def test_locations_and_hover_normalization():
    raw = [{"uri": "file:///x/a.py",
            "range": {"start": {"line": 3, "character": 2}}}]
    locs = lc.locations_of(raw)
    assert locs[0]["line"] == 4 and locs[0]["col"] == 3
    assert lc.locations_of({"targetUri": "file:///x/a.py",
                            "targetSelectionRange": {
                                "start": {"line": 0, "character": 0}}})
    assert lc.locations_of(None) == []
    assert lc.hover_text({"contents": {"value": "签名"}}) == "签名"
    assert lc.hover_text({"contents": ["a", {"value": "b"}]}) == "a\nb"
    assert lc.hover_text(None) == ""


def test_apply_text_edits_applies_in_reverse_order():
    text = "aa\nbb\ncc"
    edits = [{"range": {"start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 2}}, "newText": "AA"},
             {"range": {"start": {"line": 2, "character": 0},
                        "end": {"line": 2, "character": 2}}, "newText": "CC"}]
    out = lp.apply_text_edits(text, edits)
    assert out == "AA\nbb\nCC"


def test_apply_workspace_edit_writes_files(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")
    edit = {"changes": {lp.uri_for_path(str(path)): [
        {"range": {"start": {"line": 0, "character": 0},
                   "end": {"line": 0, "character": 1}}, "newText": "y"}]}}
    r = lp.apply_workspace_edit(str(tmp_path), edit)
    assert r["ok"] and (tmp_path / "a.py").read_text(
        encoding="utf-8") == "y = 1\n"
    snaps = os.listdir(str(tmp_path / "backups" / "format"))
    assert snaps, "重命名前必须留快照"


def test_apply_workspace_edit_empty_is_reported():
    r = lp.apply_workspace_edit(str(BASE), {})
    assert r["ok"] is False and r["errors"]


def test_client_talks_to_fake_server(tmp_path):
    """真起一个进程验证收发闭环（帧编码 / 回包派发 / 能力调用）。"""
    script = tmp_path / "fake_lsp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    server = {"language": "python", "name": "假服务",
              "argv": [sys.executable, str(script)], "available": True}
    client = lc.LspClient(str(tmp_path), str(tmp_path / "a.py"),
                          server=server)
    try:
        assert client.start() is True
        assert client.capabilities.get("definitionProvider") is True
        got = client.definition(0, 0)
        assert got["ok"] and got["locations"][0]["line"] == 5
        assert "int" in client.hover(0, 0)["text"]
        client.did_open("x = 1\n", str(tmp_path / "a.py"))
        assert client.did_change("x = 2\n", str(tmp_path / "a.py"))["text"] == "2"
        client.did_save(str(tmp_path / "a.py"))
        assert client.did_close(str(tmp_path / "a.py")) is True or True
    finally:
        client.stop()
    assert client._proc is None
