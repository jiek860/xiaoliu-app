# -*- coding: utf-8 -*-
"""license_core 公共兼容门面。

实现已拆分到：
  license_keys / license_codec / license_payload / license_file / license_verify
所有旧导入路径保持不变。
"""
from __future__ import annotations

from core.license_keys import (
    ACT_PUB_FILE, PRIV_FILE, PUB_FILE, SECRET_FILE, activation_pubkey_path,
    find_license_secret, get_machine_code, load_activation_pubkey,
    load_or_create_keypair, load_or_create_secret, pubkey_pem, tool_dir,
    vault_dir, _identity_int, _machine_int, _read_secret_file, _ih,
)
from core.license_codec import (
    FLAG_DEVICES, FLAG_EMAIL, FLAG_EXPIRE, FLAG_MACHINE, GROUP, LEVEL_NAMES,
    PREFIX, _B32_ALPH, _b32dec, _b32enc, flags_desc, format_code, parse_code,
)
from core.license_payload import (
    EPOCH, PAYLOAD_SIZE, _date_str_from_days, _days_from_date_str,
    _decode_payload, _encode_payload,
)
from core.license_file import (
    _lic_aes_key, _write_lic_plain, decrypt_lic, encrypt_lic, read_lic_file,
    write_lic_file,
)
from core.license_verify import (
    make_license, make_license_file, verify_lic_file, verify_license,
)

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
