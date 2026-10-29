# -*- coding: utf-8 -*-
"""统一意图 schema + 三段式路由（批次 44.1）。

schema（docs/102 §3.12）::

    {"intent": "edit_code", "targets": [{"type": "file", "value": "a.py"}],
     "scope": "file", "constraints": ["不要改公开接口"], "risk": "medium"}

三段式：
    ① 规则档：斜杠命令 / 文件路径 / 符号 / 明确动词 —— 置信度高，零模型成本
    ② 小模型档：调用方注入 ``model_call(prompt) -> str``，解析 JSON；失败退回规则档
    ③ 追问档：置信度低于阈值时只问一个最关键的问题，不猜着执行

开关 ``nl.intent_v2`` = ``off | shadow | on``，默认 ``shadow``：
影子期只记录不改行为，保证命令中心与聊天路由与上一版完全一致。
"""
from __future__ import annotations

import json
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

INTENTS = ("open_file", "run_test", "explain", "fix_error", "edit_code",
           "refactor", "search", "undo", "plan", "chat")
CODE_INTENTS = frozenset(INTENTS) - {"chat"}
SAFE_INTENTS = frozenset(("open_file", "run_test", "explain", "search"))

SLASH = {
    "/open": "open_file", "/test": "run_test", "/explain": "explain",
    "/fix": "fix_error", "/code": "edit_code", "/refactor": "refactor",
    "/search": "search", "/undo": "undo", "/plan": "plan", "/chat": "chat",
}

RISK = {
    "open_file": "low", "run_test": "low", "explain": "low", "search": "low",
    "plan": "low", "chat": "low",
    "edit_code": "medium", "fix_error": "medium",
    "refactor": "high", "undo": "high",
}

_FILE_RE = re.compile(
    r"(?:[A-Za-z]:)?[\w.\-\\/]*[\w\-]\."
    r"(?:py|js|jsx|ts|tsx|go|rs|java|cs|md|json|yml|yaml|toml|ini|txt|"
    r"html|css|sql|sh|bat|ps1)\b", re.I)
_SYMBOL_RE = re.compile(r"`([A-Za-z_][\w.]*)`|@([A-Za-z_][\w.]*)")
_TEST_RE = re.compile(r"\b(test_[A-Za-z0-9_]+)\b")

_RULES = (
    ("undo", ("撤销", "回滚", "恢复刚才", "undo", "撤回")),
    ("fix_error", ("修复", "报错", "异常", "跑不通", "跑不过", "失败", "bug",
                   "修一下", "修好", "崩溃", "traceback", "stack trace")),
    ("run_test", ("跑测试", "运行测试", "跑一下测试", "测试一下", "单测",
                  "pytest", "run test", "跑单测")),
    ("explain", ("解释", "讲讲", "干嘛", "干什么", "什么意思", "为什么",
                 "who calls", "what does", "这段代码")),
    ("plan", ("计划", "方案", "步骤", "规划", "怎么做", "拆成几步")),
    ("refactor", ("重构", "拆分", "抽出来", "整理结构", "优化结构", "改结构")),
    ("search", ("搜索", "搜一下", "查一下", "找一下", "在哪", "哪里",
                "谁调用", "grep", "find")),
    ("open", ("打开", "跳到", "定位到", "看一下", "打开文件")),
    ("edit_code", ("改", "修改", "实现", "添加", "新增", "写", "生成",
                   "替换", "删除", "删掉", "重命名", "补上", "加一个",
                   "加个", "加上", "补一个", "格式化")),
)
_SNAKE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+)\b")
_TEST_PATH_RE = re.compile(r"(?:^|[\s/])(?:tests?/[^\s]+|test_[\w]+\.py)")


def _wants_run(low):
    return any(w in low for w in ("跑", "运行", "执行", "run", "pytest"))


def normalize_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def mode(trunk):
    """读开关：off / shadow / on；认不出按 shadow。"""
    try:
        value = str(trunk.rule("nl.intent_v2", "shadow") or "shadow").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "mode")
        return "shadow"
    return value if value in ("off", "shadow", "on") else "shadow"


def _targets(text):
    out, seen = [], set()

    def add(kind, value):
        value = str(value or "").strip().strip("。，,;；")
        if not value or (kind, value) in seen:
            return
        seen.add((kind, value))
        out.append({"type": kind, "value": value[:200]})

    file_values = []
    for match in _FILE_RE.findall(text):
        value = match.replace("\\", "/")
        if value.lower() in ("a.py", "x.py"):
            continue
        file_values.append(value)
        add("file", value)
    for sym in _SYMBOL_RE.findall(text):
        add("symbol", sym[0] or sym[1])
    for name in _SNAKE_RE.findall(text):
        if name.lower().endswith((".py", ".js", ".ts", ".md")):
            continue
        # 文件名里的下划线不是符号（core/agent_router.py → agent_router）
        if any(name in f for f in file_values):
            continue
        add("symbol", name)
    for name in _TEST_RE.findall(text):
        add("test", name)
    return out[:5]


