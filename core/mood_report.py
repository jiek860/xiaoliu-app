# -*- coding: utf-8 -*-
"""P1-08: 情绪日报/情绪统计（完整版）

数据来源（两条都读，按「日期+情绪+时间」去重）
--------------------------------------------
1. ``data/mood_history.json`` —— ``PersonalityStateMixin.log_mood()`` 写，
   每条带 ``date``（YYYY-MM-DD），可以跨天统计。**2026-11-02 起才真的有人写**：
   在此之前 ``log_mood`` 全项目零调用，这个报告读的是一个永远空的文件，
   所以能力一直在报「暂无情绪记录」。
2. ``data/personality.json`` 的 ``mood_history`` —— 旧格式只有 ``时间``（HH:MM）、
   没有日期，按「今天」算。只在新文件读不到时兜底，避免同一段情绪被算两遍。

对外
----
``report(days)``     统计最近 N 天（参数会夹到 1..365）
``to_markdown(days)`` 报告文本
``export_md(days)``  落盘到 ``data/mood_report.md``（也可指定路径）
"""
import json
import os
from collections import Counter
from datetime import datetime, timedelta

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)

MAX_DAYS = 365
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")
_DEFAULT_MOOD = "中性"

_ADVICE = {
    "开心": "保持好心情！",
    "平静": "状态不错，继续保持",
    "焦虑": "最近压力有点大，注意休息",
    "难过": "别难过，会好起来的",
    "愤怒": "深呼吸，冷静一下",
    "低落": "慢慢来，不用急着振作",
}


class MoodReport:
    """情绪报告生成"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.path = data_path(trunk, "mood_history.json")
        self.personality_path = data_path(trunk, "personality.json")

    # ------------------------------------------------------------------
    @staticmethod
    def _norm_days(days):
        """参数校验：非数字/越界都夹回 1..365，避免算出「未来到今天」"""
        try:
            value = int(days)
        except (TypeError, ValueError):
            return 7
        return max(1, min(MAX_DAYS, value))

    @staticmethod
    def _record_time(record):
        """把一条记录换成 datetime；认不出来返回 None。

        没有 ``date`` 但有 ``时间``(HH:MM) 的老记录按「今天」算 —— 那是
        ``personality.json`` 里 ``mood_history`` 的格式。
        """
        raw = record.get("date")
        if raw:
            text = str(raw).strip()
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(text, fmt)
                except (TypeError, ValueError):
                    continue
            return None
        hhmm = str(record.get("时间") or record.get("time") or "").strip()
        if hhmm and ":" in hhmm:
            try:
                hh, mm = hhmm.split(":")[:2]
                now = datetime.now()
                return now.replace(hour=int(hh), minute=int(mm),
                                   second=0, microsecond=0)
            except (TypeError, ValueError):
                return None
        return None

    def _read_json(self, path, what):
        """读 JSON；返回 (数据, 错误说明)。读不到/坏了都要说清，不能装没数据"""
        if not os.path.exists(path):
            return None, ""
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f), ""
        except Exception as e:
            return None, "%s 读不出来（%s: %s）" % (what, type(e).__name__,
                                                 str(e)[:60])

    def _load(self):
        """返回 (记录列表, 读失败说明)"""
        data, err = self._read_json(self.path, "mood_history.json")
        records = []
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)]
        elif data is not None:
            err = err or "mood_history.json 格式不对（应为数组）"

        if records:
            # 去重：老实现可能重复 append 同一条
            seen, uniq = set(), []
            for r in records:
                key = (str(r.get("date") or ""), str(r.get("情绪") or ""),
                       str(r.get("时间") or r.get("time") or ""))
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(r)
            return uniq, err

        # 兜底：personality.json 里的旧 mood_history（只有时间、没有日期）
        pdata, perr = self._read_json(self.personality_path, "personality.json")
        if isinstance(pdata, dict):
            old = pdata.get("mood_history")
            if isinstance(old, list):
                records = [r for r in old if isinstance(r, dict)]
        if not records and not err:
            err = perr
        return records, err

    # ------------------------------------------------------------------
    def report(self, days=7):
        """生成最近 N 天的情绪报告"""
        days = self._norm_days(days)
        history, read_err = self._load()

        if not history:
            r = {"ok": True, "天数": days, "记录数": 0,
                 "说明": "暂无情绪记录"}
            if read_err:
                r["数据读取失败"] = read_err
                r["说明"] = ("暂无可用情绪记录 —— %s（不是「没聊过」，"
                            "是数据读不出来）" % read_err)
            return r

        cutoff = datetime.combine(
            (datetime.now() - timedelta(days=days)).date(), datetime.min.time())
        recent, bad_date = [], 0
        for h in history:
            t = self._record_time(h)
            if t is None:
                # 日期读不出来就跳过这条；但要报数 ——
                # 否则"最近 N 天没有情绪记录"和"记录日期全坏了"分不清
                bad_date += 1
                continue
            if t >= cutoff:
                recent.append((h, t))

        if not recent:
            r = {"ok": True, "天数": days, "记录数": 0}
            if bad_date:
                r["日期异常"] = bad_date
                r["说明"] = ("最近%d天没有情绪记录，但有 %d 条记录的日期"
                             "读不出来（已跳过）—— 可能是数据写坏了"
                             % (days, bad_date))
            else:
                r["说明"] = "最近%d天没有情绪记录" % days
            if read_err:
                r["数据读取失败"] = read_err
            return r

        moods = [str(h.get("情绪") or "").strip() or _DEFAULT_MOOD
                 for h, _t in recent]
        dist = Counter(moods)
        top = [{"情绪": k, "次数": v} for k, v in dist.most_common(3)]
        main_mood = top[0]["情绪"] if top else _DEFAULT_MOOD
        advice = _ADVICE.get(main_mood, "状态平稳")

        r = {
            "ok": True,
            "天数": days,
            "记录数": len(recent),
            "主导情绪": top,
            "分布": dict(dist),
            "建议": advice,
        }
        if bad_date:
            r["日期异常"] = bad_date
        if read_err:
            r["数据读取失败"] = read_err
        return r

    def to_markdown(self, days=7):
        """报告文本（导出用；不写盘）"""
        r = self.report(days)
        lines = ["# 小6 情绪日报\n"]
        lines.append("**统计范围：** 最近 %s 天\n" % r.get("天数", days))
        if not r.get("记录数"):
            lines.append("\n%s\n" % r.get("说明", "暂无情绪记录"))
            if r.get("数据读取失败"):
                lines.append("\n> 数据读取失败：%s\n" % r["数据读取失败"])
            return "\n".join(lines)
        lines.append("- 记录数：%s 条" % r.get("记录数"))
        lines.append("- 主导情绪：%s" % "、".join(
            "%s（%s 次）" % (i["情绪"], i["次数"]) for i in r.get("主导情绪") or []))
        lines.append("- 建议：%s" % r.get("建议", ""))
        if r.get("日期异常"):
            lines.append("- 日期异常：%s 条（已跳过）" % r["日期异常"])
        lines.append("\n## 情绪分布\n")
        for mood, count in sorted((r.get("分布") or {}).items(),
                                  key=lambda kv: -kv[1]):
            lines.append("- %s：%s 次" % (mood, count))
        return "\n".join(lines) + "\n"

    def export_md(self, days=7, path=None):
        """把报告写到文件（默认 ``data/mood_report.md``）"""
        target = str(path or data_path(self.trunk, "mood_report.md"))
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
        return self.report(7)
