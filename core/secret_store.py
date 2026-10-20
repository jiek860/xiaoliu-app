# -*- coding: utf-8 -*-
"""配置里的敏感字段加密（Windows DPAPI）

为什么要做
----------
data/config.json 里躺着 cloud_key / webhook / secret 明文，而且程序还会
自动备份 2 份。任何人拷走这个文件就能用你的 Key  不需要反编译程序。

加密方式
--------
Windows DPAPI（CryptProtectData）：
  - 密钥由系统按**当前 Windows 用户**保管，程序自己不管密钥
  - 同一个用户在这台机器上能解开
  - 文件被拷到别的机器 / 别的用户 -> 解不开（这正是我们要的）

兼容与降级
----------
  - 只有带 "dpapi:v1:" 前缀的值才解密，其余原样返回
  - 非 Windows / DPAPI 调用失败 -> 原样返回（退化成明文，不影响运行）
  - config.default.json 中的通知默认凭据使用应用级静态密文保存；
    首次运行/读取时由 core.default_secrets 还原后再由 DPAPI 重新保护
  - 解不开时返回原字符串（当作无效值），不会抛异常
"""
import base64
import ctypes
import os
import re
from ctypes import wintypes

PREFIX = "dpapi:v1:"

# 键名命中这些词、且值是非空字符串 -> 加密（int/bool 一律放过，
# 比如 max_tokens_reply 虽然含 token，但它是数字，不该动）
_SENSITIVE_KEY = re.compile(
    r"(key|secret|token|passwd|password|_pass$|webhook)", re.I)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _make_blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf          # buf 要留引用，否则会被回收


def _dpapi(data, protect):
    if os.name != "nt":
        return None
    try:
        src, _keep = _make_blob(data)
        out = _DATA_BLOB()
        fn = (ctypes.windll.crypt32.CryptProtectData if protect
              else ctypes.windll.crypt32.CryptUnprotectData)
        ok = fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out))
        if not ok:
            return None
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)
    except (OSError, AttributeError, ValueError):
        return None


def encrypt_value(text):
    """明文 -> "dpapi:v1:<base64>"；失败/非 Windows 则原样返回"""
    if not isinstance(text, str) or not text or text.startswith(PREFIX):
        return text
    raw = _dpapi(text.encode("utf-8"), True)
    if raw is None:
        return text
    return PREFIX + base64.b64encode(raw).decode("ascii")


def decrypt_value(text):
    """带前缀的值 -> 明文；解不开/没前缀则原样返回"""
    if not isinstance(text, str) or not text.startswith(PREFIX):
        return text
    try:
        raw = base64.b64decode(text[len(PREFIX):])
    except (ValueError, TypeError):
        return text
    plain = _dpapi(raw, False)
    if plain is None:
        return text
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return text


def is_sensitive_key(key):
    return bool(_SENSITIVE_KEY.search(str(key)))


def encrypt_config(cfg):
    """返回 (新配置, 本次加密了几个字段)。不修改传入的 dict。"""
    n = 0
    out = {}
    for k, v in (cfg or {}).items():
        if isinstance(v, dict):
            sub, sn = encrypt_config(v)
            out[k] = sub
            n += sn
        elif (isinstance(v, str) and v and is_sensitive_key(k)
              and not v.startswith(PREFIX)):
            enc = encrypt_value(v)
            if enc != v:
                n += 1
            out[k] = enc
        else:
            out[k] = v
    return out, n


def decrypt_config(cfg):
    """返回解密后的新配置。不修改传入的 dict。

    先解 DPAPI，再解默认配置里的应用级密文。后者只用于
    config.default.json / DEFAULTS 这类随程序分发的默认值。
    """
    out = {}
    for k, v in (cfg or {}).items():
        if isinstance(v, dict):
            out[k] = decrypt_config(v)
        elif isinstance(v, str) and v.startswith(PREFIX):
            out[k] = decrypt_value(v)
        else:
            out[k] = v
    try:
        from core.default_secrets import decrypt_tree
        return decrypt_tree(out)
    except Exception:
        return out
