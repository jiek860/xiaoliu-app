# -*- coding: utf-8 -*-
"""浏览器操作 v2.0 - 打开网页 + 点击 + 输入 + 截图 + 滚动 + 历史"""
import os, time
from core.safe import safe
from modules.base import BaseModule


class Browser(BaseModule):
    NAME = "browser"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.history = []
        self._page = None

    @safe
    def open(self, url):
        """打开网页"""
        try:
            from playwright.sync_api import sync_playwright
            if not self._page:
                p = sync_playwright().start()
                browser = p.chromium.launch(headless=True)
                self._page = browser.new_page()
            self._page.goto(url, timeout=15000)
            self.history.append({"url": url, "时间": time.time()})
            if len(self.history) > 20:
                self.history = self.history[-20:]
            return {"ok": True, "标题": self._page.title()}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def click(self, selector):
        """点击元素"""
        if not self._page:
            return {"错误": "先打开网页"}
        try:
            self._page.click(selector)
            return {"ok": True}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def type_text(self, selector, text):
        """输入文字"""
        if not self._page:
            return {"错误": "先打开网页"}
        try:
            self._page.fill(selector, text)
            return {"ok": True}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def get_text(self, selector=None):
        """获取页面文字"""
        if not self._page:
            return {"错误": "先打开网页"}
        try:
            if selector:
                return {"文字": self._page.text_content(selector)[:500]}
            return {"文字": self._page.content()[:1000]}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def screenshot(self, path=None):
        """截图"""
        if not self._page:
            return {"错误": "先打开网页"}
        try:
            if not path:
                path = os.path.join(self.base, "data", "browser_screenshot.png")
            self._page.screenshot(path=path)
            return {"ok": True, "截图": path}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def scroll(self, direction="down", pixels=500):
        """滚动页面"""
        if not self._page:
            return {"错误": "先打开网页"}
        try:
            delta = pixels if direction == "down" else -pixels
            self._page.mouse.wheel(0, delta)
            return {"ok": True}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def wait(self, seconds=2):
        """等待"""
        time.sleep(seconds)
        return {"ok": True}

    @safe
    def get_history(self, count=10):
        """获取浏览历史"""
        return {"历史": self.history[-count:]}

    # P1-05: 浏览器自动化增强
    @safe
    def login_and_keep(self, url, selector_user, selector_pwd, username, password):
        """登录并保持会话"""
        try:
            self.open(url)
            self.type_text(selector_user, username)
            self.type_text(selector_pwd, password)
            self.click("button[type=submit]")
            time.sleep(2)
            return {"ok": True, "标题": self._page.title()}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def fill_form(self, fields):
        """批量填表: fields = {selector: value}"""
        if not self._page:
            return {"错误": "先打开网页"}
        try:
            for sel, val in fields.items():
                self._page.fill(sel, str(val))
            return {"ok": True, "填写数": len(fields)}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def new_tab(self, url):
        """开新标签"""
        if not self._page:
            return self.open(url)
        try:
            page = self._page.context.new_page()
            page.goto(url, timeout=15000)
            self._page = page
            return {"ok": True, "标题": page.title()}
        except Exception as e:
            return {"错误": str(e)[:80]}

    def run(self, *args):
        return {"状态": "浏览器就绪", "能力": "打开/点击/输入/截图/滚动/登录/批量填表"}
