# -*- coding: utf-8 -*-
"""模块/插件 RSA 签名验签（完整版）

签名对象：文件内容的 sha256 十六进制字符串（小写）
信任根    ：core/公钥.pem —— 与更新包签名共用同一把发布公钥
发版端    ：tools/sign_modules.py 用密钥库里的私钥给 modules_repo/manifest.json 签名
用户端    ：plugin_market 下载/安装模块前先验签，验不过不落盘

2026-11-02 补
------------
原来验签失败只有 ``False`` 一个布尔值 —— "为什么没过"完全不可查：
没公钥？签名格式不对？内容被改？三种情况对排查来说天差地别
（前两种是环境问题，第三种是**安全问题**）。

现在每个 ``verify_*`` 都配一个 ``*_detail`` 版本，返回
``{"ok": bool, "原因": 人话, ...}``；布尔版本保留（老调用方不用改）。
"""
import hashlib
import os

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class PluginSigner:
    """签名与验签"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self.pub_key_path = os.path.join(self.base, "core", "公钥.pem")
        self.last_error = ""

    # ---------- 摘要 ----------
    def calc_hash(self, file_path):
        """计算文件 SHA256（十六进制小写）"""
        from core.release_sign import file_sha256
        return file_sha256(file_path)

    @staticmethod
    def calc_hash_bytes(data):
        """计算内存数据的 SHA256（十六进制小写）"""
        return hashlib.sha256(data).hexdigest()

    # ---------- 验签 ----------
    def load_pubkey(self):
        """加载发布公钥；失败返回 None，并把原因写进 ``last_error``"""
        self.last_error = ""
        path = self.pub_key_path
        if not os.path.isfile(path):
            self.last_error = "没有公钥文件（%s）" % path
            return None
        try:
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.last_error = "没装 cryptography，验不了签"
            return None
        try:
            with open(path, "rb") as f:
                return serialization.load_pem_public_key(f.read())
        except Exception as e:
            _x6_swallowed(__name__, e, "load pubkey")
            self.last_error = "公钥读不出来：%s: %s" % (
                type(e).__name__, str(e)[:60])
            return None

    def verify_hash_detail(self, sha_hex, signature):
        """验签并给出原因（``ok`` 为 False 时 ``原因`` 一定有值）"""
        pub = self.load_pubkey()
        if pub is None:
            return {"ok": False, "原因": self.last_error or "公钥不可用"}
        if not signature:
            return {"ok": False, "原因": "没有签名（签名参数为空）"}
        try:
            signature_bytes = bytes.fromhex(str(signature))
        except (TypeError, ValueError):
            return {"ok": False, "原因": "签名不是合法的十六进制串"}
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError:
            return {"ok": False, "原因": "没装 cryptography，验不了签"}
        try:
            pub.verify(signature_bytes, str(sha_hex).encode(),
                       padding.PKCS1v15(), hashes.SHA256())
        except Exception as e:
            _x6_swallowed(__name__, e, "verify signature")
            return {"ok": False,
                    "原因": "验签不通过（内容被改过，或签名不是这把公钥签的）"}
        return {"ok": True, "原因": ""}

    def verify_hash(self, sha_hex, signature):
        """验证 sha256 十六进制串的 RSA 签名（布尔版）"""
        return bool(self.verify_hash_detail(sha_hex, signature).get("ok"))

    def verify_plugin_detail(self, plugin_path, signature):
        """验签磁盘上的模块文件（带原因与摘要）"""
        if not os.path.isfile(plugin_path):
            return {"ok": False, "原因": "文件不存在：%s" % str(plugin_path)[:120]}
        try:
            sha_hex = self.calc_hash(plugin_path)
        except Exception as e:
            _x6_swallowed(__name__, e, "hash plugin")
            return {"ok": False, "原因": "算不出文件摘要：%s" % type(e).__name__}
        r = self.verify_hash_detail(sha_hex, signature)
        r.update({"文件": plugin_path, "sha256": sha_hex})
        return r

    def verify_plugin(self, plugin_path, signature):
        """验签磁盘上的模块文件（布尔版，老调用方用）"""
        return bool(self.verify_plugin_detail(plugin_path, signature).get("ok"))

    def verify_bytes_detail(self, data, signature):
        """验签内存中的模块内容（下载后落盘前调用）"""
        try:
            sha_hex = self.calc_hash_bytes(data)
        except Exception as e:
            _x6_swallowed(__name__, e, "hash bytes")
            return {"ok": False, "原因": "算不出内容摘要：%s" % type(e).__name__}
        r = self.verify_hash_detail(sha_hex, signature)
        r["sha256"] = sha_hex
        return r

    def verify_bytes(self, data, signature):
        """验签内存中的模块内容（布尔版）"""
        return bool(self.verify_bytes_detail(data, signature).get("ok"))

    # ---------- 发版端签名 ----------
    def sign_hash(self, sha_hex, private_key):
        """给 sha256 十六进制串签名，返回十六进制签名字符串"""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        return private_key.sign(str(sha_hex).encode(),
                                padding.PKCS1v15(), hashes.SHA256()).hex()

    def sign_file(self, file_path, private_key):
        """给一个文件签名（先算 sha256 再签），返回十六进制签名"""
        return self.sign_hash(self.calc_hash(file_path), private_key)

    def run(self, *a):
        has_key = os.path.isfile(self.pub_key_path)
        return {"公钥存在": has_key, "公钥路径": self.pub_key_path,
                "可用": bool(self.load_pubkey()) if has_key else False,
                "说明": "验签失败时用 verify_*_detail() 能拿到具体原因"}
