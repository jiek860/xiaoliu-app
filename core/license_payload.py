# -*- coding: utf-8 -*-
"""激活码 payload v3 编解码。"""
from __future__ import annotations

import struct

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

EPOCH = (2000, 1, 1)

PAYLOAD_SIZE = 22

def _days_from_date_str(expire_date: str) -> int:
    from datetime import date
    y, m, d = [int(x) for x in str(expire_date).strip().replace("/", "-").split("-")]
    days = (date(y, m, d) - date(*EPOCH)).days
    if days <= 0:
        raise ValueError("到期日必须晚于 2000-01-01")
    return days

def _date_str_from_days(days: int) -> str:
    from datetime import date, timedelta
    return (date(*EPOCH) + timedelta(days=days)).isoformat()

def _encode_payload(hdr: int, flags: int, expire_days: int, machine_int: int,
                    devices: int, verlock: int, identity_int: int,
                    features: int, salt: int) -> bytes:
    return struct.pack(">BBIIHHIHH", hdr & 0xFF, flags & 0xFF,
                       expire_days & 0xFFFFFFFF, machine_int & 0xFFFFFFFF,
                       devices & 0xFFFF, verlock & 0xFFFF,
                       identity_int & 0xFFFFFFFF, features & 0xFFFF, salt & 0xFFFF)

def _decode_payload(raw: bytes) -> dict:
    hdr, flags, expire_days, machine_int, devices, verlock, identity_int, features, salt = \
        struct.unpack(">BBIIHHIHH", raw)
    return {"version": hdr >> 5, "level": hdr & 7, "flags": flags,
            "expire_days": expire_days, "machine_int": machine_int,
            "devices": devices, "verlock": verlock,
            "identity_int": identity_int, "features": features, "salt": salt}
