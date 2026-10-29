# -*- coding: utf-8 -*-
"""统一 Agent 入口的自然语言路由。

路由只负责选执行域，不代替规划器：
    code     -> 代码 Agent（仓库、patch、测试）
    computer -> 电脑 Agent（UIA/OCR/浏览器/文件/应用）
    chat     -> 普通对话
"""
from __future__ import annotations

import os
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None


CODE_WORDS = (
    "代码", "函数", "类", "模块", "项目", "仓库", "编译", "重构", "报错",
    "异常", "堆栈", "测试", "单测", "pytest", "ruff", "lint", "bug", "修复",
    "实现", "新增", "添加", "删除", "重命名", "接口", "import", "git",
    "python", "javascript", "typescript", "java", "go", "rust", "c++",
    "test_", ".py", ".js", ".ts", ".tsx", ".go", ".rs",
)
COMPUTER_WORDS = (
    "打开", "点击", "双击", "输入", "窗口", "浏览器", "网页", "网址", "登录",
    "搜索", "截图", "鼠标", "键盘", "快捷键", "应用", "软件", "桌面", "文件夹",
    "资源管理器", "记事本", "计算器", "微信", "钉钉", "浏览器", "chrome",
    "edge", "excel", "word", "ppt", "wps", "填表", "下载", "上传", "拖拽",
    "滚动", "电脑", "屏幕", "界面", "按钮",
)
CHAT_WORDS = ("你好", "谢谢", "解释", "为什么", "区别", "建议", "是什么")


def _score(text, words):
    low = str(text or "").lower()
    score = 0
    hits = []
    for w in words:
        if w.lower() in low:
            score += 2 if len(w) >= 3 else 1
            hits.append(w)
    return score, hits


def route_goal(goal, *, has_code_root=True, explicit=None, trunk=None,
               context=None):
    """返回 {kind, confidence, reason, scores}。

    传入 ``trunk`` 时叠加批次 44.1 的 NL 意图层（开关 ``nl.intent_v2``）：
        off    —— 完全走原三词表，行为与旧版一致
        shadow —— 只把 NL 结果记进影子日志，``kind`` 不变（默认）
        on     —— 原三词表仍先跑；只有“代码域 + 明确工作台意图 + 置信度
                  ≥0.8 + 带文件/符号目标”时才保留/升级为 code，绝不抢占
                  computer 域，也不会自动执行任何破坏性动作
    """
    text = str(goal or "").strip()
    result = _route_by_words(text, has_code_root=has_code_root,
                             explicit=explicit)
    if trunk is None:
        return result
    try:
        from core.nl import intent as nl
        mode = nl.mode(trunk)
        if mode == "off":
            return result
        info = nl.route(text, context=context, threshold=0.62)
        if mode == "shadow":
            nl.record_shadow(trunk, info, text)
            merged = dict(result)
            merged["nl"] = info
            return merged
        return _merge_nl(result, info)
    except Exception as e:
        _x6_swallowed(__name__, e, "nl intent layer")
        return result


def _merge_nl(result, info):
    """NL 只做加法：不抢电脑域、不自动执行，风险高的意图保留原路由。"""
    out = dict(result)
    out["nl"] = info
    intent = info.get("intent", "chat")
    has_target = any(t.get("type") in ("file", "symbol", "test")
                     for t in info.get("targets") or [])
    confident = float(info.get("confidence") or 0) >= 0.8
    if out.get("kind") == "code" and intent in ("open_file", "run_test",
                                                 "explain", "fix_error",
                                                 "edit_code", "refactor",
                                                 "plan", "undo", "search"):
        out["reason"] = "%s / 意图:%s" % (out.get("reason", ""), intent)
        return out
    if out.get("kind") in ("chat", "computer") and has_target and confident \
            and intent in ("fix_error", "edit_code", "refactor", "run_test",
                           "explain", "open_file", "plan", "undo", "search"):
        out.update({"kind": "code", "confidence": info.get("confidence", 0.8),
                    "reason": "NL 意图:%s" % intent})
    return out


_CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".cs")


def _looks_like_code_path(text):
    """文本里是否有“目录/文件.py”这类路径（线性扫描，避免正则回溯）。"""
    s = str(text or "")
    if "```" in s:
        return True
    for part in re.split(r"[^\w\-./]+", s):
        if "/" in part and part.rstrip("/").endswith(_CODE_EXTS):
            return True
    return False


def _route_by_words(text, *, has_code_root=True, explicit=None):
    """原三词表规则档（批次 44 起作为 NL 的第一段）。"""
    text = str(text or "").strip()
    if explicit in ("code", "computer", "chat"):
        return {"kind": explicit, "confidence": 1.0,
                "reason": "用户显式指定", "scores": {}}
    low = text.lower()
    if low.startswith("/code ") or low.startswith("代码："):
        return {"kind": "code", "confidence": 1.0,
                "reason": "斜杠命令 /code", "scores": {}}
    if low.startswith("/pc ") or low.startswith("/computer "):
        return {"kind": "computer", "confidence": 1.0,
                "reason": "斜杠命令 /pc", "scores": {}}
    if low.startswith("/chat "):
        return {"kind": "chat", "confidence": 1.0,
                "reason": "斜杠命令 /chat", "scores": {}}

    code, code_hits = _score(text, CODE_WORDS)
    pc, pc_hits = _score(text, COMPUTER_WORDS)
    chat, chat_hits = _score(text, CHAT_WORDS)

    # 明确的开发上下文：项目 / 文件路径 / 代码块。
    if _looks_like_code_path(text):
        code += 4
    if re.search(r"[A-Za-z]:\\|(?:^|\s)\.{0,2}/", text):
        pc += 1

    # 打开某个代码文件通常是电脑操作；修复/实现代码才是代码 Agent。
    if code and any(w in text for w in ("修复", "实现", "重构", "测试", "编译")):
        code += 3
    if pc and any(w in text for w in ("然后", "并把", "接着", "之后")):
        pc += 2

    if not has_code_root:
        code = 0
    scores = {"code": code, "computer": pc, "chat": chat}
    best = max(scores, key=lambda k: scores[k])
    total = max(1, sum(max(0, v) for v in scores.values()))
    confidence = round(scores[best] / total, 2)
    reason = "关键词：%s" % "、".join(
        (code_hits if best == "code" else pc_hits if best == "computer"
         else chat_hits)[:5])
    if scores[best] <= 0:
        return {"kind": "chat", "confidence": 0.35,
                "reason": "未命中专用 Agent 特征", "scores": scores}
    if confidence < 0.45:
        return {"kind": "chat", "confidence": confidence,
                "reason": "置信度不足：" + reason, "scores": scores}
    return {"kind": best, "confidence": confidence,
            "reason": reason, "scores": scores}


def route_label(info):
    kind = (info or {}).get("kind", "chat")
    return {"code": "代码 Agent", "computer": "电脑 Agent",
            "chat": "对话"}.get(kind, "对话")


# ======================================================================
# 代码问答（批次 47.3）
# ----------------------------------------------------------------------
# 五种模板：解释 / 定位 / 影响面 / 用法 / 对比。回答一律带 `文件:行`
# 引用，工作台面板再把引用变成可点击跳转。
# 开关 ``code_qa.enabled`` 默认关：关着的时候一切走原路由，行为不变。
# 含"改/修复/实现"这类动作词的句子不算问答，仍交给代码 Agent。
# ======================================================================
QA_TEMPLATES = ("compare", "impact", "usage", "locate", "explain")
QA_TEMPLATE_WORDS = {
    "compare": ("区别", "不同", "对比", "差异", "相比", "不一样"),
    "impact": ("影响", "依赖", "调用方", "引用", "牵连", "波及", "改到"),
    "usage": ("怎么用", "怎么调用", "如何使用", "用法", "示例", "例子"),
    "locate": ("在哪", "在哪里", "位置", "哪个文件", "定位", "查找", "找到"),
    "explain": ("解释", "什么意思", "作用", "干嘛", "做什么", "原理"),
}
_QA_ACTION_WORDS = ("改", "修复", "实现", "添加", "新增", "删除", "重构",
                    "写一个", "写个", "生成", "新建", "重命名", "跑测试")
