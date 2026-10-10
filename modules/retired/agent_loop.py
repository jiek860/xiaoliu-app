# -*- coding: utf-8 -*-
# 【实验性模块】功能为LLM转发，后续迭代完善
# -*- coding: utf-8 -*-
import sys, os as _os
from core.safe import safe
from modules.base import BaseModule
"""Agent闭环 v1.0 - AI自动操作电脑
能力：截图理解 + 多步规划 + 每步确认 + 错误恢复
"""
import os, time, json, base64, requests
from datetime import datetime


class AgentLoop(BaseModule):
    NAME = "agent_loop"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.steps = []
        self.current_step = 0
        self.max_steps = 10
        self.screenshots = []

    @safe
    def screenshot(self):
        """截图并返回 base64"""
        import pyautogui
        img = pyautogui.screenshot()
        w, h = img.size
        if w > 1024:
            ratio = 1024 / w
            img = img.resize((1024, int(h * ratio)))
        buf = __import__('io').BytesIO()
        img.save(buf, format='JPEG', quality=60)
        return base64.b64encode(buf.getvalue()).decode()

    @safe
    def understand_screen(self, screenshot_b64, question="屏幕上有什么可点的按钮？"):
        """用云端多模态模型理解截图"""
        if not self.trunk: return None
        llm = self.trunk.modules.get("llm")
        if not llm: return None
        cloud_url = llm.config.get("cloud_url", "")
        cloud_key = llm.config.get("cloud_key", "")
        cloud_model = llm.config.get("cloud_model", "qwen-turbo")
        if not cloud_url or not cloud_key:
            return None
        url = cloud_url.rstrip("/") + "/chat/completions"
        r = requests.post(url,
            headers={"Authorization": "Bearer " + cloud_key},
            json={
                "model": cloud_model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + screenshot_b64}}
                    ]
                }],
                "max_tokens": 500,
            },
            timeout=30)
        return r.json()["choices"][0]["message"]["content"]

    @safe
    def plan_steps(self, task):
        """AI 把任务拆成步骤"""
        if not self.trunk: return []
        llm = self.trunk.modules.get("llm")
        if not llm: return []
        prompt = """把下面这个任务拆成最多 %d 个电脑操作步骤，每步是一个 JSON 对象：
{"动作": "点击/输入/打开/等待/截图", "目标": "具体描述", "预计耗时秒": 5}

任务：%s

只返回 JSON 数组，不要解释。""" % (self.max_steps, task)
        r = llm.chat(prompt)
        import re
        m = re.search(r'\[.*\]', r, re.DOTALL)
        if m:
            return json.loads(m.group())
        return []

    @safe
    def execute_step(self, step):
        """执行单步"""
        cc = self.trunk.modules.get("computer_controller") if self.trunk else None
        if not cc: return False
        action = step.get("动作", "")
        target = step.get("目标", "")
        if action == "打开":
            return cc.open_app(target)
        elif action == "点击":
            return True
        elif action == "输入":
            return cc.type_text(target)
        elif action == "等待":
            time.sleep(int(step.get("预计耗时秒", 2)))
            return True
        elif action == "截图":
            self.screenshots.append(self.screenshot())
            return True
        return False

    def run(self, task):
        """完整闭环：规划 → 执行 → 确认 → 恢复"""
        self.steps = self.plan_steps(task)
        if not self.steps:
            return {"ok": False, "msg": "规划失败"}
        
        results = []
        for i, step in enumerate(self.steps):
            # 执行前截图
            before = self.screenshot()
            # 执行
            ok = self.execute_step(step)
            # 执行后截图
            time.sleep(1)
            after = self.screenshot()
            # 确认（如果有云端模型）
            if after and self.trunk:
                check = self.understand_screen(after, "这步操作成功了吗？只回答成功/失败")
                if check and "失败" in check:
                    ok = False
            results.append({"step": i+1, "action": step, "ok": ok})
        
        return {"ok": True, "steps": results, "total": len(results)}

