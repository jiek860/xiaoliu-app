# -*- coding: utf-8 -*-
"""core/license_core.py 的同名测试：密钥、激活码、.lic 加解密与校验。

合并前的 6 个文件（keys/payload/codec/file/verify）现在都在这里，
所以这个文件把整条链路走一遍：生成 → 编码 → 写文件 → 读文件 → 校验，
外加每一条「故意弄坏」的分支（篡改签名、过期、机器/邮箱不匹配、版本锁定）。
"""
import base64
import hashlib
import hmac
import os
import struct

import pytest

import core.license_core as lc


# ──────────────────────────────────────────────────────────────
# 目录与密钥
# ──────────────────────────────────────────────────────────────
def test_tool_dir_points_to_core():
    assert os.path.basename(lc.tool_dir()) == "core"


def test_vault_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("X6_KEY_VAULT", str(tmp_path))
    assert lc.vault_dir() == str(tmp_path)
    monkeypatch.delenv("X6_KEY_VAULT")
    assert lc.vault_dir().endswith(".xiao6-keys")


def test_read_secret_file_requires_16_bytes(tmp_path):
    short = tmp_path / "short.key"
    short.write_bytes(b"12345")
    assert lc._read_secret_file(str(short)) is None
    assert lc._read_secret_file(str(tmp_path / "none.key")) is None
    good = tmp_path / "good.key"
    good.write_bytes(b"x" * 20)
    assert lc._read_secret_file(str(good)) == b"x" * 20


def test_find_license_secret_from_env_path(monkeypatch, tmp_path):
    p = tmp_path / "k.key"
    p.write_bytes(b"y" * 24)
    monkeypatch.setenv("X6_LICENSE_KEY", str(p))
    assert lc.find_license_secret() == b"y" * 24


def test_load_or_create_secret_roundtrip(tmp_path):
    path = str(tmp_path / "vault" / "密钥.key")
    s1 = lc.load_or_create_secret(path)
    assert len(s1) == 32
    assert lc.load_or_create_secret(path) == s1


def test_load_or_create_keypair_and_pubkey(tmp_path):
    os.makedirs(str(tmp_path / "keys"), exist_ok=True)
    priv = str(tmp_path / "keys" / "私钥.pem")
    k1 = lc.load_or_create_keypair(priv)
    assert os.path.exists(priv)
    assert os.path.exists(os.path.join(str(tmp_path), "keys", "公钥.pem"))
    # 再读一次走「文件已存在」分支
    k2 = lc.load_or_create_keypair(priv)
    assert lc.pubkey_pem(k1.public_key()) == lc.pubkey_pem(k2.public_key())
    assert "BEGIN PUBLIC KEY" in lc.pubkey_pem(k1.public_key())


def test_activation_pubkey_path_prefers_activation_file(tmp_path):
    core = tmp_path / "core"
    core.mkdir()
    assert lc.activation_pubkey_path(str(tmp_path)).endswith("公钥.pem")
    (core / lc.ACT_PUB_FILE).write_text("x")
    assert lc.activation_pubkey_path(str(tmp_path)).endswith(lc.ACT_PUB_FILE)


def test_load_activation_pubkey(tmp_path):
    core = tmp_path / "core"
    core.mkdir()
    # 显式 utf-8：CI 的 Windows 默认编码是 cp1252，写中文会 UnicodeEncodeError
    (core / lc.ACT_PUB_FILE).write_text("不是 PEM", encoding="utf-8")
    assert lc.load_activation_pubkey(str(tmp_path)) is None
    key = lc.load_or_create_keypair(str(tmp_path / "priv.pem"))
    (core / lc.ACT_PUB_FILE).write_text(
        lc.pubkey_pem(key.public_key()), encoding="utf-8")
    assert lc.load_activation_pubkey(str(tmp_path)) is not None


def test_machine_code_and_int_hash():
    code = lc.get_machine_code()
    assert len(code) == 16 and int(code, 16) >= 0
    assert lc._machine_int(code) == lc._machine_int(code)
    assert lc._machine_int(None) == 0
    assert lc._identity_int(None) == 0
    assert lc._identity_int("  A@B.com ") == lc._identity_int("a@b.com")