_QA_QUOTED_RE = re.compile(r"`([^`]{1,80})`")
_QA_FILE_RE = re.compile(
    r"([\w\-./\\]+\.(?:py|pyw|js|jsx|ts|tsx|go|rs|java|cs))")
_QA_IDENT_RE = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]{1,40})(\(\))?")
_QA_STOP = {
    "python", "python3", "javascript", "typescript", "java", "golang",
    "rust", "test", "tests", "pytest", "ruff", "lint", "git", "import",
    "code", "bug", "api", "json", "html", "css", "def", "class", "return",
    "true", "false", "none", "and", "the", "this", "that", "main",
}


def code_qa_enabled(trunk=None):
    """开关 ``code_qa.enabled``：默认关，读不到也按关处理。"""
    try:
        value = trunk.rule("code_qa.enabled", False) if trunk is not None \
            else False
    except Exception as e:
        _x6_swallowed(__name__, e, "code qa switch")
        value = False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "on", "true", "yes", "开")
    return bool(value)


def _question_targets(text):
    """从问题里抽目标：反引号 > 文件名 > 标识符，去重保序。"""
    out = []

    def add(name):
        name = str(name or "").strip().strip("`")
        if name and name not in out:
            out.append(name)

    for m in _QA_QUOTED_RE.finditer(text):
        add(m.group(1))
    for m in _QA_FILE_RE.finditer(text):
        add(m.group(1).replace("\\", "/"))
    for m in _QA_IDENT_RE.finditer(text):
        name = m.group(1)
        if name.lower() in _QA_STOP or name.isdigit():
            continue
        add(name)
    return out


def classify_code_question(goal):
    """识别代码问答模板；不是问答返回 None。

    ``compare`` 至少要两个目标，否则按 ``explain`` 处理；带动作词的
    句子直接返回 None（那是改代码，不是问代码）。
    """
    text = str(goal or "").strip()
    if not text or len(text) > 240:
        return None
    if any(w in text for w in _QA_ACTION_WORDS):
        return None
    low = text.lower()
    template = ""
    for name in QA_TEMPLATES:
        if any(w in low for w in QA_TEMPLATE_WORDS[name]):
            template = name
            break
    if not template:
        return None
    targets = _question_targets(text)
    if not targets:
        return None
    if template == "compare" and len(targets) < 2:
        template = "explain"
    return {"template": template, "targets": targets[:5],
            "confidence": round(min(1.0, 0.5 + 0.1 * len(targets)), 2)}


def _workspace_index(root):
    """没有索引就现场建一个（小项目可以接受；工作台会直接传躯干索引）。"""
    try:
        from core.workspace_index import WorkspaceIndex
        idx = WorkspaceIndex(str(root or "."), str(root or "."))
        if not (idx.data.get("files") or idx.data.get("symbols")):
            idx.refresh(max_files=2000)
        return idx
    except Exception as e:  # 静默是故意的 - 没索引就退回 Agent
        _x6_swallowed(__name__, e, "code qa index")
        return None


def _norm_rel(path):
    return str(path or "").replace("\\", "/")


