# -*- coding: utf-8 -*-
"""更新包 manifest 签名 / 验签（发版端与用户端共用，避免两边算法漂移）

签名内容 = 规范化 JSON（按 path 排序）：
    {"files": [[path, sha256], ...], "version": "..."}

任一文件的内容、路径或版本号被改动，验签都会失败。

发版端：build_release.py 生成 manifest → sign_release.py 填入 signature
用户端：modules/installed/auto_updater.py 的 check_update() 先验签再判断版本
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import hashlib
import json
import os


def file_sha256(path: str) -> str:
    """文件 SHA256（十六进制小写）"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_payload(manifest: dict) -> bytes:
    """把 manifest 归一化成待签名字节串"""
    files = sorted((str(f.get("path", "")), str(f.get("sha256", "")))
                   for f in (manifest or {}).get("files", []))
    data = {"version": str((manifest or {}).get("version", "")), "files": files}
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict, private_key) -> str:
    """用私钥给 manifest 签名，返回十六进制签名字符串"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    sig = private_key.sign(manifest_payload(manifest),
                           padding.PKCS1v15(), hashes.SHA256())
    return sig.hex()


def verify_manifest(manifest: dict, public_key) -> bool:
    """验签 manifest。signature 缺失、格式错误或公钥不匹配都返回 False"""
    sig = (manifest or {}).get("signature") or ""
    if not sig or public_key is None:
        return False
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        public_key.verify(bytes.fromhex(sig), manifest_payload(manifest),
                          padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


def load_release_pubkey(base_dir: str):
    """加载【更新包签名】公钥。core/公钥.pem；缺失返回 None"""
    try:
        from cryptography.hazmat.primitives import serialization
        with open(os.path.join(base_dir, "core", "公钥.pem"), "rb") as f:
            return serialization.load_pem_public_key(f.read())
    except Exception:
        return None


def load_signing_privatekey():
    """发版端读取更新签名私钥。

    查找顺序：环境变量 X6_SIGN_KEY → 密钥库（X6_KEY_VAULT 或 ~/.xiao6-keys）。
    私钥绝不放在项目目录里。
    """
    from cryptography.hazmat.primitives import serialization
    from core.license_core import vault_dir
    env_key = os.environ.get("X6_SIGN_KEY")
    vault = vault_dir()
    cands = []
    if env_key:
        cands.append(env_key)
    cands.append(os.path.join(vault, "RSA私钥-更新签名.pem"))
    for p in cands:
        try:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return serialization.load_pem_private_key(f.read(), password=None)
        except Exception as e:
            _x6_swallowed(__name__, e)
            continue
    raise RuntimeError(
        "找不到更新签名私钥，已查找:\n"
        "    1) 环境变量 X6_SIGN_KEY = %s\n"
        "    2) %s\n"
        "  · 私钥不要放进项目目录。\n"
        "  · 如果刚改过 X6_KEY_VAULT 或刚 setx，请关掉重开一个命令行窗口再试\n"
        "    （环境变量只对新开的进程生效）。"
        % (env_key if env_key else "(未设置)", cands[-1]))
