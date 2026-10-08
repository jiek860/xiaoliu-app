# -*- coding: utf-8 -*-
"""模块/插件 RSA 签名验签

签名对象：文件内容的 sha256 十六进制字符串（小写）
信任根    ：core/公钥.pem —— 与更新包签名共用同一把发布公钥
发版端    ：tools/sign_modules.py 用密钥库里的私钥给 modules_repo/manifest.json 签名
用户端    ：plugin_market 下载/安装模块前先验签，验不过不落盘
"""
import os


class PluginSigner:
    """签名与验签"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self.pub_key_path = os.path.join(self.base, "core", "公钥.pem")

    # ---------- 摘要 ----------
    def calc_hash(self, file_path):
        """计算文件 SHA256（十六进制小写）"""
        from core.release_sign import file_sha256
        return file_sha256(file_path)

    @staticmethod
    def calc_hash_bytes(data):
        """计算内存数据的 SHA256（十六进制小写）"""
        import hashlib
        return hashlib.sha256(data).hexdigest()

    # ---------- 验签 ----------
    def load_pubkey(self):
        try:
            from cryptography.hazmat.primitives import serialization
            with open(self.pub_key_path, "rb") as f:
                return serialization.load_pem_public_key(f.read())
        except Exception:
            return None

    def verify_hash(self, sha_hex, signature):
        """验证 sha256 十六进制串的 RSA 签名"""
        pub = self.load_pubkey()
        if pub is None or not signature:
            return False
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            pub.verify(bytes.fromhex(signature), str(sha_hex).encode(),
                       padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception:
            return False

    def verify_plugin(self, plugin_path, signature):
        """验签磁盘上的模块文件"""
        try:
            return self.verify_hash(self.calc_hash(plugin_path), signature)
        except Exception:
            return False

    def verify_bytes(self, data, signature):
        """验签内存中的模块内容（下载后落盘前调用）"""
        try:
            return self.verify_hash(self.calc_hash_bytes(data), signature)
        except Exception:
            return False

    # ---------- 发版端签名 ----------
    def sign_hash(self, sha_hex, private_key):
        """给 sha256 十六进制串签名，返回十六进制签名字符串"""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        return private_key.sign(str(sha_hex).encode(),
                                padding.PKCS1v15(), hashes.SHA256()).hex()

    def run(self, *a):
        return {"公钥存在": os.path.exists(self.pub_key_path),
                "公钥路径": self.pub_key_path}
