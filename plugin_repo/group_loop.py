# -*- coding: utf-8 -*-
"""群聊闭环 v2.1 - 智能路由 + 群聊组合 + 异常检测 + 反馈 + 统计 + 重置 + 导出"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, time, json
from core.safe import safe
from modules.base import BaseModule


class GroupChatPipeline(BaseModule):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "group_loop"
    VERSION = "1.0"

    TOOLS = [
        {
         "contract": {
             "params": {},
             "returns": {"type": "object"},
             "description": "群聊闭环统计：累计轮次、好评率、差评数",
         },
         "name": "grouploop_stats", "method": "stats",
         "desc": "群聊闭环统计：累计轮次、好评率、差评数",
         "args": {},
         "readonly": True,
         "hints": ["群聊统计", "群聊闭环", "好评率"]},
        {
         "contract": {
             "params": {
                 "n": {"type": "integer"}
             },
             "returns": {"type": "object"},
             "description": "看看群聊里表现最差的几轮",
         },
         "name": "grouploop_worst", "method": "worst_rounds",
         "desc": "看看群聊里表现最差的几轮",
         "args": {"n": "看几条，默认 5"},
         "readonly": True,
         "hints": ["最差几轮", "群聊表现", "差评"]},
    ]
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.state_path = os.path.join(self.base, "data", "group_loop.json")
        self.state = self._load()

    # 状态文件里必须存在的键。老版本写下的文件可能缺字段
    # （实测 stats() 会 KeyError: 'good'），读进来后统一补齐。
    _DEFAULT_STATE = {"rounds": 0, "anomalies": 0, "good": 0, "bad": 0,
                      "feedback_history": []}

    def _load(self):
        data = None
        if os.path.exists(self.state_path):
            try:
                data = json.load(open(self.state_path, encoding="utf-8"))
            except Exception:
                data = None
        if not isinstance(data, dict):
            return dict(self._DEFAULT_STATE)
        out = dict(self._DEFAULT_STATE)
        out.update(data)
        return out

    def _save(self):
        from core.safe import atomic_write_json
        try:
            atomic_write_json(self.state_path, self.state)
        except Exception as e:
            _x6_swallowed(__name__, e)

    @safe
    def feedback(self, user_input, ai_response, good=True):
        """用户反馈"""
        self.state["rounds"] += 1
        if good:
            self.state["good"] += 1
        else:
            self.state["bad"] += 1
            self.state["anomalies"] += 1

        self.state["feedback_history"].append({
            "用户": user_input[:30],
            "AI": ai_response[:30],
            "好评": good,
            "时间": time.strftime("%m-%d %H:%M")
        })
        if len(self.state["feedback_history"]) > 50:
            self.state["feedback_history"] = self.state["feedback_history"][-50:]

        self._save()
        return {"ok": True, "累计轮次": self.state["rounds"]}

    @safe
    def stats(self):
        """统计"""
        total = self.state["rounds"]
        good = self.state["good"]
        rate = f"{good/total*100:.1f}%" if total > 0 else "0%"
        return {
            "累计轮次": total,
            "好评数": good,
            "差评数": self.state["bad"],
            "好评率": rate,
            "异常数": self.state["anomalies"]
        }

    @safe
    def reset(self):
        """重置统计"""
        self.state = {"rounds": 0, "anomalies": 0, "good": 0, "bad": 0, "feedback_history": []}
        self._save()
        return {"ok": True}

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        report = f"""群聊闭环报告
==========
累计轮次: {s['累计轮次']}
好评数: {s['好评数']}
差评数: {s['差评数']}
好评率: {s['好评率']}
异常数: {s['异常数']}
"""
        return {"报告": report}

    @safe
    def get_history(self, count=10):
        """获取反馈历史"""
        return {"历史": self.state["feedback_history"][-count:]}

    @safe
    def worst_rounds(self, n=5):
        """获取差评最多的轮次"""
        bad = [h for h in self.state["feedback_history"] if not h["好评"]]
        return bad[-n:] if bad else []

    def run(self, *args):
        return self.stats()

    @safe
    def get_good_rate(self):
        """好评率"""
        s = self.stats()
        return {"好评率": s.get("好评率", "0%")}

    @safe
    def clear_history(self):
        """清空历史"""
        self.state["feedback_history"] = []
        self._save()
        return {"ok": True}

    @safe
    def get_feedback_by_date(self, date):
        """按日期查反馈"""
        found = [h for h in self.state["feedback_history"] if date in h.get("时间", "")]
        return {"日期": date, "反馈数": len(found)}