def _scope(text, targets):
    low = text.lower()
    if any(w in text for w in ("选中", "这段", "这里", "刚才选")):
        return "selection"
    if any(w in low for w in ("整个项目", "全项目", "整个仓库", "所有文件")):
        return "project"
    if any(w in text for w in ("函数", "方法", "这个类")) and \
            not any(t["type"] == "file" for t in targets):
        return "function"
    return "file"


def _constraints(text):
    found = re.findall(r"(?:不要|别|不能|保持|必须)[^，。；;\n]{2,40}", text)
    return [x.strip()[:80] for x in found[:3]]


def _rule_stage(text):
    low = text.lower()
    if low.startswith("/"):
        head = low.split()[0]
        intent = SLASH.get(head)
        if intent:
            rest = text[len(head):].strip()
            return {"intent": intent, "confidence": 0.98,
                    "reason": "斜杠命令 %s" % head, "stage": "rule",
                    "rest": rest}
    if _TEST_PATH_RE.search(low) and _wants_run(low):
        return {"intent": "run_test", "confidence": 0.88,
                "reason": "测试路径 + 运行动词", "stage": "rule", "rest": ""}
    # 撤销短语优先于「改」：用户说撤销时，句子里往往也带着“修改”
    if any(w in low for w in ("撤销", "回滚", "撤回", "undo", "恢复刚才")):
        return {"intent": "undo", "confidence": 0.92,
                "reason": "撤销短语", "stage": "rule", "rest": ""}
    best, hits = "chat", []
    for intent, words in _RULES:
        matched = [w for w in words if w.lower() in low]
        if len(matched) > len(hits):
            best, hits = intent, matched
    if best == "open":
        best = "open_file"
    if not hits:
        # 只有路径/符号/测试名时，按出现的位置猜一个最保守的意图
        targets = _targets(text)
        if any(t["type"] == "file" for t in targets):
            return {"intent": "open_file", "confidence": 0.62,
                    "reason": "只提到文件", "stage": "rule", "rest": ""}
        return {"intent": "chat", "confidence": 0.3,
                "reason": "未命中工作台意图", "stage": "rule", "rest": ""}
    # 弱动词（“改一下这个”没说改什么）降置信度，交给追问档
    strong = best not in ("edit_code",) or len(text) >= 8
    confidence = 0.9 if (strong and len(hits) >= 2) else 0.78
    if any(w in text for w in ("这个", "这里", "这段")) and not _targets(text):
        confidence = min(confidence, 0.58)
    return {"intent": best, "confidence": confidence,
            "reason": "关键词：%s" % "、".join(hits[:4]),
            "stage": "rule", "rest": ""}


def classify_prompt(text, context=None):
    """给小模型的分类提示（意图 + 槽位），固定输出 JSON。"""
    ctx = context or {}
    files = ", ".join(str(x) for x in (ctx.get("open_files") or [])[:5])
    lines = [
        "把用户的话归到下列意图之一：" + "|".join(INTENTS),
        '只输出 JSON：{"intent": "...", "targets": [{"type": "file|symbol|test",'
        ' "value": "..."}], "scope": "file|selection|function|project",'
        ' "constraints": ["..."]}',
        "不要解释，不要 Markdown。",
        "当前文件：%s" % (files or "无"),
    ]
    if ctx.get("selection"):
        lines.append("选中内容前 200 字：%s" % str(ctx["selection"])[:200])
    if ctx.get("last_error"):
        lines.append("最近报错：%s" % str(ctx["last_error"])[:200])
    lines.append("用户：%s" % text)
    return "\n".join(lines)


def parse_model_json(raw):
    """从模型输出里抠出 JSON；坏输出返回 {}。"""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError) as e:
        _x6_swallowed(__name__, e, "parse_model_json")
        return {}
    return data if isinstance(data, dict) else {}


def _from_model(text, data, base):
    intent = str(data.get("intent") or "").strip().lower()
    if intent not in INTENTS:
        return {}
    targets = []
    for item in (data.get("targets") or [])[:5]:
        if isinstance(item, dict):
            value = str(item.get("value") or "").strip()
            kind = str(item.get("type") or "file").strip().lower()
            if value:
                targets.append({"type": kind, "value": value[:200]})
    scope = str(data.get("scope") or "").strip().lower()
    if scope not in ("file", "selection", "function", "project"):
        scope = ""
    constraints = [str(x)[:80] for x in (data.get("constraints") or [])[:3]
                   if str(x).strip()]
    return {"intent": intent, "confidence": 0.85,
            "reason": "小模型分类", "stage": "model",
            "rest": base.get("rest", ""), "targets": targets,
            "scope": scope, "constraints": constraints}


