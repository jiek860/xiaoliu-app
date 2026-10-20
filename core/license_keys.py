# -*- coding: utf-8 -*-
"""授权密钥、机器码、身份和目录工具。"""
from __future__ import annotations

import hashlib
import os
import platform
import secrets
import sys
import uuid

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

def _ih(pkg):
    try:
        from core.error_text import install_hint
        return install_hint(pkg)
    except Exception:
        return ("py -3 -m pip install --target optional_libs %s "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple" % pkg)

SECRET_FILE = "密钥.key"

PRIV_FILE = "私钥.pem"

PUB_FILE = "公钥.pem"

ACT_PUB_FILE = "激活公钥.pem"

def tool_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def vault_dir() -> str:
    """开发者密钥库目录（不随程序分发）。可用环境变量 X6_KEY_VAULT 覆盖。"""
    return os.environ.get("X6_KEY_VAULT") or os.path.join(
        os.path.expanduser("~"), ".xiao6-keys")

def _read_secret_file(path: str):
    """读密钥文件；长度不足 16 字节视为无效"""
    try:
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                s = f.read().strip()
            if len(s) >= 16:
                return s
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass
    return None

def find_license_secret() -> bytes | None:
    """只读地查找 HMAC 密钥，找不到返回 None。

    查找顺序（先外部、后程序内）：
      1. 环境变量 X6_LICENSE_KEY 指定的文件路径
      2. 环境变量 X6_KEY_VAULT / 默认密钥库 ~/.xiao6-keys 下的 密钥.key
      3. 程序目录下的 密钥.key（仅开发机兼容；发布包不应携带此文件）

    说明：HMAC 是共享密钥方案，密钥一旦随程序分发即等于授权失效。
    发布包请勿包含 密钥.key，改为使用 RSA 模式（程序只需公钥）。
    """
    cands = []
    env_path = os.environ.get("X6_LICENSE_KEY")
    if env_path:
        cands.append(env_path)
    cands.append(os.path.join(vault_dir(), SECRET_FILE))
    cands.append(os.path.join(tool_dir(), SECRET_FILE))
    for p in cands:
        s = _read_secret_file(p)
        if s:
            return s
    return None

def load_or_create_secret(secret_path: str | None = None) -> bytes:
    """HMAC 模式：读取 密钥.key；不存在则生成。

    默认读写【密钥库】而非程序目录，避免共享密钥被写进并随程序分发。
    """
    if secret_path is None:
        secret_path = os.path.join(vault_dir(), SECRET_FILE)
    s = _read_secret_file(secret_path)
    if s:
        return s
    s = secrets.token_bytes(32)
    try:
        os.makedirs(os.path.dirname(secret_path), exist_ok=True)
        with open(secret_path, "wb") as f:
            f.write(s)
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass
    return s

def load_or_create_keypair(priv_path: str | None = None) -> object:
    """RSA 模式：读取/生成 RSA-2048 私钥对象。缺失则生成并保存 私钥.pem + 公钥.pem

    默认放在【密钥库】目录，绝不写进程序目录（私钥绝不能随程序分发）。
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
    except ImportError as e:
        raise RuntimeError("RSA 模式需要 cryptography 库。\n"
                           + _ih("cryptography")) from e
    if priv_path is None:
        priv_path = os.path.join(vault_dir(), PRIV_FILE)
    pub_path = os.path.join(os.path.dirname(priv_path), PUB_FILE)
    if os.path.exists(priv_path):
        with open(priv_path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with open(priv_path, "wb") as f:
        f.write(priv_pem)
    with open(pub_path, "wb") as f:
        f.write(pub_pem)
    return key

def pubkey_pem(pub_key) -> str:
    from cryptography.hazmat.primitives import serialization
    return pub_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

def activation_pubkey_path(base_dir: str) -> str:
    """激活码验签公钥路径：优先 core/激活公钥.pem，兼容旧的 core/公钥.pem。

    注意：core/公钥.pem 是【更新包签名】的公钥，与激活码密钥对不是同一套。
    早期版本把两者当成同一把，导致生成器签发的 RSA 激活码全部验签失败。
    """
    p = os.path.join(base_dir, "core", ACT_PUB_FILE)
    if os.path.exists(p):
        return p
    return os.path.join(base_dir, "core", PUB_FILE)

def load_activation_pubkey(base_dir: str):
    """加载激活码验签公钥对象；文件缺失或格式错误时返回 None"""
    try:
        from cryptography.hazmat.primitives import serialization
        with open(activation_pubkey_path(base_dir), "rb") as f:
            return serialization.load_pem_public_key(f.read())
    except Exception:
        return None

def get_machine_code() -> str:
    seed = "%s|%s|%s" % (platform.node(), platform.machine(), uuid.getnode())
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

def _machine_int(machine_code: str | None) -> int:
    if not machine_code:
        return 0
    return int(hashlib.sha256(machine_code.encode("utf-8")).hexdigest()[:8], 16)

def _identity_int(identity: str | None) -> int:
    if not identity:
        return 0
    return int(hashlib.sha256(identity.strip().lower().encode("utf-8")).hexdigest()[:8], 16)
