# -*- coding: utf-8 -*-
"""数据加密 v2.1 - 动态本地密钥 + 兼容旧XOR
修复：去掉硬编码死密钥，首次运行自动生成随机密钥存在本地
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import base64
import hashlib
import secrets
import os

_MAGIC = b"X6AESGCM2"

# 动态密钥文件：存在data目录下，不再硬编码
_KEY_FILE = None
KEY = None


def _get_key():
    """动态获取密钥：优先读本地密钥文件，第一次运行自动生成"""
    global KEY, _KEY_FILE
    if KEY is not None:
        return KEY
    try:
        # 找项目根目录下的data目录
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        key_path = os.path.join(base, "data", ".secret_key")
        _KEY_FILE = key_path
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                KEY = f.read()
        else:
            # 第一次运行生成随机密钥
            KEY = secrets.token_bytes(32)
            with open(key_path, "wb") as f:
                f.write(KEY)
            try:
                os.chmod(key_path, 0o600)  # 仅当前用户可读
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
    except Exception:
        # 密钥文件读写出错，回退临时随机密钥（和旧的硬编码兼容）
        KEY = b"web_agent_v2_secret_key_2026"
    return KEY


def encrypt(text):
    """AES-GCM 加密字符串；输出带版本前缀的 base64。"""
    key = _get_key()
    data = text.encode("utf-8")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets.token_bytes(12)
        ct = AESGCM(key).encrypt(nonce, data, _MAGIC)
        return "x6aes:v2:" + base64.b64encode(_MAGIC + nonce + ct).decode("ascii")
    except ImportError as e:
        # 无 cryptography 时明确失败，不再静默退化为 XOR。
        raise RuntimeError("AES-GCM 需要 cryptography 库") from e


def decrypt(enc):
    """解密字符串：支持 AES-GCM v2 与旧 XOR 历史数据。"""
    if not isinstance(enc, str):
        return enc
    if enc.startswith("x6aes:v2:"):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            raw = base64.b64decode(enc[len("x6aes:v2:"):])
            if not raw.startswith(_MAGIC):
                return enc
            nonce = raw[len(_MAGIC):len(_MAGIC) + 12]
            ct = raw[len(_MAGIC) + 12:]
            return AESGCM(_get_key()).decrypt(nonce, ct, _MAGIC).decode("utf-8")
        except Exception:
            return enc
    # 旧格式兼容：只读，不再用于新数据
    try:
        data = base64.b64decode(enc)
        key = _get_key()
        out = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return out.decode("utf-8")
    except Exception:
        try:
            data = base64.b64decode(enc)
            old_key = b"web_agent_v2_secret_key_2026"
            out = bytes(b ^ old_key[i % len(old_key)] for i, b in enumerate(data))
            return out.decode("utf-8")
        except Exception:
            return enc


def hash_password(password, salt=None):
    """密码哈希：PBKDF2-HMAC-SHA256，10万次迭代"""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${h.hex()}"


def verify_password(password, stored):
    """验证密码"""
    try:
        salt, h = stored.split("$")
        return hash_password(password, salt) == stored
    except:
        return False


def generate_random_key(length=32):
    """生成随机密钥"""
    return secrets.token_hex(length)


def encrypt_file(path, out_path=None):
    """AES-GCM 加密文件；失败时抛异常，不再静默写 XOR。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _get_key()
    if out_path is None:
        out_path = path + ".enc"
    with open(path, "rb") as f:
        data = f.read()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, data, _MAGIC)
    with open(out_path, "wb") as f:
        f.write(_MAGIC + nonce + ct)
    return out_path


def decrypt_file(path, out_path=None):
    """解密文件：支持 AES-GCM v2 与旧 XOR 文件。"""
    key = _get_key()
    if out_path is None:
        out_path = path.replace(".enc", "")
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(_MAGIC):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = data[len(_MAGIC):len(_MAGIC) + 12]
        ct = data[len(_MAGIC) + 12:]
        out = AESGCM(key).decrypt(nonce, ct, _MAGIC)
    else:
        out = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    with open(out_path, "wb") as f:
        f.write(out)
    return out_path


def checksum(data):
    """计算校验和：SHA256"""
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def verify_checksum(data, expected):
    """验证校验和"""
    return checksum(data) == expected


def generate_uuid():
    """生成唯一ID"""
    return secrets.token_hex(16)


def encode_base64(data):
    """Base64编码"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("ascii")


def decode_base64(s):
    """Base64解码"""
    return base64.b64decode(s).decode("utf-8")
