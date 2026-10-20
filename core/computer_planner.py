# -*- coding: utf-8 -*-
"""电脑 Agent 单步/多步规划和 JSON 解析。"""
from __future__ import annotations

import json
import re
from core.action_schema import ActionError, action_summary, validate_action

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class ComputerPlannerMixin:
    @staticmethod
    def _parse_plan_json(text):
        s = str(text or "").strip()
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
        if m:
            s = m.group(1)
        else:
            i, j = s.find("{"), s.rfind("}")
            if i >= 0 and j > i:
                s = s[i:j + 1]
        try:
            return json.loads(s)
        except Exception as e:
            raise ActionError("模型没有返回合法任务计划 JSON: " + str(e)[:120]) from None

    def plan_goal(self, goal, snapshot=None, feedback=""):
        """让 LLM 生成首轮跨应用计划。后续失败会由 replan 修正。"""
        llm = (getattr(self.trunk, "modules", {}) or {}).get("llm")
        if not llm:
            raise RuntimeError("LLM 未加载，无法生成电脑任务计划")
        snap = snapshot or self.observe()
        hits = self.ground(goal, snap)
        elements = self._candidate_prompt(snap, hits, 80)
        prompt = (
            "你是电脑操作规划器。只输出 JSON，不要解释。\n"
            "格式：{\"actions\":[{\"type\":\"click|type|hotkey|press_key|scroll|drag|"
            "open_app|open_url|activate_window|close_window|screenshot|"
            "read_file|write_file|edit_file|delete_file|copy_file|move_file|"
            "clipboard_get|clipboard_set|wait|wait_for|browser_open|browser_click|"
            "browser_type|browser_text|browser_screenshot|browser_wait|shell\","
            "\"target\":{\"element_id\":\"优先填候选id\",\"name\":\"控件名\","
            "\"rect\":[x,y,w,h],\"selector\":\"浏览器DOM选择器\"},"
            "\"args\":{},\"verify\":{\"type\":\"none|window_title|control_visible|"
            "text_changed|element_value|file_exists|file_changed|file_contains|"
            "exit_code|url_contains|screenshot_diff\",\"expected\":\"\"},"
            "\"risk\":\"low|medium|high\",\"reason\":\"为什么做\"}]}。\n"
            "约束：每次只做一个可验证动作；优先 UIA element_id；"
            "浏览器任务优先 browser_* + selector，不要盲点坐标；"
            "不要生成 shell/write_file 等高危动作，除非目标明确要求。\n"
            "当前窗口：%s\n屏幕信息：%s\n浏览器：%s\n"
            "候选元素：%s\n目标：%s\n反馈：%s"
            % (snap.get("active_window", ""),
               json.dumps(snap.get("screen") or {}, ensure_ascii=False),
               json.dumps(snap.get("browser") or {}, ensure_ascii=False),
               json.dumps(elements, ensure_ascii=False)[:12000], goal,
               str(feedback or "")[:2000]))
        out = llm.chat([{"role": "system",
                         "content": "你是严谨的跨应用电脑操作规划器。"},
                        {"role": "user", "content": prompt}])
        data = self._parse_plan_json(out)
        raw_actions = data.get("actions") if isinstance(data, dict) else data
        if not isinstance(raw_actions, list):
            raise ActionError("任务计划缺少 actions 数组")
        actions = []
        for raw in raw_actions[:20]:
            if not isinstance(raw, dict):
                continue
            raw.setdefault("action_id", "act_plan_%d" % len(actions))
            raw.setdefault("verify", {"type": "none"})
            raw.setdefault("risk", "medium")
            raw.setdefault("target", {})
            raw.setdefault("args", {})
            actions.append(validate_action(raw))
        if not actions:
            raise ActionError("模型没有生成可执行动作")
        return actions

    def plan_next(self, goal, snapshot, history=None, feedback=""):
        """动态循环的单步规划：只决定下一步，或宣布完成。"""
        llm = (getattr(self.trunk, "modules", {}) or {}).get("llm")
        if not llm:
            raise RuntimeError("LLM 未加载，无法规划下一步")
        hits = self.ground(goal, snapshot)
        candidates = self._candidate_prompt(snapshot, hits, 50)
        hist = []
        for x in (history or [])[-10:]:
            hist.append({
                "action": action_summary(x.get("action") or {})
                if (x.get("action") or {}).get("type") else "",
                "ok": bool((x.get("result") or {}).get("ok")),
                "verified": bool((x.get("verified") or {}).get("ok")),
                "reason": (x.get("verified") or {}).get("reason", ""),
            })
        prompt = (
            "你是电脑操作 Agent。根据最新屏幕和已执行历史，只决定下一步。"
            "只输出 JSON：{\"done\":false,\"thought\":\"简述\",\"action\":{"
            "\"type\":\"...\",\"target\":{...},\"args\":{...},"
            "\"verify\":{\"type\":\"...\",\"expected\":\"...\"},"
            "\"risk\":\"low|medium|high\",\"reason\":\"...\"}}。"
            "如果目标已经完成，输出 {\"done\":true,\"message\":\"完成摘要\"}。\n"
            "动作类型：click/type/hotkey/press_key/scroll/drag/open_app/open_url/"
            "activate_window/close_window/screenshot/read_file/write_file/edit_file/"
            "delete_file/copy_file/move_file/clipboard_get/clipboard_set/wait/wait_for/"
            "browser_open/browser_click/browser_type/browser_text/browser_screenshot/"
            "browser_wait/shell。\n"
            "优先使用 element_id 或 rect；浏览器优先 selector；不要一次输出多个动作。\n"
            "当前窗口：%s\n候选：%s\n历史：%s\n目标：%s\n反馈：%s"
            % (snapshot.get("active_window", ""),
               json.dumps(candidates, ensure_ascii=False)[:10000],
               json.dumps(hist, ensure_ascii=False)[:6000], goal,
               str(feedback or "")[:2000]))
        out = llm.chat([
            {"role": "system", "content": "你是严谨的电脑操作单步规划器。"},
            {"role": "user", "content": prompt}])
        data = self._parse_plan_json(out)
        if not isinstance(data, dict):
            raise ActionError("单步计划必须是 JSON 对象")
        if data.get("done"):
            return {"done": True, "message": str(data.get("message") or "目标完成")}
        raw = data.get("action") or data
        if not isinstance(raw, dict) or not raw.get("type"):
            raise ActionError("单步计划缺少 action")
        raw.setdefault("verify", {"type": "none"})
        raw.setdefault("risk", "medium")
        raw.setdefault("target", {})
        raw.setdefault("args", {})
        return {"done": False, "action": validate_action(raw),
                "thought": str(data.get("thought") or "")}
