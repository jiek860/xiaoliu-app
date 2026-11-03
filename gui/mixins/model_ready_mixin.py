# -*- coding: utf-8 -*-
"""回复质量兜底混入（从 chat_mixin 拆出，控制单文件行数）。

管两件事：
1. 判定"这条是不是程序兜底（没真回答）"—— `_reply_failed`；
2. 模型没配好 / 回复失败时，只给**一个**可执行的下一步提示。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None


class ModelReadyMixin:
    """90 分兜底：模型没配好 / 回复失败。"""

    _FAIL_REPLY_MARKS = ("回复时出了点问题", "（无回复）", "功能不可用",
                         "Pipeline 不可用", "服务不可用")

    def _reply_failed(self, a):
        """这条回复是"没成功"还是"模型说的话"。

        程序兜底是短句占位（见 StreamWorker / trunk.reply 的错误分支），
        真回复一般不会这么短，也不会正好命中这些话。
        """
        t = str(a or "").strip()
        if not t:
            return True
        return len(t) <= 200 and any(m in t for m in self._FAIL_REPLY_MARKS)

    def _model_ready(self):
        """配置层面能不能聊（不发网络探测）。检查本身失败时按"能聊"处理。"""
        try:
            from core import model_setup
            return bool(model_setup.check(self.trunk, probe=False).get("ready"))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
            return True

    def _append_chat_card(self, title, message, action, label):
        card = getattr(self.chat, "append_guidance_card", None)
        if callable(card):
            card(title, message, action, label)

    def _hint_model_not_ready_once(self):
        """每次会话只提醒一次，别再让用户"发了没反应"却不知道为什么。"""
        if getattr(self, "_model_hint_shown", False) or self._model_ready():
            return
        self._model_hint_shown = True
        self._append_chat_card(
            "模型还没配好",
            "现在发出去可能没人回。先花一分钟配一个模型，"
            "或在本机启动 Ollama 再试。",
            "guidance://open_model_settings", "去配置模型")

    def _after_reply_guidance(self, a):
        """失败回复只给**一个**下一步，不叠提示。"""
        try:
            if self._reply_failed(a):
                self._append_chat_card(
                    "这次没有回复成功",
                    "已经记进日志。可以直接重试；连续失败就到"
                    "「设置 → 模型」检查 Key / 地址 / 本地服务。",
                    "chat-retry://", "重试这条")
            elif not self._model_ready():
                self._append_chat_card(
                    "模型还没配好",
                    "刚才那句是程序兜底回复，不是模型回答。配好模型就能正常聊。",
                    "guidance://open_model_settings", "去配置模型")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
