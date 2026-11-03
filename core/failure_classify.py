# -*- coding: utf-8 -*-
"""失败判定与失败分类（第 3 批：A5 基础 + 深度⑥）。

原来的 ``trunk_reply._looks_failed`` 只比对 5 个中文占位串：
``本地模型错误: ...`` / ``⚠ 连不上本地 Ollama`` 这类**短错误**会被当成
正常回复直接显示给用户；反过来只要超过 60 字就一律算成功，哪怕整段
就是报错。这里改成**双判**：

1. **结构判**：空串 / None / 明显是我们自己写的错误占位；
2. **语义判**：网络、超时、鉴权、限流、上下文溢出、拒答等标记。

判成失败后再**分类**，每类给不同策略（重试 / 压缩上下文 / 直接提示 /
保留模型原话），避免"所有失败都当网络问题"或"该重试的不重试"。

为什么拒答要保留原话
--------------------
模型拒绝是有意义的内容（比如涉及违法/隐私）。把它替换成"我再试一次？"
等于把模型的话吞掉。分类里给它 ``keep_answer=True``，只记日志不改答复。
"""
from __future__ import annotations

# 我们自己在各层写的错误占位（结构判，命中即失败）
ERROR_PREFIXES = (
    "本地模型错误",
    "（抱歉",
    "抱歉，回复时出了点问题",
    "回复时出了点问题",
    "功能不可用",
    "Pipeline 不可用",
    "服务不可用",
    "（云端模型暂时没响应",
    "（抱歉，模型暂时没响应",
    "（模型错误",
    "⚠ 连不上本地 Ollama",
    "⚠ 本地模型出错",
)

FAIL_MARKS = (
    "连不上本地 Ollama",
    "云端模型暂时没响应",
    "模型暂时没响应",
    "模型错误",
    "网络策略拒绝",
    "云端流式失败",
    "本地模型失败",
    "本地模型重试失败",
)

AUTH_MARKS = ("401", "403", "unauthorized", "invalid api key", "incorrect api key",
              "invalid_api_key", "authentication", "鉴权", "密钥无效",
              "密钥过期", "令牌", "api-key")
RATE_MARKS = ("429", "rate limit", "ratelimit", "too many requests", "quota",
              "限流", "额度不足", "余额不足")
OVERFLOW_MARKS = ("context length", "context_length_exceeded", "maximum context",
                  "prompt is too long", "exceeds the maximum", "上下文长度",
                  "超出上下文", "上下文溢出", "too many tokens")
NETWORK_MARKS = ("connection refused", "连接被拒绝", "connect timeout",
                 "max retries", "网络不可达", "getaddrinfo", "name or service",
                 "proxy", "ssl", "断网", "无法连接", "连不上")
TIMEOUT_MARKS = ("timed out", "timeout", "read time out", "readtimeout",
                 "超时", "卡住", "没有响应", "no response")
REFUSAL_MARKS = ("抱歉，我无法", "抱歉,我无法", "我不能帮助", "我不能提供",
                 "无法提供", "作为人工智能", "as an ai", "i can't help",
                 "i cannot help", "i'm unable to", "i am unable to")

# 各类失败的处置策略
PLANS = {
    "empty": {"retry": True,
              "hint": "（这次没生成出内容，我再试一次？）"},
    "network": {"retry": True,
                "hint": "（网络好像断了，没能连上模型服务。检查下网络/代理再来一次？）"},
    "timeout": {"retry": True,
                "hint": "（模型等了太久没吐字，我先停了。要不要重试一次？）"},
    "auth": {"retry": False,
             "hint": "（API Key 好像无效或过期了，去「设置 → 模型」检查一下密钥？）"},
    "rate_limit": {"retry": False,
                   "hint": "（云端限流了，过一会儿再问我一次就行。）"},
    "context_overflow": {"retry": True, "shrink_context": True,
                         "hint": "（对话太长了，我把早前内容压缩了一下，再试一次？）"},
    # 拒答是模型的正常输出，不能吞掉
    "refusal": {"keep_answer": True},
    "unknown": {},
}

KINDS = tuple(PLANS)


def _lower(text):
    return str(text or "").lower()


def looks_failed(answer) -> bool:
    """这次回复是不是"其实没成功"（空串 / 错误占位 / 明确失败标记）。"""
    a = "" if answer is None else str(answer).strip()
    if not a:
        return True
    if a.startswith(ERROR_PREFIXES):
        return True
    return any(m in a for m in FAIL_MARKS)


def _kind_of(text, aggressive=False):
    """按标记分类；aggressive=True 时把异常文本里的弱信号也算上。"""
    low = _lower(text)
    if not low.strip():
        return "empty"
    for kind, marks in (("auth", AUTH_MARKS), ("rate_limit", RATE_MARKS),
                        ("context_overflow", OVERFLOW_MARKS),
                        ("network", NETWORK_MARKS),
                        ("timeout", TIMEOUT_MARKS),
                        ("refusal", REFUSAL_MARKS)):
        if any(m in low or m in text for m in marks):
            return kind
    if aggressive and ("refused" in low or "econn" in low):
        return "network"
    return ""


def classify(answer=None, error=None) -> str:
    """返回失败类别；不是失败返回空串。

    注意：**只对"已经判成失败"的回复做语义分类**，避免把用户正常问
    "怎么配 API Key" 的回答误判成鉴权失败并替换掉。
    例外是**拒答**：明确的拒绝话术本身有意义，要单独识别出来（调用方
    按 ``keep_answer`` 保留模型原话，不替换成兜底话）。
    """
    err = "" if error is None else str(error).strip()
    if err:
        kind = _kind_of(err, aggressive=True)
        return kind or "unknown"
    text = "" if answer is None else str(answer).strip()
    if not text:
        return "empty"
    if len(text) <= 160 and any(m in _lower(text) or m in text
                                for m in REFUSAL_MARKS):
        return "refusal"
    if not looks_failed(text):
        return ""
    return _kind_of(text, aggressive=False) or "unknown"


def plan(kind) -> dict:
    return dict(PLANS.get(str(kind or "")) or {})


def hint(kind) -> str:
    return str(plan(kind).get("hint") or "")


def should_retry(kind) -> bool:
    return bool(plan(kind).get("retry"))


def should_shrink_context(kind) -> bool:
    return bool(plan(kind).get("shrink_context"))


def keep_answer(kind) -> bool:
    return bool(plan(kind).get("keep_answer"))
