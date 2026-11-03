# -*- coding: utf-8 -*-
"""P1-09: 人格成长报告（完整版）

做了什么
--------
1. **读真实数据**：``data/personality.json``（人格模块写的那份）。
   读不到/读坏了要明确说出来 —— 原来静默退回默认值，
   报出「认识 0 天 / 关系阶段 0」，**和「真的刚认识」完全分不清**。
2. **趋势对比**：``checkpoint()`` 每天存一条快照到
   ``data/growth_history.json``（同一天只留最新一条），
   ``report(days=30)`` 拿「N 天前的快照」和现在比，给关系阶段与记忆数变化。
3. **导出**：``export_md()`` 落盘 ``data/growth_report.md``。

为什么 `report()` 自己不写快照
------------------------------
能力表里 ``growth_report`` 标的是 ``readonly=True``（只读）。
读一次报告就写盘会打破这个契约、也会把只读校验搞脏，
所以快照由 ``checkpoint()`` 单独负责，由启动编排每天调一次。
"""
import json
import os
import time
from datetime import datetime, timedelta

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)

HISTORY_LIMIT = 400          # 约一年多的日快照，超出后丢最旧的
MAX_DAYS = 3650


class GrowthReport:
    """人格成长报告：当前状态 + 趋势对比 + 导出"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.path = data_path(trunk, "personality.json")
        self.history_path = data_path(trunk, "growth_history.json")

    # ------------------------------------------------------------------
    @staticmethod
    def _norm_days(days, default=30):
        try:
            value = int(days)
        except (TypeError, ValueError):
            return default
        return max(1, min(MAX_DAYS, value))

    def _read_personality(self):
        """返回 (数据, 读失败说明)。文件不存在不算失败（就是还没聊过）。"""
        if not os.path.exists(self.path):
            return {}, ""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {}, "%s: %s" % (type(e).__name__, str(e)[:80])
        if not isinstance(data, dict):
            return {}, "personality.json 格式不对（应为对象）"
        return data, ""

    def _current(self, data, now=None):
        """把 personality.json 压成一条快照"""
        now = float(now or time.time())
        birth = data.get("birth_time", now)
        try:
            birth = float(birth)
        except (TypeError, ValueError):
            birth = now
        days = max(0, int((now - birth) / 86400))
        traits = data.get("traits")
        return {
            "date": datetime.fromtimestamp(now).strftime("%Y-%m-%d"),
            "ts": now,
            "认识天数": days,
            "关系阶段": int(data.get("relation_stage", 0) or 0),
            "记忆数": int(data.get("memory_count", 0) or 0),
            "性格特征": traits if isinstance(traits, dict) else {},
            "里程碑": data.get("milestones") if isinstance(
                data.get("milestones"), list) else [],
        }

    # ------------------------------------------------------------------
    def checkpoint(self, now=None):
        """把今天的成长快照落盘（同一天只保留最新一条）。

        返回 ``{"ok": True, "日期": ..., "快照数": n}``；
        写不了时 ``ok=False`` + ``msg``（调用方自己决定要不要提示）。
        """
        data, _err = self._read_personality()
        snap = self._current(data, now)
        rows = self._load_history()
        # 同一天覆盖：一天跑十次也只留一条
        rows = [r for r in rows
                if not (isinstance(r, dict) and r.get("date") == snap["date"])]
        rows.append(snap)
        rows = sorted(rows, key=lambda r: str(r.get("date") or ""))
        rows = rows[-HISTORY_LIMIT:]
        try:
            folder = os.path.dirname(self.history_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = self.history_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.history_path)
        except Exception as e:
            return {"ok": False, "msg": "写成长快照失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "日期": snap["date"], "快照数": len(rows)}

    def _load_history(self):
        """读快照列表；文件坏了就返回空（趋势显示"历史不足"而不是崩）"""
        if not os.path.exists(self.history_path):
            return []
        try:
            with open(self.history_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return [r for r in data if isinstance(r, dict) and r.get("date")]

    # ------------------------------------------------------------------
    def _baseline(self, rows, days, now=None):
        """取「N 天前」的基准快照：找 date ≤ 目标日期的最近一条"""
        now = now or datetime.now()
        target = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        older = [r for r in rows if str(r.get("date") or "") <= target]
        return older[-1] if older else None

    def trend(self, days=30, now=None):
        """本周期 vs 上周期（没有足够历史时明确说"还不够"）"""
        days = self._norm_days(days)
        rows = self._load_history()
        base = self._baseline(rows, days, now)
        if base is None:
            return {"对比周期天": days,
                    "说明": "历史快照不足 %d 天，先积累几天再看不变化" % days}
        data, _err = self._read_personality()
        cur = self._current(data)
        return {
            "对比周期天": days,
            "基准日期": base.get("date"),
            "关系阶段": {"当时": base.get("关系阶段", 0),
                        "现在": cur["关系阶段"],
                        "变化": cur["关系阶段"] - int(base.get("关系阶段", 0) or 0)},
            "记忆数": {"当时": base.get("记忆数", 0),
                      "现在": cur["记忆数"],
                      "变化": cur["记忆数"] - int(base.get("记忆数", 0) or 0)},
            "认识天数": {"当时": base.get("认识天数", 0),
                        "现在": cur["认识天数"],
                        "变化": cur["认识天数"] - int(base.get("认识天数", 0) or 0)},
            "快照总数": len(rows),
        }

    # ------------------------------------------------------------------
    def report(self, days=30):
        """生成成长报告（只读，不写盘）"""
        data, read_err = self._read_personality()
        cur = self._current(data)

        r = {
            "ok": True,
            "认识天数": cur["认识天数"],
            "关系阶段": cur["关系阶段"],
            "性格特征": cur["性格特征"],
            "里程碑": cur["里程碑"],
            "记忆数": cur["记忆数"],
            "趋势": self.trend(days),
        }
        if read_err:
            r["数据读取失败"] = read_err
            r["说明"] = ("上面的数字是**默认值**不是真实数据 —— "
                         "personality.json 读不了（%s）" % read_err[:60])
        elif not data:
            r["说明"] = "还没有人格数据（data/personality.json 不存在）"
        return r

    def to_markdown(self, days=30):
        """报告文本（导出用；不写盘）"""
        r = self.report(days)
        lines = ["# 小6 成长报告\n"]
        if r.get("说明"):
            lines.append("> %s\n" % r["说明"])
        lines.append("## 当前状态\n")
        lines.append("- 认识天数：%s 天" % r.get("认识天数"))
        lines.append("- 关系阶段：%s" % r.get("关系阶段"))
        lines.append("- 记忆数：%s 条" % r.get("记忆数"))
        traits = r.get("性格特征") or {}
        if traits:
            lines.append("- 性格特征：%s" % "、".join(
                "%s=%s" % (k, v) for k, v in list(traits.items())[:8]))
        miles = r.get("里程碑") or []
        if miles:
            lines.append("- 里程碑：%s" % "、".join(
                "%s(%s)" % (m.get("name", "?"), m.get("count", 0))
                for m in miles if isinstance(m, dict)))
        lines.append("\n## 趋势（最近 %s 天）\n" % r.get("趋势", {}).get(
            "对比周期天", days))
        tr = r.get("趋势") or {}
        if tr.get("说明"):
            lines.append("- %s" % tr["说明"])
        else:
            for key in ("关系阶段", "记忆数", "认识天数"):
                block = tr.get(key) or {}
                lines.append("- %s：%s → %s（%+d）"
                             % (key, block.get("当时"), block.get("现在"),
                                int(block.get("变化") or 0)))
        return "\n".join(lines) + "\n"

    def export_md(self, days=30, path=None):
        """把报告写到文件（默认 ``data/growth_report.md``）"""
        target = str(path or data_path(self.trunk, "growth_report.md"))
        try:
            folder = os.path.dirname(target)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self.to_markdown(days))
            os.replace(tmp, target)
        except Exception as e:
            return {"ok": False, "msg": "写报告失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "path": target}

    def run(self, *a):
        return self.report()
