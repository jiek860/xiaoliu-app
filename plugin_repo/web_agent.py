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
import os


class WebAgent(BaseModule):
    """浏览器自动化 Agent"""
    NAME = "web_agent"
    VERSION = "1.0"

    TOOLS = [
        {"name": "browse", "method": "browse",
         "desc": "打开网页并截图，让 AI 看页面内容",
         "args": {"url": "要打开的网址", "goal": "要完成的任务，如：登录、搜索、填表"},
         "readonly": False,
         "hints": ["网页", "浏览器", "上网", "打开网站", "browse", "web"],
         "contract": {
             "params": {"url": {"type": "string"}, "goal": {"type": "string"}},
             "returns": {"type": "object"},
             "errors": ["PLUGIN_NOT_AVAILABLE"],
             "side_effects": ["ui_control", "network"],
             "description": "打开网页并截图，让 AI 看页面内容",
             "not_responsible": ["不负责持久登录态", "不负责验证码识别"]
         }},
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

    def browse(self, url, goal="", max_steps=5):
        """打开网页 → 截图 → VLM 分析 → 决定动作 → 执行 → 再看

        DOM-first 动作循环：
        1. 打开页面
        2. 截图 + VLM 分析
        3. VLM 决定下一步动作（点击哪个选择器/输入什么）
        4. 执行动作
        5. 重复直到完成或达到最大步数
        """
        br = self._get_browser()
        if not br:
            return {"ok": False, "error": "浏览器模块未加载"}

        history = []
        analysis = ""
        screenshot = None
        try:
            # 1. 打开页面
            br.open(url)
            history.append("打开 %s" % url)

            # 2. 最多走 max_steps 步
            for step in range(max_steps):
                # 截图
                screenshot = br.screenshot() if hasattr(br, "screenshot") else None

                # 让 VLM 看页面
                vlm = self.trunk.modules.get("multimodal") if self.trunk else None
                analysis = ""
                if vlm and screenshot and isinstance(screenshot, dict) and screenshot.get("ok"):
                    try:
                        img_path = screenshot.get("截图", "")
                        if img_path and os.path.exists(img_path):
                            r = vlm.describe_image(img_path)
                            if isinstance(r, dict):
                                analysis = r.get("描述", "")
                            else:
                                analysis = str(r)
                    except Exception as e:
                        _x6_swallowed(__name__, e)

                # DOM-first：优先把可交互元素和页面文字交给 LLM，
                # VLM 截图描述只作为补充，不让模型只凭截图猜选择器。
                dom_context = ""
                try:
                    if hasattr(br, "list_interactables"):
                        dom = br.list_interactables()
                        if isinstance(dom, dict) and dom.get("元素"):
                            import json as _json
                            dom_context = _json.dumps(
                                dom["元素"], ensure_ascii=False)[:1500]
                    if hasattr(br, "get_text"):
                        gt = br.get_text()
                        if isinstance(gt, dict) and gt.get("文字"):
                            dom_context += "\n页面文字: " + str(gt["文字"])[:800]
                except Exception as e:
                    _x6_swallowed(__name__, e, "web_agent dom context failed")

                history.append("第%d步: %s" % (step + 1, analysis[:100]))
                if dom_context:
                    history.append("DOM: " + dom_context[:120])

                # 如果没有 VLM，就只返回第一步的结果
                if not vlm:
                    break

                # 让 LLM 决定下一步动作
                if goal:
                    llm = self.trunk.modules.get("llm") if self.trunk else None
                    if llm:
                        prompt = (
                            "你是浏览器自动化助手。\n"
                            "目标: %s\n"
                            "当前页面描述: %s\n"
                            "可交互元素 DOM 摘要: %s\n"
                            "浏览器支持的动作: click(选择器), type(选择器, 文字), scroll(), back()\n"
                            "请输出下一步动作，格式:\n"
                            "ACTION: click('button.submit')\n"
                            "或 ACTION: type('#search', 'hello world')\n"
                            "如果已经完成，输出 ACTION: done\n"
                            "只输出 ACTION: 开头的那一行。"
                            % (goal, analysis[:500], dom_context[:1500])
                        )
                        try:
                            action_text = llm.chat(prompt)
                            if "ACTION:" in action_text:
                                action_line = [l for l in action_text.split("\n") if "ACTION:" in l][0]
                                action = action_line.split("ACTION:")[1].strip()
                                history.append("执行: %s" % action[:80])

                                # 执行动作，并检查返回值
                                action_ok = True
                                action_err = ""
                                if action.startswith("done"):
                                    break
                                elif action.startswith("click("):
                                    selector = action[action.index("(")+1:action.rindex(")")].strip("'\"")
                                    r = br.click(selector)
                                    if isinstance(r, dict) and r.get("错误"):
                                        action_ok = False
                                        action_err = r.get("错误")
                                elif action.startswith("type("):
                                    parts = action[action.index("(")+1:action.rindex(")")].split(",", 1)
                                    if len(parts) == 2:
                                        sel = parts[0].strip().strip("'\"")
                                        txt = parts[1].strip().strip("'\"")
                                        r = br.type_text(sel, txt)
                                        if isinstance(r, dict) and r.get("错误"):
                                            action_ok = False
                                            action_err = r.get("错误")
                                elif action.startswith("scroll()"):
                                    r = br.scroll()
                                    if isinstance(r, dict) and r.get("错误"):
                                        action_ok = False
                                        action_err = r.get("错误")
                                elif action.startswith("back()"):
                                    # browser 没有 back() 方法就跳过
                                    if hasattr(br, "back"):
                                        r = br.back()
                                        if isinstance(r, dict) and r.get("错误"):
                                            action_ok = False
                                            action_err = r.get("错误")
                                    else:
                                        action_ok = False
                                        action_err = "浏览器不支持 back()"

                                # 动作失败就返回，不要静默 break
                                if not action_ok:
                                    history.append("动作失败: %s" % action_err)
                                    return {
                                        "ok": False,
                                        "error": "动作执行失败: %s" % action_err,
                                        "页面分析": analysis,
                                        "步骤历史": history,
                                    }

                                # 等一下让页面加载
                                if hasattr(br, "wait"):
                                    br.wait(0.5)
                        except Exception as e:
                            _x6_swallowed(__name__, e, "web_agent action failed")
                            return {
                                "ok": False,
                                "error": "动作执行异常: %s" % str(e)[:100],
                                "步骤历史": history,
                            }
                else:
                    # 没有 goal，就只分析第一步
                    break

            return {
                "ok": True,
                "url": url,
                "goal": goal,
                "页面分析": analysis,
                "步骤历史": history,
                "screenshot": screenshot is not None,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:200], "历史": history}

    def run(self, *a):
        url = a[0] if a else "https://www.baidu.com"
        goal = a[1] if len(a) > 1 else ""
        return self.browse(url, goal)