def _collect_refs(index, targets, limit=5):
    """目标 -> [{path, line, symbol, kind}]，按 (path,line) 去重。"""
    refs, seen = [], set()
    for target in targets:
        rows = []
        if index is not None:
            try:
                if target.endswith((".py", ".js", ".ts", ".tsx", ".jsx")):
                    rows.append({"path": _norm_rel(target), "line": 1,
                                 "symbol": target, "kind": "file"})
                rows.extend({"path": _norm_rel(s.get("file")),
                             "line": int(s.get("line") or 1),
                             "symbol": str(s.get("name") or target),
                             "kind": str(s.get("kind") or "")}
                            for s in index.find_symbols(target, limit=limit))
            except Exception as e:  # 静默是故意的 - 索引坏了就少一条引用
                _x6_swallowed(__name__, e, "code qa find symbols")
        for row in rows:
            key = (row["path"], row["line"])
            if not row["path"] or key in seen:
                continue
            seen.add(key)
            refs.append(row)
        if len(refs) >= limit:
            break
    return refs[:max(1, int(limit or 1))]


def _symbol_detail(root, rel, line, max_lines=40):
    """读定义附近的签名与首行说明，让回答不只给一行行号。"""
    out = {"signature": "", "doc": ""}
    try:
        path = os.path.join(str(root or "."), rel)
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    start = max(0, int(line or 1) - 1)
    for i in range(start, min(len(lines), start + max_lines)):
        text = lines[i].strip()
        if not out["signature"] and re.match(r"(?:def|class|function|const|let)\b",
                                             text):
            out["signature"] = text[:120]
            for j in range(i + 1, min(len(lines), i + 6)):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith(('"""', "'''", '#')):
                    out["doc"] = nxt[:120]
                    break
                if nxt:
                    out["doc"] = nxt.strip('"\'').strip()[:120]
                    break
            break
    return out


def _render_answer(info, refs, index, root):
    tpl = info["template"]
    head = {"explain": "解释", "locate": "定位", "impact": "影响面",
            "usage": "用法", "compare": "对比"}[tpl]
    lines = ["【%s】%s" % (head, "、".join(info["targets"])),
             "共 %d 处引用：" % len(refs)]
    for ref in refs:
        extra = ""
        if tpl in ("explain", "usage", "compare"):
            detail = _symbol_detail(root, ref["path"], ref["line"])
            if detail["signature"]:
                extra = "  " + detail["signature"]
            elif detail["doc"]:
                extra = "  " + detail["doc"]
        kind = ("（%s）" % ref["kind"]) if ref["kind"] else ""
        lines.append("- `%s` `%s:%d`%s%s" % (
            ref["symbol"], ref["path"], ref["line"], kind, extra))
    if tpl == "impact" and index is not None:
        lines.append("相关测试：" + _related_test_hint(index, refs))
    elif tpl == "usage" and index is not None:
        lines.append("相关测试：" + _related_test_hint(index, refs))
    elif tpl == "compare":
        sigs = []
        for ref in refs[:2]:
            detail = _symbol_detail(root, ref["path"], ref["line"])
            sigs.append(detail["signature"] or ref["symbol"])
        if len(sigs) == 2:
            lines.append("差异：`%s` ↔ `%s`" % (sigs[0], sigs[1]))
    return "\n".join(lines)


def _related_test_hint(index, refs, limit=3):
    out = []
    for ref in refs[:limit]:
        try:
            tests = index.related_tests(ref["path"]) or []
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "code qa related tests")
            tests = []
        for test in tests[:limit]:
            if test not in out:
                out.append(test)
    return "、".join("`%s`" % t for t in out) if out else "未找到"


def answer_code_question(goal, *, root=".", index=None, limit=5):
    """本地索引回答代码问题；找不到引用时 ``ok=False``，调用方退回 Agent。"""
    info = classify_code_question(goal)
    if not info:
        return {"ok": False, "reason": "不是代码问题"}
    idx = index if index is not None else _workspace_index(root)
    refs = _collect_refs(idx, info["targets"], limit=limit)
    if not refs:
        return {"ok": False, "reason": "索引里没找到相关符号",
                "template": info["template"]}
    return {"ok": True, "template": info["template"], "targets": info["targets"],
            "answer": _render_answer(info, refs, idx, root), "refs": refs}
