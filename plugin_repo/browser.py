# -*- coding: utf-8 -*-
"""浏览器操作 v2.1 - 打开网页 + 点击 + 输入 + 截图 + 滚动 + 历史

v2.1 把这条线接活（2026-10-13）：
  · 之前：playwright 包装了、代码写了 11 个动作，但 chromium 二进制没下载，
    而且没人告诉 playwright 去哪找 -> 一启动就 "Executable doesn't exist"；
    也没有任何地方 trunk.call("browser", ...)，聊天和工具调用都到不了它。
  · 现在：浏览器装在**程序文件夹**的 data/browsers（_ensure_browser_path），
    并补了 try_handle()/run() 作为工具入口，接进 tool_caller。
"""
import atexit
import concurrent.futures
import os, re, threading, time
from core.safe import safe
from core.plugin_errors import error_result as _error_result
from modules.base import BaseModule

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def _err(message, code="PLUGIN_BAD_INPUT"):
    """历史 ``{"错误": ...}`` 的统一出口（标准 6.1 结构化错误）"""
    return _error_result(code, str(message)[:300], module="browser")



def _browser_thread(fn):
    """把 Playwright 调用固定到单独线程，避免跨线程操作 page。"""
    def wrapper(self, *args, **kwargs):
        self._ensure_thread_runtime()
        if getattr(self._local, "inside", False):
            return fn(self, *args, **kwargs)
        future = self._executor.submit(
            self._invoke_in_browser_thread, fn, args, kwargs)
        try:
            return future.result(timeout=self._call_timeout)
        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": "浏览器操作超时（线程安全保护）"}
    wrapper.__name__ = getattr(fn, "__name__", "browser_op")
    wrapper.__doc__ = getattr(fn, "__doc__", "")
    return wrapper


