# -*- coding: utf-8 -*-
"""v26-3.4: 记忆加密导入导出（AES-GCM）

导出格式 v2：
    b"X6MEM2" + salt(16) + nonce(12) + ciphertext
    密钥 = PBKDF2-HMAC-SHA256(password, salt, 200000)
导入仍兼容旧版 sha256(password) + nonce + AES-GCM 和旧 XOR 文件。
"""
import base64
import hashlib
import json
import os
import secrets

_V2_MAGIC = b"X6MEM2"
_V2_ITER = 200_000
_V2_SALT = 16


class MemoryCrypto:
    """记忆加密导出/导入（AES-GCM）"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def export_encrypted(self, out_path, password):
        """AES-GCM 加密导出记忆。"""
        cards = []
        bad_lines = []
        p = os.path.join(self.base, "data", "memory_cards.jsonl")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for i, ln in enumerate(f, 1):
                    if not ln.strip():
                        continue
                    try:
                        cards.append(json.loads(ln))
                    except Exception as e:
                        bad_lines.append("第 %d 行（%s）"
                                         % (i, type(e).__name__))

        data = json.dumps(cards, ensure_ascii=False).encode("utf-8")
        try:
            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                salt = secrets.token_bytes(_V2_SALT)
                nonce = secrets.token_bytes(12)
                key = hashlib.pbkdf2_hmac(
                    "sha256", password.encode("utf-8"), salt,
                    _V2_ITER, dklen=32)
                ct = AESGCM(key).encrypt(nonce, data, _V2_MAGIC)
                blob = _V2_MAGIC + salt + nonce + ct
                algo = "AES-GCM + PBKDF2"
            except ImportError:
                # 只有确实没装 cryptography 才允许旧 XOR，并明确标记。
                key = hashlib.sha256(password.encode()).digest()
                blob = bytes(b ^ key[i % len(key)]
                             for i, b in enumerate(data))
                algo = "XOR回退（没装 cryptography，强度弱得多）"
            with open(out_path, "wb") as f:
                f.write(blob)
        except Exception as e:
            return {"ok": False,
                    "错误": "写不出加密文件：%s: %s"
                            % (type(e).__name__, str(e)[:80]),
                    "路径": str(out_path)[:120]}

        r = {"ok": True, "条数": len(cards), "加密": algo}
        if bad_lines:
            r["跳过"] = len(bad_lines)
            r["跳过明细"] = bad_lines[:5]
            r["提示"] = ("有 %d 行记忆读不出来、没进导出包：%s"
                         % (len(bad_lines), "、".join(bad_lines[:3])))
        return r

    def import_encrypted(self, path, password):
        """解密导入记忆；新格式优先，旧格式兼容。"""
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception as e:
            return {"ok": False, "错误": "读不到加密文件：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}
        if not raw:
            return {"ok": False, "错误": "文件是空的"}

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            key = hashlib.sha256(password.encode()).digest()
            try:
                plain = bytes(b ^ key[i % len(key)]
                              for i, b in enumerate(raw))
                cards = json.loads(plain)
            except Exception:
                return {"ok": False,
                        "错误": "解密失败（没装 cryptography，按 XOR 解也解不开，"
                                "可能是密码不对或文件损坏）"}
        else:
            if raw.startswith(_V2_MAGIC):
                if len(raw) <= len(_V2_MAGIC) + _V2_SALT + 12:
                    return {"ok": False, "错误": "加密文件不完整"}
                off = len(_V2_MAGIC)
                salt = raw[off:off + _V2_SALT]
                off += _V2_SALT
                nonce = raw[off:off + 12]
                ct = raw[off + 12:]
                key = hashlib.pbkdf2_hmac(
                    "sha256", password.encode("utf-8"), salt,
                    _V2_ITER, dklen=32)
                aad = _V2_MAGIC
            else:
                # 兼容旧版：sha256(password) + 12 字节 nonce + AES-GCM
                if len(raw) <= 12:
                    return {"ok": False, "错误": "文件太短，不像加密导出包"}
                nonce, ct = raw[:12], raw[12:]
                key = hashlib.sha256(password.encode()).digest()
                aad = None
            try:
                cards = json.loads(AESGCM(key).decrypt(nonce, ct, aad))
            except Exception as e:
                if "InvalidTag" in type(e).__name__ or "InvalidTag" in str(e):
                    return {"ok": False,
                            "错误": "密码不对（或文件被改过） 解密校验没通过"}
                return {"ok": False,
                        "错误": "解密失败：%s: %s"
                                % (type(e).__name__, str(e)[:60])}

        if not isinstance(cards, list):
            return {"ok": False, "错误": "解开的内容不是记忆卡列表"}

        p = os.path.join(self.base, "data", "memory_cards.jsonl")
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                for c in cards:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")
        except Exception as e:
            return {"ok": False, "错误": "写入记忆库失败：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "条数": len(cards)}

    def run(self, *a):
        return {"功能": "记忆AES-GCM加密导入导出"}