def test_tool_dir_frozen_uses_executable_dir(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert lc.tool_dir() == os.path.dirname(sys.executable)


def test_default_secret_lives_in_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("X6_KEY_VAULT", str(tmp_path / "vault"))
    s = lc.load_or_create_secret()
    assert len(s) == 32
    assert (tmp_path / "vault" / lc.SECRET_FILE).exists()


def test_secret_write_failure_still_returns(monkeypatch, tmp_path):
    # 目录位置被一个同名文件占了 -> makedirs/open 都失败，但内存密钥照常返回
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    s = lc.load_or_create_secret(str(blocker / "sub" / "密钥.key"))
    assert len(s) == 32


def test_read_secret_file_swallows_directory_error(tmp_path):
    assert lc._read_secret_file(str(tmp_path)) is None


def test_keypair_raises_friendly_error_without_cryptography(monkeypatch, tmp_path):
    import sys
    # 已经把 cryptography 缓存在 sys.modules 里，必须把它和子模块一起置 None
    for name in [k for k in list(sys.modules)
                 if k == "cryptography" or k.startswith("cryptography.")]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "cryptography", None)
    with pytest.raises(RuntimeError) as ei:
        lc.load_or_create_keypair(str(tmp_path / "私钥.pem"))
    assert "cryptography" in str(ei.value)


# ──────────────────────────────────────────────────────────────
# payload / codec
# ──────────────────────────────────────────────────────────────
def test_days_and_date_roundtrip():
    # EPOCH = 2000-01-01，所以 2020-01-02 是第 7306 天
    assert lc._days_from_date_str("2020-01-02") == 7306
    assert lc._days_from_date_str("2020/01/02") == 7306
    assert lc._date_str_from_days(7306) == "2020-01-02"
    assert lc._date_str_from_days(1) == "2000-01-02"
    with pytest.raises(ValueError):
        lc._days_from_date_str("2000-01-01")


def test_payload_encode_decode():
    raw = lc._encode_payload((3 << 5) | 2, 7, 100, 12345, 3, 25, 999, 5, 42)
    assert len(raw) == lc.PAYLOAD_SIZE
    info = lc._decode_payload(raw)
    assert info["version"] == 3 and info["level"] == 2
    assert info["flags"] == 7 and info["expire_days"] == 100
    assert info["devices"] == 3 and info["verlock"] == 25


def test_b32_roundtrip_and_errors():
    # parse_code 只认合法激活码长度：HMAC 28B / RSA 278B
    raw = b"\x01" * (lc.PAYLOAD_SIZE + 6)
    code = lc.format_code(raw)
    assert code.startswith(lc.PREFIX)
    assert lc.parse_code(code) == raw
    with pytest.raises(ValueError):
        lc._b32dec("")


def test_parse_code_custom_prefix_and_hyphen_scan():
    raw = b"\x02" * (lc.PAYLOAD_SIZE + 6)
    code = lc.format_code(raw, prefix="X6PRO")
    assert lc.parse_code(code, prefix="X6PRO") == raw
    assert lc.parse_code(code) == raw


def test_parse_code_rejects_garbage():
    with pytest.raises(ValueError):
        lc.parse_code("这不是激活码")


def test_flags_desc_all_combinations():
    assert lc.flags_desc(0) == "永久"
    assert lc.flags_desc(lc.FLAG_EXPIRE) == "时间"
    assert "机器绑定" in lc.flags_desc(lc.FLAG_MACHINE)
    assert "设备数" in lc.flags_desc(lc.FLAG_DEVICES)
    assert "邮箱绑定" in lc.flags_desc(lc.FLAG_EMAIL)
    assert lc.flags_desc(15) == "时间+机器绑定+设备数+邮箱绑定"


# ──────────────────────────────────────────────────────────────
# .lic 文件
# ──────────────────────────────────────────────────────────────
def test_lic_encrypt_decrypt_roundtrip():
    secret = b"k" * 32
    enc = lc.encrypt_lic("hello 授权".encode("utf-8"), secret)
    assert enc.startswith("X6LIC1:")
    assert lc.decrypt_lic(enc, secret) == "hello 授权".encode("utf-8")


def test_lic_tampered_ciphertext_raises():
    secret = b"k" * 32
    enc = lc.encrypt_lic(b"payload", secret)
    body = list(enc)
    body[-3] = "A" if body[-3] != "A" else "B"
    with pytest.raises(Exception):
        lc.decrypt_lic("".join(body), secret)


