# -*- coding: utf-8 -*-
"""v26-3.4: 记忆加密导入导出 完整版（AES-GCM）"""
import os, json, hashlib, secrets


class MemoryCrypto:
    """记忆加密导出/导入（AES-GCM）"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def export_encrypted(self, out_path, password):
        """AES-GCM加密导出记忆"""
        cards = []
        p = os.path.join(self.base, "data", "memory_cards.jsonl")
        if os.path.exists(p):
            for ln in open(p, encoding="utf-8"):
                try:
                    cards.append(json.loads(ln))
                except Exception:
                    pass

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = hashlib.sha256(password.encode()).digest()
            data = json.dumps(cards, ensure_ascii=False).encode("utf-8")
            iv = secrets.token_bytes(12)
            ct = AESGCM(key).encrypt(iv, data, None)
            open(out_path, "wb").write(iv + ct)
            return {"ok": True, "条数": len(cards), "加密": "AES-GCM"}
        except ImportError:
            # 回退到XOR
            key = hashlib.sha256(password.encode()).digest()
            data = json.dumps(cards, ensure_ascii=False).encode("utf-8")
            encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
            open(out_path, "wb").write(encrypted)
            return {"ok": True, "条数": len(cards), "加密": "XOR回退"}

    def import_encrypted(self, path, password):
        """AES-GCM解密导入"""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = hashlib.sha256(password.encode()).digest()
            raw = open(path, "rb").read()
            iv, ct = raw[:12], raw[12:]
            data = AESGCM(key).decrypt(iv, ct, None)
            cards = json.loads(data)
        except Exception:
            # 回退XOR
            key = hashlib.sha256(password.encode()).digest()
            raw = open(path, "rb").read()
            decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
            cards = json.loads(decrypted)

        p = os.path.join(self.base, "data", "memory_cards.jsonl")
        with open(p, "a", encoding="utf-8") as f:
            for c in cards:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        return {"ok": True, "条数": len(cards)}

    def run(self, *a):
        return {"功能": "记忆AES-GCM加密导入导出"}
