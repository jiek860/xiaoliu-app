# -*- coding: utf-8 -*-
"""v26-2.5: 浏览器会话管理（完整版）

cookie 是**登录凭证**（拿到就能以你的身份进站点），所以不能明文躺在
``data/browser_sessions/`` 里 —— 备份/迁移/崩溃包里都会顺手带走它。

2026-11-02 改：
* **落盘加密**：``AES-GCM``（密钥放在 ``data/browser_sessions/.key``，
  32 字节随机数，第一次用时生成）。文件格式 ``X6SESS1`` + nonce(12) + 密文。
* **没装 cryptography 时如实说**：仍然能存（明文 JSON），但返回值里
  ``加密: 未加密（没装 cryptography）``，并且 ``run()`` 里也标出来 ——
  不能让人以为"存进去就是加密的"。
* **兼容旧文件**：老版本写的明文 JSON 还能读（``list``/``load`` 都认）。
* **空 cookie 要报错**：原来浏览器没启动时存下一个空的 ``[]`` 并返回
  ``ok: True``,用户以为存好了，其实什么都没存。
"""
import json
import os
import secrets

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)

from core.path_safety import safe_join, safe_name

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

_MAGIC = b"X6SESS1"
_KEY_NAME = ".key"


def _aesgcm():
    """返回 AESGCM 类；没装 cryptography 返回 None（调用方降级）"""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except ImportError:
        return None


