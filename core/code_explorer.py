# -*- coding: utf-8 -*-
"""代码 Agent 模型协议、patch 解析和探索工具。"""
from __future__ import annotations

import json
import os
import re
from core.agent_permissions import authorize_agent_action
from core.patch_engine import PatchError, sha256_file, validate_patch
from core.path_safety import safe_join

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class CodeExplorerMixin:
    @staticmethod
    def _extract_json(text):
        s = str(text or "").strip()
        if not s:
            return None
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
        if m:
            s = m.group(1)
        else:
            i, j = s.find("{"), s.rfind("}")
            if i >= 0 and j > i:
                s = s[i:j + 1]
        try:
            return json.loads(s)
        except Exception:
            return None

    def _parse_patch(self, text):
        data = text if isinstance(text, dict) else self._extract_json(text)
        if not isinstance(data, dict):
            raise PatchError("模型没有返回合法 JSON: " + str(text)[:160])
        if isinstance(data.get("patch"), dict):
            data = data["patch"]
        if not isinstance(data.get("files"), list):
            raise PatchError("模型回复不是 patch（缺少 files）")
        for fp in data["files"]:
            rel = str(fp.get("path") or "")
            p = os.path.join(self.root, rel.replace("/", os.sep))
            if os.path.isfile(p):
                fp.setdefault("base_hash", sha256_file(p))
        return validate_patch(self.root, data)

    def _tool_result(self, name, args):
        args = args or {}
        if name == "read_file":
            rel = str(args.get("path") or "").replace("\\", "/")
            p = safe_join(self.root, rel, must_exist=True)
            if not p or not os.path.isfile(p):
                return {"ok": False, "error": "文件不存在或越界: " + rel}
            start = max(1, int(args.get("start") or 1))
            limit = max(1, min(400, int(args.get("limit") or 160)))
            return {"ok": True, "path": rel,
                    "content": self._read_snippet(p, rel, start, limit)}
        if name == "grep":
            q = str(args.get("query") or args.get("pattern") or "").strip()
            if not q:
                return {"ok": False, "error": "grep 缺少 query"}
            hits = self.index.search_text(q, max_hits=int(args.get("limit") or 80))
            return {"ok": True, "hits": hits}
        if name == "list_files":
            rel = str(args.get("path") or ".").replace("\\", "/")
            p = safe_join(self.root, rel, must_exist=True)
            if not p or not os.path.isdir(p):
                return {"ok": False, "error": "目录不存在或越界: " + rel}
            items = []
            for name_ in sorted(os.listdir(p))[:200]:
                items.append(name_ + ("/" if os.path.isdir(os.path.join(p, name_)) else ""))
            return {"ok": True, "path": rel, "items": items}
        if name == "find_symbols":
            syms = self.index.find_symbols(
                str(args.get("query") or ""), 40,
                kind=args.get("kind"), file=args.get("file"))
            return {"ok": True, "symbols": syms,
                    "engine": "ast/regex/tree-sitter"}
        if name == "run_command":
            cmd = str(args.get("cmd") or "").strip()
            if not cmd:
                return {"ok": False, "error": "run_command 缺少 cmd"}
            action = {"type": "shell", "risk": "high", "args": {"cmd": cmd},
                      "reason": "代码 Agent 探索命令"}
            gate = authorize_agent_action(
                self.trunk, "code_agent", action,
                title="代码 Agent 请求运行命令", detail=cmd)
            if not gate.get("allow"):
                return {"ok": False, "error": gate.get("reason")}
            r = self._run_command(
                cmd, timeout=int(args.get("timeout") or 120), sandboxed=True)
            return r
        return {"ok": False, "error": "未知工具: " + str(name)}

    def propose_patch(self, goal, context=None, previous_error="",
                      max_tool_rounds=6, two_role=None):
        """先探索、再修改；`two_role=False` 时退回单角色循环。"""
        llm = (getattr(self.trunk, "modules", {}) or {}).get("llm")
        if not llm:
            raise RuntimeError("LLM 未加载，无法生成代码修改")
        context = context or self.build_context(goal)
        from core.code_roles import (explore_project, modify_with_report,
                                     two_role_enabled)
        enabled = two_role_enabled(self.trunk) if two_role is None else bool(two_role)
        if enabled:
            report = explore_project(self, goal, context)
            if isinstance(report.get("patch"), dict):
                self._emit("explore_report", {
                    "step": "探索 Agent 直接给出方案",
                    "files": [f.get("path") for f in report["patch"].get("files", [])
                              if isinstance(f, dict)]})
                return self._parse_patch(report["patch"])
            self._emit("explore_report", {
                "step": "探索完成，交给修改 Agent",
                "tools": report.get("tools") or [],
                "report": str(report.get("report") or "")[:2000]})
            return modify_with_report(
                self, goal, context, previous_error, report.get("report"))
        return self._propose_single_role(
            llm, goal, context, previous_error, max_tool_rounds)

    def _propose_single_role(self, llm, goal, context, previous_error="",
                             max_tool_rounds=6):
        messages = self._llm_messages(goal, context, previous_error)
        for round_no in range(max_tool_rounds + 1):
            self._check_control()
            self._emit("model_request", {
                "step": "模型分析（第 %d 轮）" % (round_no + 1),
                "progress": 0.12 + round_no * 0.04})
            out = llm.chat(messages)
            data = self._extract_json(out)
            if isinstance(data, dict):
                if isinstance(data.get("patch"), dict):
                    data = data["patch"]
                if isinstance(data.get("files"), list):
                    return self._parse_patch(data)
                if data.get("done") is True:
                    raise PatchError("模型认为无需修改: " + str(data.get("message") or ""))
                tool = str(data.get("tool") or "")
                if tool:
                    result = self._tool_result(tool, data.get("args") or {})
                    self._emit("tool_result", {
                        "step": "工具 %s" % tool, "result": result})
                    messages.append({"role": "assistant", "content": str(out)[:4000]})
                    messages.append({"role": "user", "content":
                        "工具 %s 的结果：\n%s\n请继续。若要修改，请返回 patch JSON。"
                        % (tool, json.dumps(result, ensure_ascii=False)[:12000])})
                    continue
            # 兼容模型把 patch 包在 Markdown 中但 JSON 提取失败的情况。
            raise PatchError("模型没有返回 patch 或有效工具调用")
        raise PatchError("探索轮数超限，请缩小目标或提供测试命令")
