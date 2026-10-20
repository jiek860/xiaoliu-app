# -*- coding: utf-8 -*-
"""激活码生成和 HMAC/RSA 验证。"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from core.license_codec import (
    FLAG_DEVICES, FLAG_EMAIL, FLAG_EXPIRE, FLAG_MACHINE, PREFIX,
    format_code, parse_code,
)
from core.license_file import (
    _write_lic_plain, read_lic_file, write_lic_file,
)
from core.license_keys import _identity_int, _machine_int
from core.license_payload import (
    PAYLOAD_SIZE, _date_str_from_days, _days_from_date_str,
    _decode_payload, _encode_payload,
)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

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
            res["expire"] = _date_str_from_days(info["expire_days"])
            if today is None:
                from datetime import date
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
