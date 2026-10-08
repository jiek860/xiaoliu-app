# -*- coding: utf-8 -*-
"""v26-2.5: 浏览器会话管理 完整版"""
import os, json


class BrowserSession:
    """保存/加载登录会话，cookie持久化"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.dir = os.path.join(self.base, "data", "browser_sessions")
        os.makedirs(self.dir, exist_ok=True)

    def save(self, name, cookies=None):
        """保存cookie到文件"""
        if cookies is None:
            # 从browser模块拿cookie
            b = self.trunk.modules.get("browser") if self.trunk else None
            if b and hasattr(b, "_page") and b._page:
                try:
                    cookies = b._page.context.cookies()
                except Exception:
                    cookies = []
            else:
                cookies = []
        path = os.path.join(self.dir, name + ".json")
        tmp = path + ".tmp"
        json.dump(cookies, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, path)
        return {"ok": True, "文件": path, "cookie数": len(cookies)}

    def load(self, name):
        """加载cookie到browser"""
        path = os.path.join(self.dir, name + ".json")
        if not os.path.exists(path):
            return {"错误": "会话不存在"}
        cookies = json.load(open(path, encoding="utf-8"))
        b = self.trunk.modules.get("browser") if self.trunk else None
        if b and hasattr(b, "_page") and b._page:
            try:
                b._page.context.add_cookies(cookies)
                return {"ok": True, "cookie数": len(cookies), "状态": "已加载到浏览器"}
            except Exception as e:
                return {"错误": str(e)[:80]}
        return {"ok": True, "cookie数": len(cookies), "状态": "浏览器未启动"}

    def list(self):
        return [f[:-5] for f in os.listdir(self.dir) if f.endswith(".json")]

    def delete(self, name):
        path = os.path.join(self.dir, name + ".json")
        if os.path.exists(path):
            os.unlink(path)
            return {"ok": True}
        return {"错误": "不存在"}

    def run(self, *a):
        return {"会话数": len(self.list()), "会话列表": self.list()}