class BrowserSession:
    """保存/加载登录会话（cookie 加密持久化）"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.dir = data_path(trunk, "browser_sessions")
        self.last_error = ""

    # ------------------------------------------------------------------
    def _ensure_dir(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            return ""
        except Exception as e:
            _x6_swallowed(__name__, e, "browser session dir")
            return "建不出会话目录：%s: %s" % (type(e).__name__, str(e)[:60])

    def _path(self, name):
        clean = safe_name(name, default="")
        if not clean:
            return None
        return safe_join(self.dir, clean + ".json")

    def _key(self):
        """取/建会话加密密钥（32 字节）；失败返回 None"""
        path = os.path.join(self.dir, _KEY_NAME)
        try:
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    raw = f.read().strip()
                if raw:
                    return bytes.fromhex(raw.decode("ascii"))
            key = secrets.token_bytes(32)
            with open(path, "wb") as f:
                f.write(key.hex().encode("ascii"))
            try:
                os.chmod(path, 0o600)
            except Exception as e:
                # 这只是"尽量收紧权限"，Windows 上多半不支持，不值得报警
                _x6_swallowed(__name__, e, "chmod session key")
            return key
        except Exception as e:
            _x6_swallowed(__name__, e, "session key")
            self.last_error = "会话密钥读写失败：%s" % type(e).__name__
            return None

    # ------------------------------------------------------------------
    def _cookies_from_browser(self):
        b = (getattr(self.trunk, "modules", None) or {}).get("browser") \
            if self.trunk is not None else None
        page = getattr(b, "_page", None) if b is not None else None
        if not page:
            return []
        try:
            return list(page.context.cookies() or [])
        except Exception as e:
            _x6_swallowed(__name__, e, "read cookies")
            return []

    def save(self, name, cookies=None):
        """保存 cookie。加密写盘；空 cookie 直接拒绝（不写假文件）。"""
        if cookies is None:
            cookies = self._cookies_from_browser()
        if not isinstance(cookies, list):
            return {"ok": False, "错误": "cookies 必须是列表"}
        if not cookies:
            return {"ok": False,
                    "错误": "没拿到 cookie（浏览器可能没启动 / 还没登录）"}

        path = self._path(name)
        if not path:
            return {"ok": False, "错误": "会话名非法"}
        err = self._ensure_dir()
        if err:
            return {"ok": False, "错误": err}

        payload = json.dumps(cookies, ensure_ascii=False).encode("utf-8")
        algo = "明文（没装 cryptography）"
        try:
            AESGCM = _aesgcm()
            if AESGCM is not None:
                key = self._key()
                if key is not None:
                    nonce = secrets.token_bytes(12)
                    blob = _MAGIC + nonce + AESGCM(key).encrypt(
                        nonce, payload, _MAGIC)
                    algo = "AES-GCM"
                else:
                    blob = payload      # 取不到密钥就退明文，但要说明
            else:
                blob = payload
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, path)
        except Exception as e:
            _x6_swallowed(__name__, e, "save session")
            return {"ok": False, "错误": "写会话失败：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}

        r = {"ok": True, "文件": path, "cookie数": len(cookies), "加密": algo}
        if algo.startswith("明文"):
            r["说明"] = "没装 cryptography，这次是按明文存的（装的化会自动加密）"
        return r

    def _read(self, path):
        """读会话文件 → (cookies, 加密方式)；失败抛说明字符串"""
        with open(path, "rb") as f:
            raw = f.read()
        if not raw:
            return [], "空文件"
        if not raw.startswith(_MAGIC):
            try:                            # 旧版明文 JSON
                return json.loads(raw.decode("utf-8")), "明文（旧格式）"
            except Exception:
                return None, "文件既不是加密格式也不是 JSON"
        AESGCM = _aesgcm()
        if AESGCM is None:
            return None, "加密会话读不了（没装 cryptography）"
        key = self._key()
        if key is None:
            return None, "会话密钥读不出来"
        try:
            start = len(_MAGIC)             # 旧代码写死 12/24（把 magic 当 12 字节），
            nonce = raw[start:start + 12]   # 实际 magic 是 7 字节，读回来必然对不上
            plain = AESGCM(key).decrypt(nonce, raw[start + 12:], _MAGIC)
            return json.loads(plain.decode("utf-8")), "AES-GCM"
        except Exception:
            return None, "解密失败（密钥变了或文件被改过）"

    def load(self, name):
        """把保存的 cookie 装回浏览器"""
        path = self._path(name)
        if not path or not os.path.isfile(path):
            return {"ok": False, "错误": "会话不存在或名称非法"}
        try:
            cookies, algo = self._read(path)
        except Exception as e:
            _x6_swallowed(__name__, e, "load session")
            return {"ok": False, "错误": "读会话失败：%s" % type(e).__name__}
        if cookies is None:
            return {"ok": False, "错误": algo}

        b = (getattr(self.trunk, "modules", None) or {}).get("browser") \
            if self.trunk is not None else None
        page = getattr(b, "_page", None) if b is not None else None
        if not page:
            return {"ok": True, "cookie数": len(cookies), "加密": algo,
                    "状态": "浏览器未启动（cookie 已读出，未装入）"}
        try:
            page.context.add_cookies(cookies)
        except Exception as e:
            return {"ok": False, "错误": "装入浏览器失败：%s" % str(e)[:80],
                    "加密": algo}
        return {"ok": True, "cookie数": len(cookies), "加密": algo,
                "状态": "已加载到浏览器"}

    def list(self):
        """会话名列表（不含密钥文件）"""
        try:
            names = [f[:-5] for f in os.listdir(self.dir)
                     if f.endswith(".json") and not f.startswith(".")]
        except Exception as e:
            _x6_swallowed(__name__, e, "list sessions")
            return []
        return sorted(names)

    def delete(self, name):
        path = self._path(name)
        if not path or not os.path.isfile(path):
            return {"ok": False, "错误": "不存在或名称非法"}
        try:
            os.unlink(path)
        except Exception as e:
            _x6_swallowed(__name__, e, "delete session")
            return {"ok": False, "错误": "删不掉：%s" % str(e)[:60]}
        return {"ok": True, "名称": safe_name(name)}

    def run(self, *a):
        names = self.list()
        enc = "AES-GCM" if _aesgcm() is not None else "未加密（没装 cryptography）"
        return {"会话数": len(names), "会话列表": names, "加密方式": enc}
