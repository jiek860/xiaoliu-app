# -*- coding: utf-8 -*-
"""性能监控 v1.0 - 记录关键操作耗时"""
import threading
from collections import defaultdict


class PerfMonitor:
    """性能监控：记录reply、向量搜索、嵌入等关键操作耗时"""
    def __init__(self):
        self._lock = threading.Lock()
        self._metrics = defaultdict(list)

    def record(self, name, value):
        """记录一个指标（秒）"""
        with self._lock:
            self._metrics[name].append(value)
            # 最多保留1000条
            if len(self._metrics[name]) > 1000:
                self._metrics[name] = self._metrics[name][-500:]

    def stats(self, name=None):
        """统计：平均值、最小值、最大值、P95"""
        with self._lock:
            if name:
                vals = self._metrics.get(name, [])
                return self._calc_stats(vals)
            # 全部指标
            return {k: self._calc_stats(v) for k, v in self._metrics.items()}

    def _calc_stats(self, vals):
        if not vals:
            return {}
        sorted_vals = sorted(vals)
        n = len(vals)
        return {
            "count": n,
            "avg": round(sum(vals) / n, 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
            "p95": round(sorted_vals[int(n * 0.95)], 3) if n > 20 else None,
        }

    def all_stats_str(self):
        """格式化输出"""
        s = self.stats()
        lines = []
        for name, st in s.items():
            if st:
                lines.append("%s: %.2fs avg (%.2f~%.2fs, %d次)" % (
                    name, st["avg"], st["min"], st["max"], st["count"]))
        return "\n".join(lines) if lines else "暂无性能数据"
