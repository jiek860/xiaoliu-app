# -*- coding: utf-8 -*-
"""敏感信息检测 + 自动脱敏"""
import re


# 注意：不要用 \b 来卡数字边界。
# \b 是"\w 与非 \w 之间"，而中文属于 \w ——
# "我的手机号是13812345678" 里「是」和「1」之间没有边界，
# \b1[3-9]\d{9}\b 永远匹配不到。这个模块因此在中文语境下几乎失效
# （只有数字前面是空格/标点时才碰巧能用）。
# 改用前后否定环视，保证卡的是"数字边界"而不是"单词边界"。
PATTERNS = {
    "身份证": r"(?<!\d)\d{17}[\dXx](?!\d)",
    "银行卡": r"(?<!\d)\d{16,19}(?!\d)",
    "手机号": r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "邮箱": r"[\w.-]+@[\w.-]+\.\w+",
    "API密钥": r"(?:sk-|api[_-]?key[=:]\s*)[\w-]{16,}",
    "密码": r"(?:password|passwd|pwd)[=:]\s*\S+",
}


class SensitiveDetector:
    """敏感信息检测与脱敏"""
    def __init__(self, trunk=None):
        self.trunk = trunk

    def detect(self, text):
        """检测敏感信息"""
        found = []
        for name, pat in PATTERNS.items():
            for m in re.finditer(pat, text):
                found.append({"type": name, "value": m.group()[:20] + "..."})
        return found

    def mask(self, text):
        """自动脱敏"""
        for name, pat in PATTERNS.items():
            def _mask(m):
                s = m.group()
                if len(s) <= 6:
                    return "***"
                return s[:3] + "*" * (len(s) - 6) + s[-3:]
            text = re.sub(pat, _mask, text)
        return text

    def check_and_mask(self, text):
        """检查并自动脱敏"""
        found = self.detect(text)
        if found:
            return {"safe": False, "found": found, "masked": self.mask(text)}
        return {"safe": True, "found": []}

    def run(self, *a):
        return {"功能": "敏感信息检测脱敏", "检测项": list(PATTERNS.keys())}
