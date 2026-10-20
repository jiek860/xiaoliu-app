# -*- coding: utf-8 -*-
"""Browser：页面操作、DOM 感知、指令解析和 Chromium 状态。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.browser import Browser  # noqa: E402


class _FakeMouse:
    def __init__(self):
        self.wheels = []

    def wheel(self, x, y):
        self.wheels.append((x, y))


class _FakeLocator:
    def __init__(self, page=None):
        self.page = page
        self.first = self

    def inner_text(self):
        return "文本"

    def inner_html(self):
        return "<div>文本</div>"

    def count(self):
        return 1

    def press(self, key):
        return None

    def set_input_files(self, path):
        return None


class _FakePage:
    def __init__(self):
        self.url = "https://example.com"
        self.mouse = _FakeMouse()
        self.filled = []
        self.clicked = []
        self.context = self
        self._new_page = None

    def goto(self, url, timeout=0):
        self.url = url

    def title(self):
        return "Example"

    def click(self, selector):
        self.clicked.append(selector)

    def fill(self, selector, text):
        self.filled.append((selector, text))

    def content(self):
        return "<html>body</html>"

    def text_content(self, selector):
        return "selector text"

    def screenshot(self, path):
        self.shot = path

    def locator(self, selector):
        return _FakeLocator(self)

    def wait_for_selector(self, selector, timeout=0):
        return None

    def new_page(self):
        return _FakePage()


class _FakeTrunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {}
        self.modules = {}

    def _log(self, *_a, **_k):
        return None


def _browser(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    b = Browser(_FakeTrunk(tmp_path))
    page = _FakePage()

    def start(headless=True):
        b._page = page
        return page

    monkeypatch.setattr(b, "_start", start)
    b._page = page
    return b, page


def test_browser_page_actions(tmp_path, monkeypatch):
    b, page = _browser(tmp_path, monkeypatch)
    try:
        assert b.open("https://a.test")["ok"] is True
        assert b.click("button")["ok"] is True
        assert b.type_text("input", "hi")["ok"] is True
        assert b.get_text()["文字"]
        assert b.get_text("div")["文字"] == "selector text"
        assert b.screenshot()["ok"] is True
        assert b.scroll("up", 100)["ok"] is True
        assert page.mouse.wheels[-1] == (0, -100)
        assert b.wait(0.01)["ok"] is True
        assert b.fill_form({"a": 1})["填写数"] == 1
        assert b.new_tab("https://b.test")["ok"] is True
        assert b.get_history()["历史"]
    finally:
        b.shutdown()


def test_browser_dom_helpers(tmp_path, monkeypatch):
    b, _page = _browser(tmp_path, monkeypatch)
    try:
        assert b.current_info()["started"] is True
        assert b.get_dom()["ok"] is True
        assert b.get_dom("div")["ok"] is True
        assert b.exists("div")["exists"] is True
        assert b.wait_for_selector("div")["ok"] is True
        assert b.press("input")["ok"] is True
        assert b.upload_file("input", "x.txt")["ok"] is True
    finally:
        b.shutdown()


def test_browser_unstarted_guards(tmp_path, monkeypatch):
    b, _page = _browser(tmp_path, monkeypatch)
    b._page = None
    try:
        assert b.click("x")["错误"]
        assert b.type_text("x", "y")["错误"]
        assert b.get_text()["错误"]
        assert b.screenshot()["错误"]
        assert b.scroll()["错误"]
        assert b.fill_form({})["错误"]
        assert b.current_info()["started"] is False
    finally:
        b.shutdown()


def test_browser_try_handle_branches(tmp_path, monkeypatch):
    b, _page = _browser(tmp_path, monkeypatch)
    try:
        assert b.try_handle("")["ok"] is False
        assert b.try_handle("打开 https://example.com")["ok"] is True
        assert "文字" in b.try_handle("读取页面文字")
        assert b.try_handle("截图")["ok"] is True
        assert b.try_handle("向下滚动 200")["ok"] is True
        assert b.try_handle("点击 button")["ok"] is True
        assert b.try_handle("在 input 输入 hello")["ok"] is True
        assert b.try_handle("输入 world 到 input")["ok"] is True
        assert b.try_handle("填表 {\"a\":1}")["ok"] is True
        assert b.try_handle("没听懂")["ok"] is False
        assert b.run()["状态"].startswith("浏览器")
    finally:
        b.shutdown()


def test_chromium_info_installed_and_missing(tmp_path, monkeypatch):
    b, _page = _browser(tmp_path, monkeypatch)
    try:
        assert b.chromium_info()["已装"] is False
        d = tmp_path / "data" / "browsers" / "chromium-1"
        d.mkdir(parents=True)
        (d / "chrome.exe").write_bytes(b"x")
        info = b.chromium_info()
        assert info["已装"] is True
        assert info["文件数"] >= 1
    finally:
        b.shutdown()