# -*- coding: utf-8 -*-
"""反馈学习 - 从用户话语里记录偏好，不直接改核心逻辑，只记录日志"""
import os, json, re, time
from core.paths import BASE
class FeedbackLearner:
    RULES = [
        ("嫌长", re.compile(r"(太长|太啰嗦|简短点|说重点)")),
        ("嫌短", re.compile(r"(太短|详细点|多说点)")),
        ("记不住", re.compile(r"(你记错了|你忘了|之前说过)")),
    ]
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or BASE
        self.log_path = os.path.join(self.base, "data", "feedback_log.json")
    def observe(self, text):
        if not text: return []
        hits = []
        for name, pat in self.RULES:
            if pat.search(text):
                hits.append(name)
        if hits:
            self._log(hits, text)
        return hits
    def _log(self, tags, text):
        try:
            log = []
            if os.path.exists(self.log_path):
                log = json.load(open(self.log_path, encoding="utf-8"))
            log.append({"time":time.strftime("%Y-%m-%d %H:%M:%S"), "tags":tags, "text":text[:50]})
            log = log[-200:]
            tmp = self.log_path + ".tmp"
            json.dump(log, open(tmp,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(tmp, self.log_path)
        except: pass