def test_lic_too_short_raises():
    with pytest.raises(ValueError):
        lc.decrypt_lic("X6LIC1:" + base64.b64encode(b"123").decode(), b"k" * 32)


def test_lic_file_encrypted_and_plain(tmp_path):
    secret = b"s" * 32
    enc_path = str(tmp_path / "e.lic")
    lc.write_lic_file(enc_path, "CODE-1", secret, {"user": "张三"})
    assert "ENC=" in open(enc_path, encoding="utf-8").read()
    assert lc.read_lic_file(enc_path, secret) == {"code": "CODE-1", "meta": {"user": "张三"}}
    with pytest.raises(ValueError):
        lc.read_lic_file(enc_path, None)

    plain_path = str(tmp_path / "p.lic")
    lc._write_lic_plain(plain_path, "CODE-2")
    assert lc.read_lic_file(plain_path, None) == {"code": "CODE-2", "meta": {}}


def test_read_lic_file_bad_format(tmp_path):
    p = tmp_path / "bad.lic"
    p.write_text("随便写点\n", encoding="utf-8")
    with pytest.raises(ValueError):
        lc.read_lic_file(str(p), None)


# ──────────────────────────────────────────────────────────────
# 生成 + 校验（HMAC）
# ──────────────────────────────────────────────────────────────
def test_make_license_parameter_validation():
    key = b"k" * 32
    with pytest.raises(ValueError):
        lc.make_license(key, mode="des")
    with pytest.raises(ValueError):
        lc.make_license(key, level=9)
    with pytest.raises(ValueError):
        lc.make_license(key, devices=1000)
    with pytest.raises(ValueError):
        lc.make_license(key, version_lock=-1)


def test_hmac_permanent_license_valid():
    key = b"k" * 32
    code = lc.make_license(key, level=1, features=3)
    r = lc.verify_license(code, key)
    assert r["valid"] is True and r["reason"] == "ok", r
    assert r["level"] == 1 and r["features"] == 3
    assert r["expire"] == "永久" and r["verlock"] is None


def test_signature_tamper_is_rejected():
    key = b"k" * 32
    code = lc.make_license(key)
    raw = lc.parse_code(code)
    bad = bytearray(raw)
    bad[0] ^= 0xFF
    r = lc.verify_license(lc.format_code(bytes(bad)), key)
    assert r["valid"] is False and "签名" in r["reason"], r
    r2 = lc.verify_license(lc.format_code(raw), b"w" * 32)
    assert r2["valid"] is False and "签名" in r2["reason"], r2


def test_expire_date_branches():
    key = b"k" * 32
    code = lc.make_license(key, expire_date="2020-06-01")
    assert lc.verify_license(code, key, today="2020-05-01")["valid"] is True
    expired = lc.verify_license(code, key, today="2020-07-01")
    assert expired["valid"] is False and "过期" in expired["reason"], expired
    assert expired["expire"] == "2020-06-01"
    # today 传 date 对象
    from datetime import date
    assert lc.verify_license(code, key, today=date(2020, 5, 1))["valid"] is True


def test_machine_binding_branches():
    key = b"k" * 32
    code = lc.make_license(key, machine_code="mc-1")
    assert lc.verify_license(code, key, machine_code="mc-1")["valid"] is True
    assert lc.verify_license(code, key, machine_code="mc-2")["machine_locked"] is True
    miss = lc.verify_license(code, key)
    assert miss["valid"] is False and "机器码" in miss["reason"], miss


def test_email_binding_branches():
    key = b"k" * 32
    code = lc.make_license(key, email="User@Example.com")
    assert lc.verify_license(code, key, identity="user@example.com")["valid"] is True
    wrong = lc.verify_license(code, key, identity="other@example.com")
    assert wrong["valid"] is False and "不匹配" in wrong["reason"], wrong
    miss = lc.verify_license(code, key)
    assert miss["valid"] is False and "邮箱" in miss["reason"], miss


