# -*- coding: utf-8 -*-
"""敏感信息检测 + 自动脱敏"""
import re


PATTERNS = {
    "身份证": r"\b\d{17}[\dXx]\b",
    "银行卡": r"\b\d{16,19}\b",
    "手机号": r"\b1[3-9]\d{9}\b",
    "邮箱": r"\b[\w.-]+@[\w.-]+\.\w+\b",
    "API密钥": r"\b(sk-|api[_-]?key[=:]\s*)[\w-]{16,}\b",
    "密码": r"\b(password|passwd|pwd)[=:]\s*\S+\b",
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
