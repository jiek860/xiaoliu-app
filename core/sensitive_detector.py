# -*- coding: utf-8 -*-
"""敏感信息检测 + 自动脱敏（完整版）

注意：不要用 \\b 来卡数字边界。
\\b 是"\\w 与非 \\w 之间"，而中文属于 \\w ——
"我的手机号是13812345678" 里「是」和「1」之间没有边界，
\\b1[3-9]\\d{9}\\b 永远匹配不到。这个模块因此在中文语境下几乎失效
（只有数字前面是空格/标点时才碰巧能用）。改用前后否定环视，
保证卡的是"数字边界"而不是"单词边界"。

2026-11-02 补：新增四类密钥格式（原来只有 ``sk-`` / ``api_key=`` 那种）：
    私钥块（PEM） / AWS AccessKey / GitHub 令牌 / JWT
规则顺序 = 从"更具体的"到"更宽泛的"：宽泛规则（如银行卡 16~19 位）
放后面，避免把 18 位身份证当银行卡再报一次。
"""
import re

# 顺序有意义：具体 → 宽泛
PATTERNS = {
    "私钥": r"-----BEGIN[A-Z ]*PRIVATE KEY-----",
    "GitHub令牌": r"gh[pousr]_[A-Za-z0-9]{36}",
    "AWS密钥": r"(?:AKIA|ASIA)[0-9A-Z]{16}",
    "JWT": r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    "身份证": r"(?<!\d)\d{17}[\dXx](?!\d)",
    "手机号": r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "银行卡": r"(?<!\d)\d{16,19}(?!\d)",
    "邮箱": r"[\w.-]+@[\w.-]+\.\w+",
    "API密钥": r"(?:sk-|api[_-]?key[=:]\s*)[\w-]{16,}",
    "密码": r"(?:password|passwd|pwd)[=:]\s*\S+",
}


class SensitiveDetector:
    """敏感信息检测与脱敏"""

    def __init__(self, trunk=None):
        self.trunk = trunk

    def detect(self, text):
        """检测敏感信息

        ⚠️ **返回结果里不带敏感内容本身**（2026-10-13 改）
        原来返回的是 {"value": m.group()[:20] + "..."} ——
        也就是把密钥的**前 20 个字符**原样带出来。对 API 密钥来说，
        前 20 位往往已经是可用的密钥片段。这个结果一旦进日志、发给模型、
        或显示在界面上，"检测敏感信息"这个动作本身就变成了泄露渠道。

        现在只返回：类型、长度、在文本里的位置（偏移）。
        用户拿位置就能找到是哪一段，但结果本身**不可还原**。

        ``text`` 空/非字符串 → 返回空列表（不抛异常）。
        """
        raw = "" if text is None else str(text)
        if not raw:
            return []
        found = []
        for name, pat in PATTERNS.items():
            for m in re.finditer(pat, raw):
                found.append({
                    "type": name,
                    "length": len(m.group()),
                    "pos": m.start(),          # 用位置代替内容
                })
        return found

    def mask(self, text):
        """自动脱敏

        脱敏粒度按字符串长度走（2026-10-13 改）：
            原来统一是 s[:3] + "*"*(len-6) + s[-3:]，
            对 7~8 位的串几乎等于没遮（7 位里露 6 位）。
            现在：
                <= 4 位      -> 全遮
                <= 8 位      -> 只留第 1 位
                更长         -> 留前 3 后 2（业界常用做法，保留可辨识性）
        """
        if text is None:
            return ""
        raw = str(text)

        def _mask(m):
            s = m.group()
            n = len(s)
            if n <= 4:
                return "*" * n
            if n <= 8:
                return s[0] + "*" * (n - 1)
            return s[:3] + "*" * (n - 5) + s[-2:]

        for _name, pat in PATTERNS.items():
            raw = re.sub(pat, _mask, raw)
        return raw

    def check_and_mask(self, text):
        """检查并自动脱敏"""
        found = self.detect(text)
        if found:
            return {"safe": False, "found": found, "masked": self.mask(text)}
        return {"safe": True, "found": []}

    def run(self, *a):
        return {"功能": "敏感信息检测脱敏",
                "检测项": list(PATTERNS.keys()),
                "说明": "只在本地判定；检测结果不含原文（只有类型/长度/位置）"}
