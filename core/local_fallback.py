# -*- coding: utf-8 -*-
"""P2-02: 端侧小模型兜底（完整版）

什么时候用
----------
本地模型（Ollama）没起来、或者云端全挂了时，聊天不能变成一片空白。
``core/trunk_reply.py::_local_fallback_reply`` 会调 :meth:`LocalFallback.reply`
拿一句人话（「启动 Ollama 就能正常聊」），而不是让用户对着空气发呆。

分级（2026-11-02 补）
--------------------
原来只有「你好 / 谢谢 / 问号 / 其它」四条，用户说「我难受」「帮我看看」
得到的还是那句「启动 Ollama」。现在按 *意图* 分级：

    问候 greeting / 感谢 thanks / 告别 bye / 求助 help /
    情绪低落 low / 道歉 sorry / 提问 question / 闲聊 chitchat / 兜底 fallback

可选小模型
----------
配 ``config["fallback_model"]``（例如 ``qwen2.5:1.5b``）且 LLM 模块可用时，
先让模型用一句话回答；失败/超时立刻退回规则，**规则永远是最后一道**。
不配就完全不碰模型（默认行为不变）。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

# 规则表：顺序有意义 —— 先匹配更具体的意图，最后才是兜底。
# (分级, 关键词列表, 回复模板)；模板里的 {topic} 会用用户原话填。
_RULES = [
    ("greeting", ("你好", "您好", "hi", "hello", "在吗", "在么", "早上好",
                  "晚上好", "早安", "晚安"),
     "你好呀！模型这会儿没连上，我先用简单模式陪你。"
     "启动 Ollama（或检查网络）之后就能正常聊啦。"),
    ("thanks", ("谢谢", "感谢", "多谢", "辛苦了", "麻烦你了"),
     "不客气～能帮上就好。"),
    ("bye", ("再见", "拜拜", "先这样", "回头聊", "下次聊", "bye"),
     "好，那我先待着。想到我就叫我一声。"),
    ("help", ("怎么", "如何", "帮我", "能不能", "可以帮", "教我", "设置",
              "报错", "为什么", "咋办", "怎么办"),
     "这个我暂时没法深入回答（模型没连上）。"
     "你可以先在「设置 → 模型」里把模型配好，或者把问题说细一点，"
     "我再试试用简单模式帮你理一理。"),
    ("low", ("累", "难过", "难受", "烦", "崩溃", "焦虑", "压力", "孤独",
             "失眠", "失望", "不开心", "想哭"),
     "我在呢，先别急着扛着。要不要慢慢跟我说说发生了什么？"
     "（模型临时没连上，但这句话是我真心回的。）"),
    ("sorry", ("对不起", "抱歉", "不好意思"),
     "没事的，不用道歉。"),
    ("question", ("?", "？"),
     "这个问题我现在没法深度回答，等 Ollama 把本地模型加载起来就能正常聊啦。"),
]
_EMPTY_REPLY = "你好，我在。"
_FALLBACK_REPLY = ("模型这会儿没连上，我只能简单回复。"
                   "启动 Ollama（或恢复网络）之后就能正常对话了。")


class LocalFallback:
    """Ollama 不可用时的规则兜底（可选接一个小模型）"""

    def __init__(self, trunk=None):
        self.trunk = trunk

    # ------------------------------------------------------------------
    @staticmethod
    def classify(text):
        """返回分级名（见模块 docstring）；空输入返回 ``empty``"""
        raw = "" if text is None else str(text)
        low = raw.lower()
        if not raw.strip():
            return "empty"
        for name, keywords, _tpl in _RULES:
            if any(k.lower() in low for k in keywords):
                return name
        return "fallback"

    def _rule_reply(self, name):
        for rule_name, _kw, tpl in _RULES:
            if rule_name == name:
                return tpl
        return _FALLBACK_REPLY if name != "empty" else _EMPTY_REPLY

    def _try_small_model(self, text):
        """可选小模型：配置了 fallback_model 且 LLM 可用时才尝试。

        这个分支是**尽力而为**：模型慢/报错/没配都直接返回 None，
        由规则兜住（兜底模块自己不能成为新的故障源）。
        """
        trunk = self.trunk
        if trunk is None:
            return None
        config = getattr(trunk, "config", {}) or {}
        model = str(config.get("fallback_model") or "").strip()
        if not model:
            return None
        modules = getattr(trunk, "modules", None) or {}
        llm = modules.get("llm")
        if llm is None or not hasattr(llm, "chat"):
            return None
        prompt = ("请用一两句口语化的话回复下面这句，"
                  "不要解释你是 AI：\n%s" % str(text)[:200])
        try:
            # 真实 LLMClient 的形参是 force_model；老接口/假 LLM 只收 message。
            # 逐级退让 —— 兜底模块自己绝不能变成新的故障源。
            try:
                ans = llm.chat(prompt, force_model=model)
            except TypeError:
                try:
                    ans = llm.chat(prompt, model=model)
                except TypeError:
                    ans = llm.chat(prompt)
        except Exception as e:
            _x6_swallowed(__name__, e, "fallback model")
            return None
        text = str(ans or "").strip()
        return text[:300] if text else None

    # ------------------------------------------------------------------
    def reply(self, text, use_model=None):
        """返回一句回复（调用方 ``trunk_reply`` 只认字符串）。

        ``use_model``：None = 看配置（有 ``fallback_model`` 才试）；
        True = 试着用模型；False = 只用规则。
        """
        name = self.classify(text)
        want_model = bool(use_model) if use_model is not None else True
        if want_model and name != "empty":
            got = self._try_small_model(text)
            if got:
                return got
        return self._rule_reply(name)

    def answer(self, text, use_model=None):
        """结构化版本：给日志/自检用，能看出这次是哪一档、有没有走模型。"""
        name = self.classify(text)
        return {"分级": name, "回复": self.reply(text, use_model=use_model)}

    def run(self, *a):
        return {"状态": "兜底模式就绪",
                "分级": [name for name, _kw, _tpl in _RULES] + ["fallback"],
                "说明": "Ollama 或云端不可用时启用；配 fallback_model 可接小模型"}
