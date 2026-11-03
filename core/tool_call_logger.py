# -*- coding: utf-8 -*-
"""P1-11: 工具调用日志（完整版）

2026-11-02 补的三件事
--------------------
1. **落盘**：原来只留最近 50 条在内存里，重启就没了 —— 用户问
   "刚才那个工具为什么失败"时什么都查不到。现在每条同时追加到
   ``data/tool_calls.jsonl``（超过 ``MAX_FILE_LINES`` 行自动瘦身，
   保留最近一半）。
2. **成败要落下来**：``tool_caller`` 调用失败时传进来的是一个异常对象，
   原来记成 ``result=str(异常)`` 但**没标失败**，日志里看不出哪次是坏的。
   现在按 ``ok`` 字段记录（不传就按"结果是异常 → 失败"推断）。
3. **按工具聚合**：``stats()`` 给出每个工具的调用次数/失败次数/平均耗时/
   最慢一次，``export_md`` 把这些写成一张表（这就是"有入口"）。
"""
import json
import os
import time

try:
    from core.data_paths import data_path
except ImportError:      # 独立脚本/测试环境没有 core 包时兜底
    def data_path(target, *parts):
        base = getattr(target, "base", None) or "."
        return os.path.join(base, "data", *parts)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

MAX_MEMORY = 200         # 内存里留最近多少条
MAX_FILE_LINES = 2000    # 文件超过这个行数就瘦身到最近一半


