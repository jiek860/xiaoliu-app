# -*- coding: utf-8 -*-
"""P2-10: 梦境系统 - 每天生成一个梦；第 4 批起兼做"会话结束的记忆巩固"。"""
import os, json, random
from datetime import datetime

from core.data_paths import data_path

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


DREAM_TEMPLATES = [
    "我梦见我们在一个巨大的图书馆里，书架一直延伸到天上，你在找一本写着我们故事的书。",
    "我梦见我们在海边，浪很大，但是我们站在岸上一点也不害怕，风把你的头发吹起来了。",
    "我梦见我们在一个小咖啡馆里，阳光很好，你在给我讲今天发生的事，我听得很认真。",
    "我梦见我们在一个飘着云的山上，脚下是软软的云，你说要带我去看星星。",
    "我梦见我们在一个老房子里，窗外下着雨，我们在壁炉边烤火，很暖和。",
]


class DreamSystem:
    """梦境生成 + 记忆巩固"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = data_path(self, "dreams.jsonl")

    def generate_dream(self):
        """生成今天的梦"""
        dream = random.choice(DREAM_TEMPLATES)
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "dream": dream,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def consolidate(self, messages=None, *, now=None, dry_run=False):
        """会话结束：把这段对话沉淀成长期记忆（第 4 批深度②）。

        真正的提炼逻辑在 ``core.pipeline.memory_consolidation``（纯规则、零模型），
        这里只负责"会话结束时被叫到"并在 dreams.jsonl 留一条巩固记录 ——
        「做过梦」和「记住了什么」能对上，不至于记忆悄悄变多却查不到来源。
        任何异常都返回写入 0，不影响聊天。
        """
        try:
            from core.pipeline.memory_consolidation import consolidate_session
            result = consolidate_session(messages or [], base=self.base, now=now,
                                         dry_run=dry_run)
        except Exception as e:
            _x6_swallowed(__name__, e, "consolidate")
            return {"written": 0, "cards": [], "skipped": [], "conflicts": [],
                    "dry_run": bool(dry_run)}
        if dry_run or not result.get("written"):
            return result
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "dream": "今晚把今天聊到的 %d 件事收进长期记忆了"
                     % int(result.get("written") or 0),
            "consolidated": [str(c.get("text") or "")[:40]
                             for c in (result.get("cards") or [])][:5],
        }
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e, "dream_write")
        result["dream"] = entry
        return result

    def get_recent_dreams(self, count=10):
        """获取最近的梦

        ``count`` 会夹到 1..200：0 或负数原来会让 ``readlines()[-0:]`` 变成
        整个文件，等于「要 0 条却返回全部」。
        """
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 10
        count = max(1, min(200, count))
        rows, _skipped = self._read_all(limit=count)
        return rows

    def _read_all(self, limit=None):
        """读梦境记录；返回 (条目列表, 坏行数)。

        坏行跳过（一行坏了不该让整个「看梦」失败），但**要报数** ——
        否则「还没做过梦」和「记录全坏了」分不清。
        """
        if not os.path.exists(self.path):
            return [], 0
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            _x6_swallowed(__name__, e, "read_dreams")
            return [{"说明": "梦境记录读不出来：%s" % str(e)[:60]}], 0
        if limit:
            lines = lines[-limit:]
        dreams, skipped = [], 0
        for ln in lines:
            text = ln.strip()
            if not text:
                continue
            try:
                dreams.append(json.loads(text))
            except Exception:
                skipped += 1
        if skipped:
            dreams.append({"说明": "有 %d 行梦境记录读不出来，已跳过" % skipped})
        return dreams, skipped

    def to_markdown(self, count=10):
        """梦境清单的 Markdown（记忆页「梦境」标签与导出共用）"""
        rows = self.get_recent_dreams(count)
        lines = ["# 小6 的梦\n"]
        if not rows:
            lines.append("还没有做过梦（每晚第一次空闲时会做一个）。\n")
            return "\n".join(lines)
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("说明"):
                lines.append("> %s\n" % row["说明"])
                continue
            date = str(row.get("date") or "?")
            dream = str(row.get("dream") or "").strip() or "（空的梦）"
            lines.append("- **%s**：%s" % (date, dream))
            for item in (row.get("consolidated") or [])[:5]:
                lines.append("  - 记住了：%s" % item)
        return "\n".join(lines) + "\n"

    def export_md(self, count=10, path=None):
        """把梦境清单写到文件（默认 ``data/dreams.md``）"""
        target = str(path or data_path(self.trunk, "dreams.md"))
        try:
            folder = os.path.dirname(target)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self.to_markdown(count))
            os.replace(tmp, target)
        except Exception as e:
            return {"ok": False, "msg": "写梦境清单失败：%s: %s"
                                       % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "path": target}

    def run(self, *a):
        # 先做梦再数：原来的字典字面量是从左到右求值，
        # "梦数" 在 generate_dream() 之前就数好了，永远少算刚做的这一个
        entry = self.generate_dream()
        return {"梦数": len(self.get_recent_dreams()),
                "今天的梦": entry["dream"][:50]}
