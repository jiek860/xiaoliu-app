# -*- coding: utf-8 -*-
"""MCP 服务器信任管理（解决"每次启动都弹窗"）。

背景
----
MCP 服务器启动前会请求用户确认。用户点「永久允许」后，命令哈希写入
``data/plugin_data/mcp_client/mcp_trust.json``，以后同一条命令不再询问。

设计要点
--------
* 哈希 = sha256(命令字符串)[:16]。命令**一旦改动**哈希就变，会重新询问
  —— 这是防止命令被悄悄替换的安全设计，不能为了"少弹窗"而放宽。
* 写盘失败必须返回明确错误，不能假装成功：否则用户以为授权了，
  下次启动照样弹窗，还会以为程序坏了。
* 全部操作写审计（N15 格式）。

独立成模块的原因：mcp_client.py 已接近 600 行上限，信任管理属于
可分离的纯逻辑，拆出来更好测。
"""
from __future__ import annotations

import hashlib
import json
import os


def command_hash(command):
    """命令字符串 -> 16 位十六进制哈希（与 core.mcp_sandbox 保持一致）。"""
    return hashlib.sha256(
        str(command or "").encode("utf-8", "replace")).hexdigest()[:16]


def trust_path(base):
    """信任文件的规范位置（含旧路径迁移）。"""
    base = str(base or ".")
    new = os.path.join(base, "data", "plugin_data", "mcp_client",
                       "mcp_trust.json")
    legacy = os.path.join(base, "data", "security", "mcp_trust.json")
    if not os.path.exists(new) and os.path.exists(legacy):
        try:  # 静默是故意的 - 迁移失败不影响新路径使用
            os.makedirs(os.path.dirname(new), exist_ok=True)
            os.replace(legacy, new)
        except OSError:
            pass
    return new


def load_trusted(base):
    try:
        data = json.load(open(trust_path(base), encoding="utf-8"))
        return set(data.get("trusted_commands") or [])
    except (OSError, ValueError, AttributeError):
        return set()


def save_trusted(base, hashes):
    """原子写入信任列表。返回 (ok, error_message)。"""
    path = trust_path(base)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"trusted_commands": sorted(set(hashes))}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True, ""
    except OSError as e:
        return False, "写入信任文件失败: %s" % str(e)[:120]


def is_trusted(base, command):
    return command_hash(command) in load_trusted(base)