class ToolCallLogger:
    """记录工具调用，供可视化 / 导出 / 排障"""

    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = data_path(trunk, "tool_calls.jsonl")
        self.calls = []          # 最近 MAX_MEMORY 条
        self.last_error = ""

    # ------------------------------------------------------------------
    def log_call(self, tool, args, result, elapsed=0.0, ok=None):
        """记一次工具调用。

        ``ok`` 不传时按结论推断：结果是异常对象 → 失败，其余算成功
        （``tool_caller`` 就是把异常原样传进来的）。
        """
        name = str(tool or "").strip()
        if not name:
            return {"ok": False, "错误": "没给工具名，这次调用没记上"}
        failed = ok is False or (ok is None and isinstance(result, BaseException))
        entry = {
            "tool": name,
            "args": str(args)[:200],
            "result": str(result)[:200],
            "elapsed": round(float(elapsed or 0.0), 2),
            "ok": not failed,
            "time": time.strftime("%H:%M:%S"),
            "ts": round(time.time(), 3),
        }
        self.calls.append(entry)
        if len(self.calls) > MAX_MEMORY:
            self.calls = self.calls[-MAX_MEMORY:]

        err = self._append(entry)
        r = {"ok": not err, "调用数": len(self.calls)}
        if err:
            r["说明"] = err
        return r

    def _append(self, entry):
        """追加一行到日志文件；失败返回说明（内存记录仍然有效）"""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._shrink_if_needed()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e, "tool log append")
            self.last_error = "写工具日志失败：%s" % type(e).__name__
            return self.last_error
        return ""

    def _shrink_if_needed(self):
        """文件行数超过上限时只留最近一半（避免无限长大）"""
        try:
            if not os.path.exists(self.path):
                return
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) <= MAX_FILE_LINES:
                return
            keep = lines[-(MAX_FILE_LINES // 2):]
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(keep)
            os.replace(tmp, self.path)
        except Exception as e:
            # 瘦身失败不影响本次写入：文件大一点总比丢日志强
            _x6_swallowed(__name__, e, "tool log shrink")

    # ------------------------------------------------------------------
    def get_calls(self, limit=None):
        """内存里的最近调用（``limit`` 夹到 1..MAX_MEMORY）"""
        if limit is None:
            return self.calls
        try:
            n = int(limit)
        except (TypeError, ValueError):
            return self.calls
        n = max(1, min(MAX_MEMORY, n))
        return self.calls[-n:]

    def _read_file(self, limit=MAX_FILE_LINES):
        """读落盘日志（坏行计数）；读不出来给说明"""
        if not os.path.exists(self.path):
            return {"ok": False, "说明": "还没有工具调用日志", "调用": []}
        rows, bad = [], 0
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            return {"ok": False, "说明": "读日志失败：%s" % type(e).__name__,
                    "调用": []}
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                bad += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                bad += 1
        r = {"ok": True, "调用": rows}
        if bad:
            r["跳过"] = bad
            r["说明"] = "有 %d 行读不出来（已跳过）" % bad
        return r

    def stats(self):
        """按工具聚合：次数 / 失败 / 平均耗时 / 最慢"""
        got = self._read_file()
        rows = got.get("调用") or []
        agg = {}
        for row in rows:
            tool = str(row.get("tool") or "未知")
            item = agg.setdefault(tool, {"次数": 0, "失败": 0,
                                         "总耗时": 0.0, "最慢": 0.0})
            item["次数"] += 1
            if not row.get("ok", True):
                item["失败"] += 1
            try:
                cost = float(row.get("elapsed") or 0.0)
            except (TypeError, ValueError):
                cost = 0.0
            item["总耗时"] += cost
            item["最慢"] = max(item["最慢"], cost)
        out = {}
        for tool, item in agg.items():
            out[tool] = {"次数": item["次数"], "失败": item["失败"],
                         "平均耗时": round(item["总耗时"] / item["次数"], 2),
                         "最慢": round(item["最慢"], 2)}
        r = {"ok": got.get("ok", False), "总调用": len(rows),
             "总失败": sum(v["失败"] for v in out.values()), "按工具": out}
        if got.get("说明"):
            r["说明"] = got["说明"]
        return r

    def clear(self):
        """清内存（不动落盘日志：日志是证据）"""
        self.calls = []
        return {"ok": True}

    def to_markdown(self, limit=20):
        """最近调用 + 按工具统计（导出/界面入口）"""
        st = self.stats()
        lines = ["# 工具调用日志\n",
                 "- 总调用：%s 次（失败 %s 次）\n"
                 % (st.get("总调用", 0), st.get("总失败", 0))]
        if st.get("说明"):
            lines.append("> %s\n" % st["说明"])
        by_tool = st.get("按工具") or {}
        if by_tool:
            lines.append("\n## 按工具\n")
            lines.append("| 工具 | 次数 | 失败 | 平均耗时(s) | 最慢(s) |")
            lines.append("|---|---|---|---|---|")
            for tool, item in sorted(by_tool.items(),
                                     key=lambda kv: -kv[1]["次数"]):
                lines.append("| %s | %d | %d | %s | %s |"
                             % (tool, item["次数"], item["失败"],
                                item["平均耗时"], item["最慢"]))
        got = self._read_file()
        rows = (got.get("调用") or [])[-max(1, int(limit or 20)):]
        if rows:
            lines.append("\n## 最近 %d 次\n" % len(rows))
            for row in rows:
                lines.append("- %s %s（%s 秒）%s → %s"
                             % (row.get("time", ""), row.get("tool", ""),
                                row.get("elapsed", 0),
                                "成功" if row.get("ok", True) else "失败",
                                str(row.get("result", ""))[:60]))
        return "\n".join(lines) + "\n"

    def export_md(self, path=None, limit=20):
        path = path or data_path(self.trunk, "tool_calls.md")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self.to_markdown(limit=limit))
            os.replace(tmp, path)
        except Exception as e:
            _x6_swallowed(__name__, e, "export tool log md")
            return {"ok": False, "错误": "写不出去：%s: %s"
                                        % (type(e).__name__, str(e)[:60])}
        return {"ok": True, "文件": path}

    def run(self, *a):
        st = self.stats()
        return {"调用数": len(self.calls), "日志总数": st.get("总调用", 0),
                "总失败": st.get("总失败", 0),
                "最近": self.calls[-5:]}
