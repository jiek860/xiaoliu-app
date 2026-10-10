# -*- coding: utf-8 -*-
r"""一个最小的 stdio MCP 服务器，专供测试用（不依赖 npx / uvx / 网络）

实现 initialize / notifications/initialized / tools/list / tools/call，
提供两个工具：
    echo(text)  原样回显，验证正常调用链路
    boom()      返回 isError，验证错误路径

故意先往 stdout 打一行非 JSON 的横幅，用来验证客户端能容忍
（真实服务器也常常会打启动日志）。
"""
import json
import sys

TOOLS = [
    {"name": "echo", "description": "原样返回输入的文字",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "boom", "description": "故意报错，用来测错误路径",
     "inputSchema": {"type": "object", "properties": {}}},
]


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    # --silent：只读不回。用来确定性地测超时路径 ——
    # 靠"把超时设得极短"是不稳的，服务器响应够快就不触发。
    silent = "--silent" in sys.argv

    # 非 JSON 横幅：客户端应当忽略而不是报错
    sys.stdout.write("fake-mcp-server ready\n")
    sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if silent:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method = msg.get("method")
        rid = msg.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-mcp", "version": "0.1"}}})
        elif method == "notifications/initialized":
            pass                      # 通知，不用回
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            name = p.get("name")
            args = p.get("arguments") or {}
            if name == "echo":
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text",
                                 "text": "echo: " + str(args.get("text", ""))}]}})
            elif name == "boom":
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": "出错了"}],
                    "isError": True}})
            else:
                send({"jsonrpc": "2.0", "id": rid,
                      "error": {"code": -32601, "message": "未知工具: %s" % name}})
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid,
                  "error": {"code": -32601, "message": "未知方法: %s" % method}})


if __name__ == "__main__":
    main()
