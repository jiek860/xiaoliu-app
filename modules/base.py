# -*- coding: utf-8 -*-
"""模块基类 - 所有功能模块的父类，提供通用方法
减少重复代码：stats / export_report / run
"""
import time


class BaseModule:
    """所有功能模块的基类"""
    NAME = "未命名模块"
    VERSION = "1.0"

    def __init__(self, trunk=None):
        self.trunk = trunk
        self._count = 0  # 调用次数
        self._history = []  # 历史记录
        self._start_time = time.time()

    def stats(self):
        """统计信息（子类可覆盖）"""
        return {
            "模块": self.NAME,
            "版本": self.VERSION,
            "调用次数": self._count,
            "运行时长": "%.1f秒" % (time.time() - self._start_time),
        }

    def export_report(self):
        """导出报告（子类可覆盖）"""
        s = self.stats()
        lines = ["%s 报告" % self.NAME, "=" * 30]
        for k, v in s.items():
            lines.append("%s: %s" % (k, v))
        return {"报告": "\n".join(lines)}

    def clear_history(self):
        """清空历史"""
        self._history.clear()
        return {"ok": True}

    def get_history(self, count=10):
        """获取历史"""
        return {"历史": self._history[-count:]}

    def run(self, *args):
        """入口方法（子类覆盖）"""
        self._count += 1
        if args:
            return {"结果": str(args[0])}
        return self.stats()

    def _add_history(self, item):
        """添加历史记录"""
        self._history.append({
            "time": time.strftime("%H:%M:%S"),
            "item": item
        })
        # 最多保留100条
        if len(self._history) > 100:
            self._history = self._history[-100:]
