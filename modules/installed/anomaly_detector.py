# -*- coding: utf-8 -*-
"""异常检测 v2.0 - 监控错误 + 告警 + 记录 + 自动修复 + 统计 + 清空"""
import sys, os, time
from core.safe import safe
from modules.base import BaseModule


class AnomalyDetector(BaseModule):
    NAME = "anomaly_detector"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.errors = []
        self.max_errors = 100
        self.warnings = 0
        self.start_time = time.time()

    @safe
    def report_error(self, error_type, message, module=""):
        """报告错误"""
        entry = {
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "类型": error_type,
            "信息": message[:100],
            "模块": module
        }
        self.errors.append(entry)
        if len(self.errors) > self.max_errors:
            self.errors = self.errors[-self.max_errors:]

        # 错误太多告警
        if len(self.errors) > 20:
            self.warnings += 1

        return {"记录": entry}

    @safe
    def get_errors(self, count=20):
        """获取最近错误"""
        return {"错误数": len(self.errors), "最近": self.errors[-count:]}

    @safe
    def clear_errors(self):
        """清空错误记录"""
        self.errors = []
        self.warnings = 0
        return {"ok": True}

    @safe
    def check_health(self):
        """健康检查"""
        uptime = int(time.time() - self.start_time)
        status = {
            "状态": "正常",
            "错误数": len(self.errors),
            "告警数": self.warnings,
            "运行时长": f"{uptime//3600}小时{(uptime%3600)//60}分"
        }
        if len(self.errors) > 50:
            status["状态"] = "警告"
            status["提示"] = "错误太多，建议重启"
        elif len(self.errors) > 20:
            status["状态"] = "注意"
        return status

    @safe
    def auto_fix(self):
        """自动修复简单错误"""
        if not self.errors:
            return {"状态": "无错误"}

        # 这里原来调 self_heal.fix() 做自动修复，但 SelfHealPipeline
        # 根本没有 fix 方法，hasattr 永远为假 —— 那个分支从来没执行过。
        # self_heal 已删除，这段一并去掉，如实说明没有自动修复能力。
        return {"状态": "无自动修复能力", "说明": "请到「设置 → 系统 → 日志」里看错误详情"}

    @safe
    def error_stats(self):
        """错误统计"""
        from collections import Counter
        types = [e["类型"] for e in self.errors]
        return {"错误类型统计": Counter(types).most_common(5)}

    @safe
    def export_report(self):
        """导出报告"""
        s = self.check_health()
        report = f"""异常检测报告
==========
状态: {s['状态']}
错误数: {s['错误数']}
告警数: {s['告警数']}
运行时长: {s['运行时长']}
"""
        return {"报告": report}

    def run(self, *args):
        return self.check_health()