def test_devices_and_verlock():
    key = b"k" * 32
    code = lc.make_license(key, devices=3, version_lock=25)
    r = lc.verify_license(code, key, app_version="25.2.24")
    assert r["valid"] is True and r["device_limit"] == 3 and r["verlock"] == 25
    bad = lc.verify_license(code, key, app_version="24.1.0")
    assert bad["valid"] is False and "仅适用于" in bad["reason"], bad
    weird = lc.verify_license(code, key, app_version="abc")
    assert weird["valid"] is False


def test_unknown_version_and_flags_rejected():
    key = b"k" * 32
    payload = lc._encode_payload((2 << 5) | 0, 0, 0, 0, 0, 0, 0, 0, 0)
    sig = hmac.new(key, payload, hashlib.sha256).digest()[:6]
    r = lc.verify_license(lc.format_code(payload + sig), key)
    assert r["valid"] is False and "版本" in r["reason"], r

    payload2 = lc._encode_payload((3 << 5) | 0, 16, 0, 0, 0, 0, 0, 0, 0)
    sig2 = hmac.new(key, payload2, hashlib.sha256).digest()[:6]
    r2 = lc.verify_license(lc.format_code(payload2 + sig2), key)
    assert r2["valid"] is False and "类型" in r2["reason"], r2


def test_bad_length_code_is_rejected():
    key = b"k" * 32
    r = lc.verify_license(lc.format_code(b"\x00" * 10), key)
    assert r["valid"] is False and "格式" in r["reason"], r
    r2 = lc.verify_license("乱码", key)
    assert r2["valid"] is False and "无法解析" in r2["reason"], r2


# ──────────────────────────────────────────────────────────────
# 生成 + 校验（RSA）与 .lic 端到端
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def rsa_key(tmp_path):
    os.makedirs(str(tmp_path / "rsa"), exist_ok=True)
    return lc.load_or_create_keypair(str(tmp_path / "rsa" / "私钥.pem"))


def test_rsa_license_roundtrip(rsa_key):
    code = lc.make_license(rsa_key, "rsa", level=2, expire_date="2099-01-01")
    pub = rsa_key.public_key()
    r = lc.verify_license(code, pub)
    assert r["valid"] is True and r["level"] == 2, r
    assert len(lc.parse_code(code)) == lc.PAYLOAD_SIZE + 256


def test_rsa_signature_mismatch(tmp_path, rsa_key):
    code = lc.make_license(rsa_key, "rsa")
    os.makedirs(str(tmp_path / "other"), exist_ok=True)
    other = lc.load_or_create_keypair(str(tmp_path / "other" / "私钥.pem"))
    r = lc.verify_license(code, other.public_key())
    assert r["valid"] is False and "RSA" in r["reason"], r


def test_license_file_end_to_end_hmac(tmp_path, rsa_key):
    """make_license_file 固定走 RSA 签名，所以密钥传私钥对象。
    lic 解密密钥（secret）与验签公钥是两件事，分别传。"""
    secret = b"k" * 32
    plain = lc.make_license_file(rsa_key, level=1, out_path=str(tmp_path / "plain.lic"))
    assert lc.verify_lic_file(plain, None, license_key=rsa_key.public_key())["valid"] is True
    enc = lc.make_license_file(rsa_key, out_path=str(tmp_path / "enc.lic"), secret=secret)
    assert lc.verify_lic_file(enc, secret, license_key=rsa_key.public_key())["valid"] is True
    with pytest.raises(ValueError):
        lc.verify_lic_file(enc, None)   # 加密文件不给解密密钥


def test_license_file_end_to_end_rsa(tmp_path, rsa_key):
    path = lc.make_license_file(rsa_key, level=2, out_path=str(tmp_path / "rsa.lic"))
    r = lc.verify_lic_file(path, None, license_key=rsa_key.public_key())
    assert r["valid"] is True and r["level"] == 2, r


# ──────────────────────────────────────────────────────────────
# 结构守卫：合并后的模块不应再引用旧拆分文件
# ──────────────────────────────────────────────────────────────
def test_no_stale_license_submodules_imported():
    src = open(os.path.join(lc.tool_dir(), "license_core.py"), encoding="utf-8").read()
    for old in ("license_keys", "license_payload", "license_codec",
                "license_file", "license_verify"):
        assert ("core." + old) not in src, old
    assert struct.calcsize(">BBIIHHIHH") == lc.PAYLOAD_SIZE
