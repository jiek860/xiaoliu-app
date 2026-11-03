# -*- coding: utf-8 -*-
"""v26-6.2: 数据统计报表（完整版）

为什么要改返回结构
------------------
原来三个计数失败时一律 `return 0`，于是「**真的 0 条**」和
「**文件读不出来**」在结果里长得一模一样 —— 用户看到「聊天消息 0 条」
根本不知道是没聊过，还是数据库坏了。

现在每项都是结构化的：
    {"值": n, "状态": "ok" | "缺失" | "失败", "说明": 可选}
- ``ok``   读到了，n 是真的
- ``缺失`` 文件/表本来就没有（还没聊过，正常）
- ``失败`` 文件在但读不出来（该看日志了）

时间范围也真的生效了：``今天 / 本周 / 本月 / 全部`` 或天数。
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)

_PERIODS = ("今天", "本周", "本月", "全部")


class StatsReport:
    """生成使用统计报告"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.db_path = data_path(trunk, "chats.db")
        self.cards_path = data_path(trunk, "memory_cards.jsonl")
        self.calendar_path = data_path(trunk, "calendar.json")

    # ------------------------------------------------------------------
    @staticmethod
    def _since(period):
        """时间范围 → 起始时间戳；0 表示「全部」。认不出来就按全部算。"""
        now = datetime.now()
        text = str(period or "").strip()
        if text in ("", "全部", "所有"):
            return 0.0, "全部"
        if text == "今天":
            start = datetime(now.year, now.month, now.day)
        elif text == "本周":
            start = datetime(now.year, now.month, now.day) - timedelta(
                days=now.weekday())
        elif text == "本月":
            start = datetime(now.year, now.month, 1)
        else:
            try:
                days = int(text)
            except (TypeError, ValueError):
                return 0.0, "全部"
            days = max(1, min(3650, days))
            start = now - timedelta(days=days)
            return start.timestamp(), "最近 %d 天" % days
        return start.timestamp(), text

    @staticmethod
    def _ok(value, extra=None):
        item = {"值": int(value), "状态": "ok"}
        if extra:
            item.update(extra)
        return item

    @staticmethod
    def _missing(msg="文件不存在（还没产生数据）"):
        return {"值": 0, "状态": "缺失", "说明": msg}

    @staticmethod
    def _failed(msg):
        return {"值": 0, "状态": "失败", "说明": str(msg)[:120]}

    # ------------------------------------------------------------------
    def _count_chats(self, since=0.0):
        if not os.path.exists(self.db_path):
            return self._missing("chats.db 不存在（还没聊过）")
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cols = [row[1] for row in
                        conn.execute("PRAGMA table_info(messages)").fetchall()]
                if not cols:
                    return self._missing("chats.db 里还没有 messages 表")
                if since and "ts" in cols:
                    n = conn.execute("SELECT COUNT(*) FROM messages WHERE ts >= ?",
                                     (since,)).fetchone()[0]
                else:
                    # 没有 ts 列（老库）时只能报总数，并说明范围没生效
                    n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                    if since:
                        return self._ok(n, {"说明": "老库没有 ts 列，这里是全部条数"})
            finally:
                conn.close()
            return self._ok(n)
        except Exception as e:
            return self._failed("读 chats.db 失败：%s: %s"
                                % (type(e).__name__, str(e)[:60]))

    def _count_cards(self, since=0.0):
        if not os.path.exists(self.cards_path):
            return self._missing("memory_cards.jsonl 不存在（还没有记忆卡）")
        try:
            total, bad = 0, 0
            with open(self.cards_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        card = json.loads(line)
                    except Exception:
                        bad += 1
                        continue
                    if since:
                        ts = card.get("time") if isinstance(card, dict) else None
                        if isinstance(ts, (int, float)) and ts < since:
                            continue
                    total += 1
        except Exception as e:
            return self._failed("读记忆卡失败：%s: %s"
                                % (type(e).__name__, str(e)[:60]))
        extra = {"说明": "有 %d 行没法解析（已跳过）" % bad} if bad else None
        return self._ok(total, extra)

    def _count_calendar(self, since=0.0):
        if not os.path.exists(self.calendar_path):
            return self._missing("calendar.json 不存在（还没有日历事件）")
        try:
            with open(self.calendar_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return self._failed("读日历失败：%s: %s"
                                % (type(e).__name__, str(e)[:60]))
        if isinstance(data, dict):
            rows = data.get("三元组") or data.get("events") or []
        elif isinstance(data, list):
            rows = data
        else:
            return self._failed("calendar.json 格式不对（应为数组）")
        if not isinstance(rows, list):
            return self._failed("calendar.json 的事件列表格式不对")
        if not since:
            return self._ok(len(rows))
        cutoff = datetime.fromtimestamp(since).strftime("%Y-%m-%d")
        kept = [r for r in rows
                if isinstance(r, dict) and str(r.get("date") or "") >= cutoff]
        return self._ok(len(kept))

    # ------------------------------------------------------------------
    def generate(self, period="全部"):
        """返回结构化统计（每项都带「值 + 状态」）"""
        since, label = self._since(period)
        stats = {
            "聊天消息": self._count_chats(since),
            "记忆卡": self._count_cards(since),
            "日历事件": self._count_calendar(since),
        }
        failed = [k for k, v in stats.items() if v.get("状态") == "失败"]
        r = {
            "ok": not failed,
            "范围": label,
            "统计": stats,
            "合计": sum(int(v.get("值") or 0) for v in stats.values()),
        }
        if failed:
            r["说明"] = "%s 读不出来（不是 0 条，是没读成）" % "、".join(failed)
        return r

    def to_markdown(self, period="全部"):
        """报告文本（GUI 弹窗与导出共用一份，避免两套渲染逻辑）"""
        r = self.generate(period)
        lines = ["# 小6使用统计\n"]
        lines.append("**时间范围：** %s\n" % r.get("范围", period))
        lines.append("## 使用量\n")
        for name, item in (r.get("统计") or {}).items():
            state = item.get("状态")
            if state == "ok":
                suffix = ""
                if item.get("说明"):
                    suffix = "（%s）" % item["说明"]
                lines.append("- %s：%d 条%s" % (name, item.get("值", 0), suffix))
            elif state == "缺失":
                lines.append("- %s：还没有数据（%s）"
                             % (name, item.get("说明", "")))
            else:
                lines.append("- %s：**读取失败**（%s）"
                             % (name, item.get("说明", "")))
        lines.append("\n- 合计：%s 条\n" % r.get("合计", 0))
        if r.get("说明"):
            lines.append("\n> %s\n" % r["说明"])
        return "\n".join(lines) + "\n"

    def summary(self, period="全部"):
        """一行摘要（设置页显示用，比 markdown 短）。

        读失败的项**不能显示成 0 条**：这里分别写「—」和「读失败」。
        """
        r = self.generate(period)
        parts = []
        for name, item in (r.get("统计") or {}).items():
            state = item.get("状态")
            if state == "ok":
                parts.append("%s %d" % (name, item.get("值", 0)))
            elif state == "缺失":
                parts.append("%s —" % name)
            else:
                parts.append("%s 读失败" % name)
        return " · ".join(parts) or "暂无统计"

    def run(self, *a):
        return self.generate()
