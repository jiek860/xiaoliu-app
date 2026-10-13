# -*- coding: utf-8 -*-
"""浏览器操作 v2.1 - 打开网页 + 点击 + 输入 + 截图 + 滚动 + 历史

v2.1 把这条线接活（2026-10-13）：
  · 之前：playwright 包装了、代码写了 11 个动作，但 chromium 二进制没下载，
    而且没人告诉 playwright 去哪找 -> 一启动就 "Executable doesn't exist"；
    也没有任何地方 trunk.call("browser", ...)，聊天和工具调用都到不了它。
  · 现在：浏览器装在**程序文件夹**的 data/browsers（_ensure_browser_path），
    并补了 try_handle()/run() 作为工具入口，接进 tool_caller。
"""
import os, re, time
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
        self._pw = None          # sync_playwright 的句柄，退出时要收
        self._browser = None

    def _ensure_browser_path(self):
        """让 playwright 到**程序文件夹**里找浏览器

        `playwright install` 把浏览器装到 PLAYWRIGHT_BROWSERS_PATH 指向的目录。
        装的时候指到了 <base>/data/browsers，运行时**必须指同一个目录** ——
        否则它会去默认的 %LOCALAPPDATA%\\ms-playwright 找，然后报
        "Executable doesn't exist"（这正是这个模块此前一启动就失败的原因：
        包装了、代码写了，但浏览器没下载，也没人告诉它去哪找）。

        外部已设过这个变量就尊重外部设置。
        """
        p = os.path.join(self.base, "data", "browsers")
        if os.path.isdir(p) and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = p
        return os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""

    def _start(self, headless=True):
        """启动 playwright + chromium（只启一次，之后复用同一个 page）"""
        self._ensure_browser_path()
        from playwright.sync_api import sync_playwright
        if not self._page:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=headless)
            self._page = self._browser.new_page()
        return self._page

    @safe
    def open(self, url, headless=True):
        """打开网页"""
        try:
            page = self._start(headless=headless)
            page.goto(url, timeout=15000)
            self.history.append({"url": url, "时间": time.time()})
            if len(self.history) > 20:
                self.history = self.history[-20:]
            return {"ok": True, "标题": page.title()}
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

    # ---------- 统一入口（工具调用 / 聊天用）----------
    def try_handle(self, text):
        """把一句话解析成浏览器动作并执行

        为什么是"收一句话自己解析"，而不是 (action, **kwargs)：
        tool_caller 分发工具时只传**第一个参数值** ——
            arg_val = list(args.values())[0] if args else query
            self.trunk.call(info["mod"], info["method"], arg_val)
        所以工具入口收不到第 2 个参数。computer_controller.try_handle
        也是这个形状。多参数在那边是同一个约束。
        """
        t = str(text or "").strip()
        if not t:
            return {"ok": False, "错误": "没给指令"}

        # 摘出目标地址。优先级：完整 URL（http/https/file）→ 域名 → 本地路径。
        #
        # 踩过的坑：原来只认 (?:[\w\-]+\.)+[A-Za-z]{2,6}，于是
        #   "打开 file:///E:/x/_browser_test.html"
        # 里的 file:// 不被识别，反倒匹配到尾巴上的 "_browser_test.html"，
        # 补成 https://_browser_test.html -> ERR_NAME_NOT_RESOLVED，
        # 而且这一失败会把 playwright 的 sync 状态带坏，后续调用报出
        # 一个误导性的 "Playwright Sync API inside the asyncio loop"。
        # 现在：先认完整 URL，域名的 TLD 用白名单（免得 .html/.txt 被当域名）。
        u = ""
        m = re.search(r"(?:https?|file)://[^\s，。]+", t)
        if m:
            u = m.group(0)
        else:
            m = re.search(r"((?:[\w\-]+\.)+(?:com|cn|net|org|io|dev|edu|gov|"
                          r"top|xyz|info|me|tv|cc|co)(?:/[^\s，。]*)?)", t, re.I)
            if m:
                u = "https://" + m.group(1)
            else:
                m = re.search(r"([A-Za-z]:\\[^\s，。]+)", t)
                if m:
                    u = "file:///" + m.group(1).replace("\\", "/")
        if u and re.search(r"打开|访问|去|上|看看|浏览|读取|打开网页", t):
            return self.open(u)

        # 读页面文字
        if re.search(r"读(取)?(页面|网页)?(文字|内容|文本)|页面(文字|内容)|正文|get_text", t):
            return self.get_text()

        # 截图
        if re.search(r"截图|截屏|快照|screenshot", t):
            return self.screenshot()

        # 滚动
        if re.search(r"滚动|下滑|翻页|scroll", t):
            direction = "up" if re.search(r"上|up", t) else "down"
            n = re.search(r"(\d+)", t)
            return self.scroll(direction, int(n.group(1)) if n else 500)

        # 点击
        m = re.search(r"点击|点一下|单击|click\s*[：:]?\s*(.+)", t)
        if m:
            sel = t.split("点击")[-1].split("单击")[-1] if ("点击" in t or "单击" in t) else m.group(1)
            sel = re.sub(r"^\s*(元素|按钮|链接)?\s*", "", sel).strip()
            if sel:
                return self.click(sel)

        # 填表：{"selector": "value", ...} 直接给 JSON
        m = re.search(r"\{.*\}", t)
        if m and re.search(r"填表|表单|填入|fill_form", t):
            try:
                import json as _json
                return self.fill_form(_json.loads(m.group(0)))
            except Exception as e:
                return {"错误": "填表内容不是合法 JSON: " + str(e)[:50]}

        # 输入：在 <selector> 输入 <text>
        m = re.search(r"(?:在|往)\s*(\S+)\s*(?:里|中)?\s*(?:输入|填|打)\s*(.+)$", t)
        if m:
            return self.type_text(m.group(1).strip(), m.group(2).strip())
        m = re.search(r"(?:输入|填)\s*(.+?)\s*(?:到|进)\s*(\S+)\s*$", t)
        if m:
            return self.type_text(m.group(2).strip(), m.group(1).strip())

        # 开新标签
        if m and re.search(r"新标签|新窗口|new_tab", t):
            return self.new_tab(m.group(0))

        return {"ok": False, "错误": "没听懂这条浏览器指令: " + t[:40],
                "可用": "打开<网址> / 读页面文字 / 截图 / 滚动 / 点击<选择器> / "
                        "在<选择器>输入<内容> / 填表<JSON>"}

    def run(self, text=""):
        if not text or not str(text).strip():
            return {"状态": "浏览器就绪",
                    "能力": "打开/点击/输入/读文字/截图/滚动/登录/批量填表/新标签",
                    "浏览器目录": self._ensure_browser_path()}
        return self.try_handle(text)
