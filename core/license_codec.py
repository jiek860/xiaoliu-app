# -*- coding: utf-8 -*-
"""激活码 Base32 编解码、格式化和标志描述。"""
from __future__ import annotations

import base64

from core.license_payload import PAYLOAD_SIZE

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

PREFIX = "X6AI-"

GROUP = 5

FLAG_EXPIRE = 1

FLAG_MACHINE = 2

FLAG_DEVICES = 4

FLAG_EMAIL = 8

LEVEL_NAMES = {0: "标准版", 1: "专业版", 2: "旗舰版"}

_B32_ALPH = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

def _b32enc(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=")

def _b32dec(s: str) -> bytes:
    s = "".join(ch for ch in s.upper() if ch in _B32_ALPH)
    if not s:
        raise ValueError("激活码为空")
    pad = "=" * ((8 - len(s) % 8) % 8)
    raw = base64.b32decode(s + pad)
    # 严格 round-trip 校验：重新编码必须还原原字符串，
    # 杜绝"篡改末位填充 bit 后解码结果不变"的绕过（Python 3.12 默认不检查填充 bit）
    if _b32enc(raw) != s:
        raise ValueError("激活码格式错误（数据校验失败）")
    return raw

def format_code(raw: bytes, prefix: str = PREFIX) -> str:
    """raw → base32 → 每 5 字符一组，前缀-组-组-..."""
    b = _b32enc(raw)
    groups = [b[i:i + GROUP] for i in range(0, len(b), GROUP)]
    return prefix.rstrip("-") + "-" + "-".join(groups)

def parse_code(code: str, prefix: str | None = None) -> bytes:
    """解析激活码为 bytes。prefix=None 时自动识别任意前缀：
    依次尝试 ①原码去分隔符 ②默认 X6AI- 前缀剥离 ③每个 '-' 分割点剥离，
    直到解码出合法长度（HMAC 28B / RSA 278B）。
    """
    c = code.strip()
    if prefix is not None:
        p = prefix.rstrip("-") + "-"
        if c.upper().startswith(p.upper()):
            c = c[len(p):]
        return _b32dec(c)
    cands = [c]
    if c.upper().startswith(PREFIX.upper()):
        cands.append(c[len(PREFIX):])
    pos = -1
    while True:
        pos = c.find("-", pos + 1)
        if pos < 0:
            break
        cands.append(c[pos + 1:])
    for cc in cands:
        try:
            raw = _b32dec(cc)
            if len(raw) in (PAYLOAD_SIZE + 6, PAYLOAD_SIZE + 256):
                return raw
        except Exception as e:
            _x6_swallowed(__name__, e)
            continue
    raise ValueError("激活码格式错误")

def flags_desc(flags: int) -> str:
    parts = ["永久" if not (flags & FLAG_EXPIRE) else "时间"]
    if flags & FLAG_MACHINE:
        parts.append("机器绑定")
    if flags & FLAG_DEVICES:
        parts.append("设备数")
    if flags & FLAG_EMAIL:
        parts.append("邮箱绑定")
    return "+".join(parts)
