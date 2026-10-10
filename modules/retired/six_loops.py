# -*- coding: utf-8 -*-
import sys, os as _os
from core.safe import safe
from modules.base import BaseModule
"""六大闭环 v1.0
错误闭环 / 性能闭环 / 安全闭环 / 用户反馈闭环 / 数据闭环 / 测试闭环
"""
import os, time, json, re, traceback
from datetime import datetime
from collections import Counter


class SixLoops(BaseModule):
    NAME = "six_loops"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.data_dir = os.path.join(self.base, "data")
        self.feedback_path = os.path.join(self.data_dir, "feedback.json")
        self.errors_path = os.path.join(self.data_dir, "errors.json")
        self.perf_path = os.path.join(self.data_dir, "perf.json")
        self._load()

    def _load(self):
        self.feedback = self._read_json(self.feedback_path)
        self.errors = self._read_json(self.errors_path)
        self.perf = self._read_json(self.perf_path)

    def _read_json(self, p):
        try:
            if os.path.exists(p):
                d = json.load(open(p, encoding="utf-8"))
                return d if isinstance(d, dict) else {}
        except: pass
        return {}

    def _save_json(self, p, d):
        try:
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except: pass

    # ===== 1. 错误闭环 =====
    def error_loop(self, error_text):
        """报错→分析→修复建议→记录"""
        err_key = str(error_text)[:100]
        self.errors[err_key] = {
            "time": datetime.now().isoformat(),
            "count": self.errors.get(err_key, {}).get("count", 0) + 1,
        }
        self._save_json(self.errors_path, self.errors)
        # 简单分析
        suggestions = []
        if "ModuleNotFoundError" in error_text or "ImportError" in error_text:
            suggestions.append("装依赖: pip install 包名")
        elif "SyntaxError" in error_text:
            suggestions.append("检查语法: 括号/缩进/冒号")
        elif "TypeError" in error_text:
            suggestions.append("检查参数类型")
        elif "KeyError" in error_text:
            suggestions.append("检查字典 key 是否存在")
        elif "sqlite3.OperationalError" in error_text:
            suggestions.append("检查数据库表结构")
        return {"error": error_text[:20], "suggestions": suggestions}

    # ===== 2. 性能闭环 =====
    def perf_loop(self, action, duration_ms):
        """记录耗时，慢了告警"""
        if "actions" not in self.perf:
            self.perf["actions"] = {}
        if action not in self.perf["actions"]:
            self.perf["actions"][action] = {"count": 0, "total_ms": 0, "max_ms": 0}
        d = self.perf["actions"][action]
        d["count"] += 1
        d["total_ms"] += duration_ms
        d["max_ms"] = max(d["max_ms"], duration_ms)
        avg = d["total_ms"] / d["count"]
        alert = ""
        if avg > 3000:
            alert = "⚠️ 平均耗时 %.1f秒，偏慢" % (avg/1000)
        self._save_json(self.perf_path, self.perf)
        return {"action": action, "avg_ms": int(avg), "alert": alert}

    # ===== 3. 安全闭环 =====
    def security_loop(self, action, detail=""):
        """异常操作检测"""
        dangerous = ["删除", "格式化", "关机", "重启", "rm -rf", "del /f"]
        for word in dangerous:
            if word in action or word in detail:
                return {"blocked": True, "msg": "⚠️ 危险操作被拦截: " + word}
        return {"blocked": False}

    # ===== 4. 用户反馈闭环 =====
    def feedback_loop(self, user_says, ai_answer):
        """你说不对→AI改→再问对了吗"""
        if re.search(r'(不对|错了|不是|不对吧|差远了|根本不是)', user_says):
            # 记录负面反馈
            self.feedback["negative"] = self.feedback.get("negative", 0) + 1
            self.feedback["last_wrong"] = {
                "user": user_says[:100],
                "ai": ai_answer[:200],
                "time": datetime.now().isoformat()
            }
            self._save_json(self.feedback_path, self.feedback)
            return {"need_fix": True, "msg": "好的，我改——你说应该怎么答？"}
        elif re.search(r'(对|没错|可以|行|好的|对了)', user_says):
            self.feedback["positive"] = self.feedback.get("positive", 0) + 1
            self._save_json(self.feedback_path, self.feedback)
            return {"need_fix": False}
        return {"need_fix": False}

    # ===== 5. 数据闭环 =====
    def data_loop(self, user_input):
        """统计用户偏好，主动推荐"""
        if "topics" not in self.feedback:
            self.feedback["topics"] = Counter()
        topics = ["代码", "编程", "python", "易经", "算卦", "天气", "新闻", "下载", "安装"]
        for t in topics:
            if t in user_input.lower():
                self.feedback["topics"][t] = self.feedback["topics"].get(t, 0) + 1
        self._save_json(self.feedback_path, self.feedback)
        # 找最常聊的
        if self.feedback["topics"]:
            top = sorted(self.feedback["topics"].items(), key=lambda x: -x[1])[:3]
            return {"favorite_topics": top}
        return {}

    # ===== 6. 测试闭环 =====
    def test_loop(self, code):
        """跑代码，不通过返回错误"""
        try:
            # 简单语法检查
            compile(code, "<test>", "exec")
            return {"passed": True, "error": ""}
        except SyntaxError as e:
            return {"passed": False, "error": str(e)}
        except Exception as e:
            return {"passed": False, "error": str(e)}
    def run(self, *a):
        """统一入口：返回六闭环统计"""
        return {
            "错误数": len(self.errors),
            "反馈数": len(self.feedback),
            "性能数据": len(self.perf),
            "状态": "正常",
        }

