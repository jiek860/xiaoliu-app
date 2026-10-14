# -*- coding: utf-8 -*-
"""v26-3.4: 记忆加密导入导出 完整版（AES-GCM）"""
import os, json, hashlib, secrets


class MemoryCrypto:
    """记忆加密导出/导入（AES-GCM）"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def export_encrypted(self, out_path, password):
        """AES-GCM 加密导出记忆

        两处按 2026-10-13 的测试结果改了：
          ① 解析不了的行原来 `except: pass` 静默跳过，返回的"条数"只数成功的
             —— 用户以为导出完整。现在报出跳过数与明细。
          ② 写不进去（盘满/权限/路径不存在）原来会把异常抛穿。现在返回错误。
        """
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
        key = hashlib.sha256(password.encode()).digest()

        try:
            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                iv = secrets.token_bytes(12)
                blob = iv + AESGCM(key).encrypt(iv, data, None)
                algo = "AES-GCM"
            except ImportError:
                # 只有"没装 cryptography"才回退 XOR（原来这里和别的情况混在一起）
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
        """AES-GCM 解密导入记忆

        ⚠️ 原来这里把"AES 解密失败"和"没装 cryptography"混在同一个 except 里，
        于是**密码输错也会掉进 XOR 回退分支** —— XOR 解出乱码，
        json.loads 抛 UnicodeDecodeError/JSONDecodeError，
        用户看到的是一句"编码错误"，完全看不出是密码不对。

        现在分开判断：
            · 没装 cryptography  -> 走 XOR 回退
            · AES 抛 InvalidTag  -> **密码不对**（明确的错误）
            · 其它               -> 报文件损坏/格式不对
        """
        raw = None
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception as e:
            return {"ok": False, "错误": "读不到加密文件：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}
        if not raw:
            return {"ok": False, "错误": "文件是空的"}

        key = hashlib.sha256(password.encode()).digest()
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            # 真的没装 cryptography -> XOR 回退（旧文件可能就是这么导的）
            try:
                plain = bytes(b ^ key[i % len(key)]
                              for i, b in enumerate(raw))
                cards = json.loads(plain)
            except Exception:
                return {"ok": False,
                        "错误": "解密失败（没装 cryptography，按 XOR 解也解不开，"
                                "可能是密码不对或文件损坏）"}
        else:
            if len(raw) <= 12:
                return {"ok": False, "错误": "文件太短，不像加密导出包"}
            iv, ct = raw[:12], raw[12:]
            try:
                cards = json.loads(AESGCM(key).decrypt(iv, ct, None))
            except Exception as e:
                # InvalidTag = 认证失败 = 密码不对（GCM 会校验完整性）
                if "InvalidTag" in type(e).__name__ or "InvalidTag" in str(e):
                    return {"ok": False,
                            "错误": "密码不对（或文件被改过）—— 解密校验没通过"}
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
