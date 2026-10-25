# -*- coding: utf-8 -*-
"""双角色代码 Agent：探索 Agent 先找信息，修改 Agent 再动手。

为什么不直接铺开多 Agent
------------------------
先把两个职责拆清楚就能拿到大部分收益：
* 探索 Agent 只读（工具白名单），目标是产出"文件 + 符号 + 命中片段"的报告；
* 修改 Agent 只写 patch，上下文里带探索报告和上一轮错误；
这样减少"还没看清代码就乱改"，也便于分别限制轮次和审计。

默认开启；配置 `code_agent.two_role=false` 或环境
`X6_CODE_AGENT_TWO_ROLE=0` 可退回单角色。
"""
from __future__ import annotations

import json
import os

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

EXPLORE_ROUNDS = 3


def _config_dict(trunk):
    cfg = getattr(trunk, "config", None) or {}
    sec = cfg.get("code_agent") if isinstance(cfg, dict) else None
    return sec if isinstance(sec, dict) else {}


def two_role_enabled(trunk):
    env = str(os.environ.get("X6_CODE_AGENT_TWO_ROLE", "")).lower()
    if env in ("0", "false", "off", "no"):
        return False
    return bool(_config_dict(trunk).get("two_role", True))


def explore_rounds(trunk):
    env = os.environ.get("X6_CODE_AGENT_EXPLORE_ROUNDS")
    try:
        n = int(env) if env else int(_config_dict(trunk).get("explore_rounds")
                                      or EXPLORE_ROUNDS)
    except (TypeError, ValueError):
        n = EXPLORE_ROUNDS
    return max(1, min(6, n))


_EXPLORE_SYSTEM = (
    "你是探索 Agent，只负责在真实代码库里找信息，不修改任何文件。\n"
    "只输出严格 JSON，不要 Markdown。三种返回之一：\n"
    "1) {\"tool\":\"read_file|grep|list_files|find_symbols|run_command\",\"args\":{...}}\n"
    "2) {\"report\":\"给修改 Agent 的结论（文件、符号、关键片段、注意事项）\"}\n"
    "3) 如果你已经能直接给出修改方案，返回 {\"files\":[...]}（上层会交给修改 Agent）\n"
    "规则：路径相对工作区；先用 find_symbols/grep 定位，再 read_file 确认；"
    "不要运行会修改文件的命令；信息够了就尽快给 report。"
)


def _explore_messages(agent, goal, context):
    system = _EXPLORE_SYSTEM
    user = ("目标：\n%s\n\n当前上下文：\n%s" % (
        goal, str(context.get("text") or "")[:16000]))
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def explore_project(agent, goal, context):
    """返回 {report, files, patch?, tools}；任何异常都降级为空报告。"""
    llm = (getattr(agent.trunk, "modules", {}) or {}).get("llm")
    if not llm:
        return {"report": "", "files": context.get("files") or [], "tools": []}
    messages = _explore_messages(agent, goal, context)
    tools = []
    report = ""
    for round_no in range(1, explore_rounds(agent.trunk) + 1):
        agent._check_control()
        agent._emit("role", {"role": "explore", "step": "探索 Agent 第 %d 轮"
                             % round_no})
        try:
            out = agent._llm_chat(llm, messages)
        except Exception as e:  # 静默是故意的 - 探索失败由单角色兜底
            # 用户取消不是探索失败，必须继续向上传播。
            if getattr(agent, "_cancel", None) is not None and agent._cancel.is_set():
                raise
            _x6_swallowed(__name__, e, "explore agent chat")
            return {"report": "", "files": [], "tools": tools,
                    "error": str(e)[:200]}
        data = agent._extract_json(out)
        if not isinstance(data, dict):
            report = str(out or "")[:6000]
            break
        if isinstance(data.get("files"), list):
            return {"report": report, "files": data.get("files"),
                    "patch": data, "tools": tools}
        if data.get("report"):
            report = str(data.get("report"))[:6000]
            break
        if data.get("done") is True:
            report = str(data.get("message") or "")[:6000]
            break
        tool = str(data.get("tool") or "")
        if not tool:
            report = json.dumps(data, ensure_ascii=False)[:4000]
            break
        result = agent._tool_result(tool, data.get("args") or {})
        tools.append(tool)
        agent._emit("tool_result", {"step": "探索工具 " + tool,
                                    "result": result})
        messages.append({"role": "assistant", "content": str(out)[:4000]})
        messages.append({"role": "user", "content":
                         "工具 %s 结果：\n%s\n请继续探索，或给出 report。"
                         % (tool, json.dumps(result, ensure_ascii=False)[:12000])})
    if not report:
        report = "探索未给出结论；请优先查看这些文件：" + \
                 ", ".join(str(x) for x in (context.get("files") or [])[:12])
    return {"report": report, "files": context.get("files") or [],
            "tools": tools}


_MODIFY_SYSTEM = (
    "你是修改 Agent。基于探索报告做最小、可测试的修改。\n"
    "只输出严格 JSON：{\"goal\":\"...\",\"files\":[{\"op\":\"update|create|delete|rename|write\","
    "\"path\":\"相对路径\",\"new_path\":\"重命名时填写\",\"content\":\"create/write时填写\","
    "\"hunks\":[{\"old\":\"原文唯一片段\",\"new\":\"替换内容\",\"reason\":\"原因\"}]}],"
    "\"tests\":[\"可选测试命令\"]}\n"
    "规则：路径相对工作区；不要动 .git/data/backups；"
    "update 的 old 必须从文件内容原样复制（含缩进）且唯一；"
    "优先小改动；不确定就先用 read_file 工具确认。"
)


def modify_with_report(agent, goal, context, previous_error, report,
                       max_rounds=4, previous_diff=""):
    llm = (getattr(agent.trunk, "modules", {}) or {}).get("llm")
    if not llm:
        raise RuntimeError("LLM 未加载，无法生成代码修改")
    user = ("目标：\n%s\n\n探索报告：\n%s\n\n项目上下文：\n%s" % (
        goal, str(report or "")[:12000],
        str(context.get("text") or "")[:12000]))
    if previous_diff:
        user += ("\n\n上一轮已应用的改动（请在此基础上修复，"
                 "不要重复同样的修改）：\n" + str(previous_diff)[-4000:])
    if previous_error:
        user += "\n\n上一轮测试失败：\n" + str(previous_error)[-6000:]
    messages = [{"role": "system", "content": _MODIFY_SYSTEM},
                {"role": "user", "content": user}]
    for round_no in range(1, max(1, int(max_rounds)) + 1):
        agent._check_control()
        agent._emit("role", {"role": "modify", "step": "修改 Agent 第 %d 轮"
                             % round_no})
        out = agent._llm_chat(llm, messages)
        data = agent._extract_json(out)
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("patch"), dict):
            data = data["patch"]
        if isinstance(data.get("files"), list):
            return agent._parse_patch(data)
        tool = str(data.get("tool") or "")
        if tool:
            result = agent._tool_result(tool, data.get("args") or {})
            messages.append({"role": "assistant", "content": str(out)[:4000]})
            messages.append({"role": "user", "content":
                             "工具 %s 结果：\n%s\n请继续，然后给出 patch。"
                             % (tool, json.dumps(result, ensure_ascii=False)[:12000])})
            continue
        if data.get("done") is True:
            from core.patch_engine import PatchError
            raise PatchError("模型认为无需修改: " + str(data.get("message") or ""))
    from core.patch_engine import PatchError
    raise PatchError("修改 Agent 未返回有效 patch")
