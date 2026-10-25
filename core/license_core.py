# -*- coding: utf-8 -*-
"""授权：密钥、激活码编解码、.lic 加解密与 HMAC/RSA 验证。

一键合并（2026-10-25）：原来拆成 6 个文件
  license_core / license_keys / license_codec / license_payload /
  license_file / license_verify
对外只保留 `core.license_core` 一个导入路径，内部按「密钥 → payload →
编解码 → 文件 → 校验」分段，函数实现未改动。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import secrets
import struct
import sys
import uuid

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


# ══════════════════════════════════════════════════════════════
# 1. 密钥、机器码、身份和目录（原 license_keys.py）
# ══════════════════════════════════════════════════════════════
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
                # 密钥是 32 字节随机二进制，可能以 0x0a/0x20 等空白字节开头，
                # 只能剥掉文本编辑器追加的行尾换行，不能整体 strip。
                s = f.read().rstrip(b"\r\n")
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


# ══════════════════════════════════════════════════════════════
# 2. payload v3 编解码（原 license_payload.py）
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# 3. 激活码 Base32 编解码与格式化（原 license_codec.py）
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# 4. .lic 文件 AES-GCM 加解密与读写（原 license_file.py）
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# 5. 激活码生成与校验（原 license_verify.py）
# ══════════════════════════════════════════════════════════════
def make_license(key, mode: str = "hmac", *, expire_date: str | None = None,
                 machine_code: str | None = None, devices: int = 0,
                 email: str | None = None, level: int = 0, features: int = 0,
                 version_lock: int = 0, prefix: str = PREFIX) -> str:
    """生成激活码。
    mode: 'hmac'（key=密钥 bytes） / 'rsa'（key=私钥对象）
    参数组合：expire_date(时间) machine_code(机器绑定) devices(设备数)
              email(邮箱绑定) level(0标准/1专业/2旗舰) features(功能位)
              version_lock(锁定主版本，0 不限)
    """
    mode = mode.lower()
    if mode not in ("hmac", "rsa"):
        raise ValueError("mode 必须为 hmac 或 rsa")
    level = int(level)
    if level not in (0, 1, 2):
        raise ValueError("等级须为 0/1/2（标准/专业/旗舰）")
    flags = 0
    expire_days = 0
    if expire_date:
        expire_days = _days_from_date_str(expire_date)
        flags |= FLAG_EXPIRE
    machine_i = 0
    if machine_code:
        machine_i = _machine_int(machine_code)
        flags |= FLAG_MACHINE
    if devices:
        devices = int(devices)
        if not 1 <= devices <= 999:
            raise ValueError("设备数须在 1~999")
        flags |= FLAG_DEVICES
    identity_i = 0
    if email:
        identity_i = _identity_int(email)
        flags |= FLAG_EMAIL
    verlock = int(version_lock)
    if verlock < 0 or verlock > 999:
        raise ValueError("版本锁定值无效")
    features = int(features) & 0xFFFF
    hdr = (3 << 5) | level
    salt = secrets.randbelow(65536)
    payload = _encode_payload(hdr, flags, expire_days, machine_i, devices,
                              verlock, identity_i, features, salt)
    if mode == "hmac":
        sig = hmac.new(key, payload, hashlib.sha256).digest()[:6]
    else:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        sig = key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    return format_code(payload + sig, prefix)


def make_license_file(key, *, expire_date=None, machine_code=None, devices=0,
                      email=None, level=0, features=0, version_lock=0,
                      prefix=PREFIX, out_path="授权.lic", secret: bytes | None = None) -> str:
    """RSA/HMAC 模式：生成 .lic 授权文件。
    secret 提供时加密写入（AES-GCM，校验端用同一密钥解密）；None 时写明文（兼容旧端）。
    """
    code = make_license(key, "rsa", expire_date=expire_date, machine_code=machine_code,
                        devices=devices, email=email, level=level,
                        features=features, version_lock=version_lock, prefix=prefix)
    write_lic_file(out_path, code, secret) if secret else _write_lic_plain(out_path, code)
    return out_path


def verify_lic_file(path: str, lic_secret: bytes, license_key=None, **kw) -> dict:
    """校验 .lic 授权文件。lic_secret 用于解密；license_key 用于验签
    （HMAC 模式传密钥，RSA 模式传公钥；None 时默认 = lic_secret）。
    返回与 verify_license 相同的结果。
    """
    data = read_lic_file(path, lic_secret)
    key = lic_secret if license_key is None else license_key
    return verify_license(data["code"], key, **kw)


def verify_license(code: str, key, mode: str = "auto", *, prefix: str | None = None,
                   machine_code: str | None = None,
                   identity: str | None = None, app_version: str = "0.0",
                   today=None) -> dict:
    """校验激活码。key：hmac 模式=密钥 bytes；rsa 模式=公钥对象；mode='auto' 自动判断。
    prefix: 自定义前缀（默认 None 自动识别）；machine_code: 机器码（机器绑定时）；
    identity: 邮箱/用户名（邮箱绑定时）；app_version: 程序当前版本（版本锁定时）。
    返回 valid/reason/level/features/flags/expire/machine_locked/device_limit/email_locked/verlock
    """
    res = {"valid": False, "reason": "", "level": 0, "features": 0, "flags": 0,
           "expire": None, "machine_locked": False, "device_limit": None,
           "email_locked": False, "verlock": None}
    try:
        raw = parse_code(code, prefix=prefix)
        if len(raw) == PAYLOAD_SIZE + 6:
            payload, sig = raw[:PAYLOAD_SIZE], raw[PAYLOAD_SIZE:]
            expect = hmac.new(key, payload, hashlib.sha256).digest()[:6]
            if not hmac.compare_digest(expect, sig):
                res["reason"] = "激活码无效（签名不符）"
                return res
        elif len(raw) == PAYLOAD_SIZE + 256:
            payload, sig = raw[:PAYLOAD_SIZE], raw[PAYLOAD_SIZE:]
            try:
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.asymmetric import padding
                key.verify(sig, payload, padding.PKCS1v15(), hashes.SHA256())
            except Exception:
                res["reason"] = "激活码无效（RSA 签名不符）"
                return res
        else:
            res["reason"] = "激活码格式错误"
            return res

        info = _decode_payload(payload)
        if info["version"] != 3:
            res["reason"] = "激活码版本不支持"
            return res
        flags = info["flags"]
        if flags & ~15:
            res["reason"] = "激活码类型未知"
            return res
        res.update({"flags": flags, "level": info["level"],
                    "features": info["features"],
                    "machine_locked": bool(flags & FLAG_MACHINE),
                    "device_limit": info["devices"] if (flags & FLAG_DEVICES) else None,
                    "email_locked": bool(flags & FLAG_EMAIL),
                    "verlock": info["verlock"] or None})
        # 时间
        if flags & FLAG_EXPIRE:
            from datetime import date
            res["expire"] = _date_str_from_days(info["expire_days"])
            if today is None:
                today = date.today()
            if isinstance(today, str):
                y, m, d = [int(x) for x in today.split("-")]
                today = date(y, m, d)
            if today > date.fromisoformat(res["expire"]):
                res["reason"] = "已过期（%s）" % res["expire"]
                return res
        else:
            res["expire"] = "永久"
        # 机器绑定
        if flags & FLAG_MACHINE:
            if not machine_code:
                res["reason"] = "本机机器码缺失，无法校验绑定"
                return res
            if info["machine_int"] != _machine_int(machine_code):
                res["reason"] = "激活码与本机不匹配"
                return res
        # 邮箱绑定
        if flags & FLAG_EMAIL:
            if not identity:
                res["reason"] = "请输入购买时登记的邮箱/用户名"
                return res
            if info["identity_int"] != _identity_int(identity):
                res["reason"] = "邮箱/用户名与激活码不匹配"
                return res
        # 版本锁定
        if info["verlock"]:
            try:
                cur = int(str(app_version).split(".")[0])
            except Exception:
                cur = 0
            if cur != info["verlock"]:
                res["reason"] = "激活码仅适用于 %d.x 版本" % info["verlock"]
                return res
        res["valid"] = True
        res["reason"] = "ok"
        return res
    except Exception as e:
        res["reason"] = "激活码无法解析：%s" % e
        return res


__all__ = [
    "PREFIX", "SECRET_FILE", "PRIV_FILE", "PUB_FILE", "ACT_PUB_FILE",
    "EPOCH", "PAYLOAD_SIZE", "GROUP", "FLAG_EXPIRE", "FLAG_MACHINE",
    "FLAG_DEVICES", "FLAG_EMAIL", "LEVEL_NAMES", "tool_dir", "vault_dir",
    "find_license_secret", "load_or_create_secret", "load_or_create_keypair",
    "pubkey_pem", "activation_pubkey_path", "load_activation_pubkey",
    "get_machine_code", "format_code", "parse_code", "make_license",
    "make_license_file", "encrypt_lic", "decrypt_lic", "write_lic_file",
    "read_lic_file", "verify_lic_file", "verify_license", "flags_desc",
]
