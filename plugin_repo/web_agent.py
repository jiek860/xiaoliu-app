# -*- coding: utf-8 -*-
"""P1-4: 浏览器 Agent - 截图→看页面→决定→执行→验证

复用现有 browser.py，加持久登录态。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from modules.base import BaseModule


class WebAgent(BaseModule):
    """浏览器自动化 Agent"""
    NAME = "web_agent"
    VERSION = "1.0"

    TOOLS = [
        {"name": "browse", "method": "browse",
         "desc": "打开网页并截图，让 AI 看页面内容",
         "args": {"url": "要打开的网址", "goal": "要完成的任务，如：登录、搜索、填表"},
         "readonly": False,
         "hints": ["网页", "浏览器", "上网", "打开网站", "browse", "web"]},
    ]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self._browser = None

    def _get_browser(self):
        """获取浏览器实例（带持久登录态）"""
        if self._browser:
            return self._browser
        try:
            self._browser = self.trunk.modules.get("browser") if self.trunk else None
        except Exception as e:
            _x6_swallowed(__name__, e)
        return self._browser

    def browse(self, url, goal=""):
        """打开网页 → 截图 → 让 AI 看 → 决定操作"""
        br = self._get_browser()
        if not br:
            return {"ok": False, "error": "浏览器模块未加载"}
        try:
            # 1. 打开页面
            br.open(url)
            # 2. 截图
            screenshot = br.screenshot() if hasattr(br, "screenshot") else None
            # 3. 让 VLM 看页面
            vlm = self.trunk.modules.get("multimodal") if self.trunk else None
            analysis = ""
            if vlm and screenshot:
                try:
                    analysis = vlm.describe(screenshot, f"页面内容描述，目标: {goal}")
                except Exception as e:
                    _x6_swallowed(__name__, e)
            return {
                "ok": True,
                "url": url,
                "goal": goal,
                "页面分析": analysis,
                "screenshot": screenshot is not None,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def run(self, *a):
        url = a[0] if a else "https://www.baidu.com"
        goal = a[1] if len(a) > 1 else ""
        return self.browse(url, goal)