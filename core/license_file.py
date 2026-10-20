# -*- coding: utf-8 -*-
""".lic 授权文件的 AES-GCM 加解密与读写。"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

def _lic_aes_key(secret: bytes) -> bytes:
    """从密钥派生 .lic 加密专用 AES-256 密钥（与激活码签名密钥隔离）"""
    return hashlib.sha256(b"x6lic-v1|" + secret).digest()

def encrypt_lic(content: bytes, secret: bytes) -> str:
    """AES-GCM 加密 → 'X6LIC1:' + base64(iv + tag + ciphertext)"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _lic_aes_key(secret)
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, content, None)
    return "X6LIC1:" + base64.b64encode(iv + ct).decode("ascii")

def decrypt_lic(payload: str, secret: bytes) -> bytes:
    """解密 encrypt_lic 产物"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _lic_aes_key(secret)
    raw = base64.b64decode(payload.split(":", 1)[1])
    if len(raw) < 12:
        raise ValueError("授权文件数据损坏")
    return AESGCM(key).decrypt(raw[:12], raw[12:], None)

def write_lic_file(path: str, code: str, secret: bytes,
                   meta: dict | None = None) -> None:
    """加密写 .lic：内容为 {code, meta} 的 JSON，AES-GCM 加密"""
    data = json.dumps({"code": code, "meta": meta or {}}, ensure_ascii=False).encode("utf-8")
    enc = encrypt_lic(data, secret)
    with open(path, "w", encoding="utf-8") as f:
        f.write("=== 小6AI 授权文件 ===\n")
        f.write("ENC=" + enc + "\n")

def _write_lic_plain(path: str, code: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("=== 小6AI 授权文件 ===\n")
        f.write("KEY=" + code + "\n")

def read_lic_file(path: str, secret: bytes | None) -> dict:
    """读 .lic：优先解密 ENC 段；兼容旧明文 KEY= 段。返回 {'code', 'meta'}"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    for line in text.splitlines():
        if line.startswith("ENC="):
            if not secret:
                raise ValueError("授权文件已加密，需提供解密密钥")
            return json.loads(decrypt_lic(line[4:].strip(), secret))
    for line in text.splitlines():
        if line.startswith("KEY="):
            return {"code": line[4:].strip(), "meta": {}}
    raise ValueError("授权文件格式无法识别")