def clarify_question(info):
    """缺槽位时只问一个最关键的问题。"""
    intent = (info or {}).get("intent", "chat")
    has_file = any(t.get("type") == "file" for t in info.get("targets") or [])
    has_symbol = any(t.get("type") == "symbol"
                     for t in info.get("targets") or [])
    has_test = any(t.get("type") == "test" for t in info.get("targets") or [])
    if intent in ("open_file", "explain", "fix_error", "edit_code",
                  "refactor") and not (has_file or has_symbol):
        return "要动哪个文件或符号？给我一个文件名或函数名就行。"
    if intent == "run_test" and not has_test:
        return "跑哪个测试？说个测试文件名，或者回复「全部」。"
    if intent == "search" and not (info.get("query") or has_file):
        return "想搜什么关键词？"
    if intent == "undo":
        return "要撤销最近一次自动修改吗？"
    return "能再说清楚一点吗？比如要改哪个文件、想达成什么效果。"


def _risk(intent, text):
    risk = RISK.get(intent, "medium")
    if any(w in text for w in ("删除", "清空", "格式化", "所有文件",
                               "整个项目", "重命名")):
        risk = "high"
    return risk


def route(text, *, context=None, model_call=None, threshold=0.6):
    """三段式路由，返回 schema + confidence/reason/stage/clarify。"""
    original = normalize_text(text)
    base = _rule_stage(original)
    ctx = dict(context or {})
    info = dict(base)
    if model_call is not None and base.get("confidence", 0) < 0.75:
        try:
            data = parse_model_json(
                model_call(classify_prompt(original, ctx)))
        except Exception as e:
            _x6_swallowed(__name__, e, "model_call")
            data = {}
        merged = _from_model(original, data, base) if data else {}
        if merged:
            info.update(merged)
    targets = info.get("targets") or _targets(
        str(info.get("rest") or "") or original)
    scope = info.get("scope") or _scope(original, targets)
    constraints = info.get("constraints") or _constraints(original)
    confidence = float(info.get("confidence") or 0.0)
    result = {
        "text": original,
        "intent": info.get("intent", "chat"),
        "targets": targets,
        "scope": scope,
        "constraints": constraints,
        "risk": _risk(info.get("intent", "chat"), original),
        "confidence": round(confidence, 2),
        "reason": info.get("reason", ""),
        "stage": info.get("stage", "rule"),
        "query": "",
        "clarify": "",
    }
    if result["intent"] == "search":
        rest = str(info.get("rest") or "").strip()
        result["query"] = rest or re.sub(
            r"^(?:搜索|搜一下|查一下|找一下|帮我搜|搜|查|找)", "", original).strip()
    has_test = any(t.get("type") in ("test", "file")
                   for t in result["targets"])
    wants_all = any(w in original for w in ("全部", "所有", "全量"))
    missing_slot = (
        (result["intent"] == "run_test" and not has_test and not wants_all)
        or (result["intent"] == "search"
            and not result["query"] and not result["targets"]))
    if missing_slot:
        result["clarify"] = clarify_question(result)
        result["stage"] = "clarify"
    elif confidence < float(threshold or 0.6) and result["intent"] != "chat":
        result["clarify"] = clarify_question(result)
        result["stage"] = "clarify"
    result["auto_execute"] = bool(
        result["intent"] in SAFE_INTENTS and result["risk"] == "low"
        and result["confidence"] >= 0.8 and not result["clarify"])
    return result


def record_shadow(trunk, info, goal=""):
    """影子记录：只写会改什么，不执行；任何异常静默。"""
    try:
        payload = {"kind": "nl_intent", "goal": str(goal or "")[:120],
                   "intent": info.get("intent", ""),
                   "confidence": info.get("confidence", 0),
                   "stage": info.get("stage", ""),
                   "targets": [t.get("value") for t in
                               (info.get("targets") or [])][:5],
                   "risk": info.get("risk", "")}
        ctx = getattr(trunk, "ctx", None)
        if ctx is not None and hasattr(ctx, "record_shadow"):
            return bool(ctx.record_shadow(payload))
        rec = getattr(trunk, "record_shadow", None)
        if callable(rec):
            return bool(rec(payload))
    except Exception as e:
        _x6_swallowed(__name__, e, "record_shadow")
    return False