class Browser(BaseModule):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "browser"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.history = []
        self._page = None
        self._pw = None
        self._browser = None
        self._local = threading.local()
        self._call_timeout = 45
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="x6-browser")
        atexit.register(self.shutdown)

    def _ensure_thread_runtime(self):
        if not hasattr(self, "_local"):
            self._local = threading.local()
        if not hasattr(self, "_call_timeout"):
            self._call_timeout = 45
        if not hasattr(self, "_executor"):
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="x6-browser")
            atexit.register(self.shutdown)

    def _invoke_in_browser_thread(self, fn, args, kwargs):
        self._local.inside = True
        try:
            return fn(self, *args, **kwargs)
        finally:
            self._local.inside = False

    def shutdown(self):
        """关闭浏览器和专属线程；重复调用安全。"""
        if not hasattr(self, "_executor"):
            return
        def _close():
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception as e:  # 静默是故意的 - 退出清理失败不阻塞程序
                _x6_swallowed(__name__, e, "best-effort fallback")
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception as e:  # 静默是故意的 - 退出清理失败不阻塞程序
                _x6_swallowed(__name__, e, "best-effort fallback")
            self._page = self._browser = self._pw = None
        try:
            self._executor.submit(_close).result(timeout=8)
        except Exception as e:  # 静默是故意的 - 退出清理失败不阻塞程序
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            self._executor.shutdown(wait=False)
        except Exception as e:  # 静默是故意的 - 退出清理失败不阻塞程序
            _x6_swallowed(__name__, e, "best-effort fallback")

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
        if os.path.isdir(p) and not self.env("PLAYWRIGHT_BROWSERS_PATH"):
            self.set_env("PLAYWRIGHT_BROWSERS_PATH", p)
        return self.env("PLAYWRIGHT_BROWSERS_PATH") or ""

    def chromium_info(self):
        """chromium 装了没 / 缺什么 / 怎么装（#7：第一次用才提示下载）

        为什么要这个
        ------------
        以前没装 chromium 时，用户看到的是 playwright 那句原始报错被截到 80 字：

            Executable doesn't exist at ...\\data\\browsers\\chromium-1243\\chrome-w

        既看不出是"浏览器没下载"，也不知道该怎么办。
        实际这个浏览器有 700 MB，**本来就不该随程序分发** ——
        对方需要浏览器功能时再下就行。所以缺它属于**正常状态**，
        不该报成错误，而该给一句能照着做的提示。

        判定方式：看 data/browsers 下有没有 chromium-* 目录
        （playwright 把版本号编在目录名里，所以用前缀匹配）。
        """
        import glob as _g
        d = os.path.join(self.base, "data", "browsers")

        def _size(p):
            n = sz = 0
            for r, _ds, fs in os.walk(p):
                for f in fs:
                    try:
                        sz += os.path.getsize(os.path.join(r, f))
                        n += 1
                    # 静默是故意的：统计体积时跳过读不到的单个文件，
                    # 少算一个不影响"大概多大"
                    except Exception as e:
                        _x6_swallowed(__name__, e, "best-effort fallback")
            return n, round(sz / 1024.0 / 1024, 1)

        dirs = _g.glob(os.path.join(d, "chromium-*"))
        dirs = [x for x in dirs if "headless" not in os.path.basename(x)]
        if dirs:
            n, mb = _size(dirs[0])
            return {"已装": True, "路径": dirs[0], "文件数": n, "MB": mb}

        return {
            "已装": False,
            "路径": d,
            "说明": "浏览器内核（Chromium）还没下载 —— 这是正常的：它约 700 MB，"
                    "不随程序分发，**第一次要用浏览器功能时再下**。",
            "怎么装": "py -3 -m playwright install chromium",
            "注意": "必须让 PLAYWRIGHT_BROWSERS_PATH 指向 %s "
                    "（本模块已自动设置；手动装时也要指同一个目录，"
                    "否则它会装到 %%LOCALAPPDATA%%\\ms-playwright，"
                    "而运行时找不到）" % d,
            "大小": "约 700 MB（含 headless shell 与 ffmpeg）",
            "装完": "回到「电脑控制 → 浏览器」重试即可",
        }

    def _start(self, headless=True):
        """启动 playwright + chromium（只启一次，之后复用同一个 page）"""
        self._ensure_browser_path()
        # 先查内核在不在，给一句能照着做的提示，而不是甩 playwright 的原始报错
        info = self.chromium_info()
        if not info.get("已装"):
            # 命令放最前面 —— open() 会把错误截到 80 字，
            # 原来写"浏览器内核没下载（约 700 MB…）。装法：py -3 -m playwright
            # install chromium" 时，命令正好被切掉，用户没法复制。
            raise RuntimeError(
                "先运行：py -3 -m playwright install chromium"
                "（浏览器内核约 700 MB，未随程序分发）")
        from playwright.sync_api import sync_playwright
        if not self._page:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=headless)
            self._page = self._browser.new_page()
        return self._page

    @safe
    @_browser_thread
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
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
    def click(self, selector):
        """点击元素"""
        if not self._page:
            return _err("先打开网页", "PLUGIN_BAD_INPUT")
        try:
            self._page.click(selector)
            return {"ok": True}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
    def type_text(self, selector, text):
        """输入文字"""
        if not self._page:
            return _err("先打开网页", "PLUGIN_BAD_INPUT")
        try:
            self._page.fill(selector, text)
            return {"ok": True}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
    def get_text(self, selector=None):
        """获取页面文字"""
        if not self._page:
            return _err("先打开网页", "PLUGIN_BAD_INPUT")
        try:
            if selector:
                return {"文字": self._page.text_content(selector)[:500]}
            return {"文字": self._page.content()[:1000]}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
    def screenshot(self, path=None):
        """截图"""
        if not self._page:
            return _err("先打开网页", "PLUGIN_BAD_INPUT")
        try:
            if not path:
                path = os.path.join(self.base, "data", "browser_screenshot.png")
            self._page.screenshot(path=path)
            return {"ok": True, "截图": path}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
    def scroll(self, direction="down", pixels=500):
        """滚动页面"""
        if not self._page:
            return _err("先打开网页", "PLUGIN_BAD_INPUT")
        try:
            delta = pixels if direction == "down" else -pixels
            self._page.mouse.wheel(0, delta)
            return {"ok": True}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
    def back(self):
        """返回上一页"""
        if not self._page:
            return _err("先打开网页", "PLUGIN_BAD_INPUT")
        try:
            self._page.go_back()
            time.sleep(0.5)
            return {"ok": True}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
    def list_interactables(self, limit=40):
        """列出页面上可交互元素，供 Agent 做 DOM-first 决策。"""
        if not self._page:
            return _err("先打开网页", "PLUGIN_BAD_INPUT")
        try:
            items = self._page.eval_on_selector_all(
                "button, input, textarea, select, a[href]",
                """els => els.slice(0, %d).map((el, i) => ({
                    index: i,
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    id: el.id || '',
                    name: el.getAttribute('name') || '',
                    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80),
                    href: el.getAttribute('href') || ''
                }))""" % int(limit))
            return {"ok": True, "元素": items}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
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
    @_browser_thread
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
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
    def fill_form(self, fields):
        """批量填表: fields = {selector: value}"""
        if not self._page:
            return _err("先打开网页", "PLUGIN_BAD_INPUT")
        try:
            for sel, val in fields.items():
                self._page.fill(sel, str(val))
            return {"ok": True, "填写数": len(fields)}
        except Exception as e:
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    @safe
    @_browser_thread
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
            return _err(str(e)[:80], "PLUGIN_INTERNAL_ERROR")

    # ---------- 统一入口（工具调用 / 聊天用）----------
    # ---------- DOM 感知（供电脑 Agent 使用）----------
    @_browser_thread
    def current_info(self):
        """返回当前页面 URL/标题；未启动浏览器时安全返回空状态。"""
        if not self._page:
            return {"ok": True, "started": False, "url": "", "title": ""}
        try:
            return {"ok": True, "started": True,
                    "url": self._page.url or "",
                    "title": self._page.title() or ""}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200],
                    "url": "", "title": ""}

    @safe
    @_browser_thread
    def get_dom(self, selector=None):
        """读取当前页面文本和可访问性友好的 HTML 摘要。"""
        try:
            page = self._start(headless=False)
            if selector:
                el = page.locator(selector).first
                return {"ok": True, "selector": selector,
                        "text": (el.inner_text() or "")[:20000],
                        "html": (el.inner_html() or "")[:30000]}
            return {"ok": True, "url": page.url, "title": page.title(),
                    "text": (page.locator("body").inner_text() or "")[:30000],
                    "html": (page.content() or "")[:50000]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    @safe
    @_browser_thread
    def exists(self, selector):
        try:
            page = self._start(headless=False)
            return {"ok": True, "exists": page.locator(selector).count() > 0}
        except Exception as e:
            return {"ok": False, "exists": False, "error": str(e)[:200]}

    @safe
    @_browser_thread
    def wait_for_selector(self, selector, timeout=5000):
        try:
            page = self._start(headless=False)
            page.wait_for_selector(selector, timeout=int(timeout))
            return {"ok": True, "selector": selector}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    @safe
    @_browser_thread
    def press(self, selector, key="Enter"):
        try:
            page = self._start(headless=False)
            page.locator(selector).first.press(str(key))
            return {"ok": True, "selector": selector, "key": str(key)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    @safe
    @_browser_thread
    def upload_file(self, selector, path):
        try:
            page = self._start(headless=False)
            page.locator(selector).first.set_input_files(str(path))
            return {"ok": True, "selector": selector, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

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
                return _err("填表内容不是合法 JSON: " + str(e)[:50], "PLUGIN_BAD_INPUT")

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
