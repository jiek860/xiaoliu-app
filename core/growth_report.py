# -*- coding: utf-8 -*-
"""P1-09: 人格成长报告"""
import os, json, time


class GrowthReport:
    """人格成长报告"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "personality.json")

    def report(self):
        """生成成长报告

        读不到 personality.json 时原来静默退回默认值 —— 于是报出
        "认识 0 天 / 关系阶段 0"，**和"真的刚认识"完全分不清**。
        现在把读取失败明确说出来（数据缺失或写坏了，用户该知道）。
        """
        data = {}
        read_err = ""
        if os.path.exists(self.path):
            try:
                data = json.load(open(self.path, encoding="utf-8"))
            except Exception as e:
                read_err = "%s: %s" % (type(e).__name__, str(e)[:80])

        birth = data.get("birth_time", time.time())
        days = int((time.time() - birth) / 86400)

        r = {
            "认识天数": days,
            "关系阶段": data.get("relation_stage", 0),
            "性格特征": data.get("traits", {}),
            "里程碑": data.get("milestones", []),
            "记忆数": data.get("memory_count", 0),
        }
        if read_err:
            r["数据读取失败"] = read_err
            r["说明"] = ("上面的数字是**默认值**不是真实数据 —— "
                         "personality.json 读不了（%s）" % read_err[:60])
        elif not data:
            r["说明"] = "还没有人格数据（data/personality.json 不存在）"
        return r

    def run(self, *a):
        return self.report()
