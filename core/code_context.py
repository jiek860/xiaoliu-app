# -*- coding: utf-8 -*-
"""代码 Agent 项目上下文、符号和 snippet 构建。"""
from __future__ import annotations

import os
import re
from core.path_safety import safe_join
from core.workspace_index import WorkspaceIndex

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class CodeContextMixin:
    def _goal_terms(self, goal):
        terms = []
        for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", goal or ""):
            if w.lower() not in ("the", "and", "for", "with", "this", "that"):
                terms.append(w)
        chinese = re.findall(r"[\u4e00-\u9fff]{2,}", goal or "")
        for chunk in chinese:
            if len(chunk) <= 4:
                terms.append(chunk)
            else:
                for i in range(0, min(len(chunk) - 1, 10), 2):
                    terms.append(chunk[i:i + 3])
        out = []
        for t in terms:
            if t and t not in out:
                out.append(t)
        return out[:16]

    def _read_snippet(self, path, rel, start=1, limit=140):
        try:
            lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            return ""
        start = max(1, int(start))
        seg = lines[start - 1:start - 1 + limit]
        return "\n".join("%5d| %s" % (start + i, s)
                         for i, s in enumerate(seg))

    def build_context(self, goal, max_files=22, max_chars=24000):
        try:
            if self.index.data.get("files"):
                self.index.refresh()
            else:
                self.index.rebuild()
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        scores: dict[str, int] = {}
        hit_lines: dict[str, int] = {}
        for term in self._goal_terms(goal):
            for h in self.index.search_text(term, max_hits=40):
                f = h["file"]
                scores[f] = scores.get(f, 0) + 3
                hit_lines.setdefault(f, h["line"])
            for sym in self.index.find_symbols(term, 20):
                f = sym.get("file")
                if f:
                    scores[f] = scores.get(f, 0) + 2
                    hit_lines.setdefault(f, sym.get("line", 1))

        # 当前打开文件、最近修改文件、测试关联文件都要进入候选。
        for rel in self.open_files:
            rel = os.path.relpath(rel, self.root).replace("\\", "/") \
                if os.path.isabs(rel) else rel.replace("\\", "/")
            if os.path.isfile(os.path.join(self.root, rel)):
                scores[rel] = scores.get(rel, 0) + 10
        for item in self.index.recent_files(20):
            rel = item.get("path")
            if rel:
                scores[rel] = scores.get(rel, 0) + 1
        for rel in list(scores):
            for t in self.index.related_tests(rel)[:3]:
                scores[t] = scores.get(t, 0) + 4

        files = sorted(scores, key=lambda x: -scores[x])[:max_files]
        chunks, used = [], 0
        if self.selection.strip():
            chunks.append("=== USER SELECTION ===\n" + self.selection[:6000])
            used += len(chunks[-1])
        for rel in files:
            p = safe_join(self.root, rel.replace("/", os.sep), must_exist=True)
            if not p or not os.path.isfile(p):
                continue
            outline = ""
            syms = self.index.find_symbols(os.path.splitext(os.path.basename(rel))[0], 20)
            syms = [s for s in syms if s.get("file") == rel]
            if syms:
                outline = "\n".join(
                    "  - %s %s (L%s-L%s)" % (
                        s.get("kind"), s.get("name"), s.get("line"),
                        s.get("end_line")) for s in syms[:20])
            line = int(hit_lines.get(rel) or 1)
            snippet = self._read_snippet(p, rel, max(1, line - 40), 130)
            block = "\n\n=== FILE: %s ===\n" % rel
            if outline:
                block += "OUTLINE:\n%s\n" % outline
            block += snippet
            if used + len(block) > max_chars:
                break
            chunks.append(block)
            used += len(block)
        return {"files": files, "text": "".join(chunks),
                "symbols": {"recent": self.index.find_symbols("", 30)}}

    def _llm_messages(self, goal, context, previous_error=""):
        system = (
            "你是代码修改 Agent。先探索，再最小修改，最后交给测试验证。\n"
            "只输出严格 JSON，不要 Markdown 解释。可以返回以下三类之一：\n"
            "1) 探索工具：{\"tool\":\"read_file|grep|list_files|find_symbols|run_command\","
            "\"args\":{...}}\n"
            "2) 修改方案：{\"goal\":\"...\",\"files\":[{\"op\":\"update|create|delete|rename|write\","
            "\"path\":\"相对路径\",\"new_path\":\"重命名时填写\",\"content\":\"create/write时填写\","
            "\"hunks\":[{\"old\":\"原文唯一片段\",\"new\":\"替换内容\",\"reason\":\"原因\"}]}],"
            "\"tests\":[\"可选测试命令\"]}\n"
            "3) 完成：{\"done\":true,\"message\":\"结果摘要\"}\n"
            "规则：路径必须相对工作区；不要动 .git/data/backups；"
            "update 的 old 必须能唯一匹配；优先小改动；需要更多信息就先用工具。"
        )
        user = ("目标：\n%s\n\n已收集上下文：\n%s" % (goal, context.get("text", "")))
        if previous_error:
            user += "\n\n上一轮测试失败：\n" + previous_error[-6000:]
        return [{"role": "system", "content": system},
                {"role": "user", "content": user}]
