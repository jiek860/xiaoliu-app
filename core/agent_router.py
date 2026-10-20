# -*- coding: utf-8 -*-
"""统一 Agent 入口的自然语言路由。

路由只负责选执行域，不代替规划器：
    code     -> 代码 Agent（仓库、patch、测试）
    computer -> 电脑 Agent（UIA/OCR/浏览器/文件/应用）
    chat     -> 普通对话
"""
from __future__ import annotations

import re


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


def route_goal(goal, *, has_code_root=True, explicit=None):
    """返回 {kind, confidence, reason, scores}。"""
    text = str(goal or "").strip()
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
    if re.search(r"```|(?:^|\s)(?:[\w\-/]+/)+[\w\-]+\.(?:py|js|ts|tsx|go|rs|java|cs)", text):
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
