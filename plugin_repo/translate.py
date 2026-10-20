# -*- coding: utf-8 -*-
"""翻译 v2.1 - 8种语言翻译 + 批量翻译 + 历史记录 + 语言列表 + 清空 + 统计 + 导出"""
import time
from core.safe import safe
from modules.base import BaseModule


class Translator(BaseModule):
    NAME = "translate"
    VERSION = "1.0"

    TOOLS = [
        {"name": "translate_text", "method": "translate",
         "desc": "把一段文字翻译成目标语言",
         "args": {"text": "要翻译的文字",
                  "to_lang": "目标语言代码，如 en/zh/ja，默认 en"},
         "readonly": True,
         "hints": ["翻译", "translate", "译成", "英文怎么说", "中文意思"]},
        {"name": "translate_detect", "method": "detect_lang",
         "desc": "判断一段文字是什么语言",
         "args": {"text": "要判断的文字"},
         "readonly": True,
         "hints": ["什么语言", "哪国语言", "识别语言"]},
    ]
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.history = []
        self.translate_count = 0
        self.langs = [
            {"code": "en", "name": "英语"},
            {"code": "ja", "name": "日语"},
            {"code": "ko", "name": "韩语"},
            {"code": "fr", "name": "法语"},
            {"code": "de", "name": "德语"},
            {"code": "es", "name": "西班牙语"},
            {"code": "ru", "name": "俄语"},
            {"code": "zh", "name": "中文"},
        ]

    @safe
    def translate(self, text, to_lang="en"):
        """翻译"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}

        try:
            r = llm.chat(f"把这句话翻译成{to_lang}: {text[:200]}")
            self.translate_count += 1
            self.history.append({
                "原文": text[:50],
                "译文": r[:50],
                "目标语言": to_lang,
                "时间": time.strftime("%m-%d %H:%M")
            })
            if len(self.history) > 30:
                self.history = self.history[-30:]
            return {"原文": text, "译文": r, "语言": to_lang}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def batch_translate(self, texts, to_lang="en"):
        """批量翻译"""
        results = []
        for t in texts[:5]:
            r = self.translate(t, to_lang)
            results.append(r)
        return {"处理数": len(results), "结果": results}

    @safe
    def list_languages(self):
        """列出所有支持的语言"""
        return self.langs

    @safe
    def get_history(self, count=10):
        """获取翻译历史"""
        return {"历史": self.history[-count:]}

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        self.translate_count = 0
        return {"ok": True}

    @safe
    def detect_lang(self, text):
        """检测语言"""
        if any('\u4e00' <= c <= '\u9fff' for c in text):
            return "zh"
        elif any('\u3040' <= c <= '\u30ff' for c in text):
            return "ja"
        elif any('\uac00' <= c <= '\ud7af' for c in text):
            return "ko"
        return "en"

    @safe
    def stats(self):
        """统计"""
        return {
            "总翻译次数": self.translate_count,
            "支持语言数": len(self.langs),
            "历史数": len(self.history)
        }

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        report = f"""翻译模块报告
==========
总翻译次数: {s['总翻译次数']}
支持语言数: {s['支持语言数']}
历史数: {s['历史数']}
"""
        return {"报告": report}

    def run(self, *args):
        if args:
            return self.translate(args[0])
        return self.stats()

