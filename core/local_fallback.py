# -*- coding: utf-8 -*-
"""P2-02: 端侧小模型兜底 - Ollama不可用时的简单回答"""


class LocalFallback:
    """Ollama挂了用简单规则回答"""
    def __init__(self, trunk=None):
        self.trunk = trunk

    def reply(self, text):
        """简单规则回答"""
        text = text.strip()
        if not text:
            return "你好，我在。"
        if "你好" in text or "hi" in text.lower():
            return "你好呀！Ollama现在没启动，我用简单模式回答你。启动Ollama就能正常聊天啦。"
        if "谢谢" in text:
            return "不客气~"
        if "?" in text or "？" in text:
            return "这个问题我现在没法深度回答，启动Ollama加载本地模型后就能正常聊啦。"
        return "Ollama现在没启动，我只能简单回复。启动Ollama后就能正常对话了。"

    def run(self, *a):
        return {"状态": "兜底模式就绪", "说明": "Ollama不可用时启用"}
