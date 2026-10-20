# -*- coding: utf-8 -*-
"""UIA / OCR / 文本线索的元素 grounding。

输出统一带 `element_id`、`rect`、`source`、`confidence` 的候选。
执行器可以直接按 element_id 或 rect 定位，不再让模型臆造坐标。
"""
from __future__ import annotations

import hashlib
import re


_RECT_RE = re.compile(
    r"@\((?P<x>-?\d+),(?P<y>-?\d+),(?P<w>-?\d+),(?P<h>-?\d+)\)")


def _eid(source, name, rect, index=0):
    raw = "%s|%s|%s|%s" % (source, name, rect, index)
    return "%s_%s" % (source, hashlib.sha1(
        raw.encode("utf-8", errors="replace"),
        usedforsecurity=False).hexdigest()[:10])


def parse_uia_lines(text):
    """把 computer_controller.ui_dump 的结构文本转成候选元素。"""
    out = []
    pat = re.compile(
        r"^(?P<indent>\s*)(?P<type>\w+)(?:\s+「(?P<name>[^」]*)」)?"
        r"(?:\s+=\s*「(?P<value>[^」]*)」)?"
        r"\s+@\((?P<x>-?\d+),(?P<y>-?\d+),(?P<w>-?\d+),(?P<h>-?\d+)\)")
    for i, line in enumerate(str(text or "").splitlines()):
        m = pat.match(line)
        if not m:
            continue
        name = (m.group("name") or "").strip()
        value = (m.group("value") or "").strip()
        rect = [int(m.group("x")), int(m.group("y")),
                int(m.group("w")), int(m.group("h"))]
        out.append({
            "element_id": _eid("uia", name, rect, i),
            "name": name,
            "value": value,
            "type": m.group("type"),
            "rect": rect,
            "depth": len(m.group("indent")) // 2,
            "source": "uia",
        })
    return out


def _tokens(text):
    base = [x for x in re.findall(r"[\w\u4e00-\u9fff]+",
                                  str(text or "").lower()) if x]
    out = []
    for tok in base:
        if tok not in out:
            out.append(tok)
        # 中文没有空格分词：同时加入 1/2 字 n-gram。
        if re.search(r"[\u4e00-\u9fff]", tok):
            for n in (1, 2):
                for i in range(0, max(1, len(tok) - n + 1)):
                    sub = tok[i:i + n]
                    if sub and sub not in out:
                        out.append(sub)
    return out


def ground(goal, elements, top_k=8):
    """根据目标文字给候选控件打分，返回可执行 element_id。"""
    words = _tokens(goal)
    scored = []
    for el in elements or []:
        name = str(el.get("name") or "")
        value = str(el.get("value") or "")
        hay = (name + " " + value + " " + str(el.get("type", ""))).lower()
        if not name and not value:
            continue
        score = 0.0
        for w in words:
            if w and w in hay:
                score += 1.0
                if w == name.lower() or w == value.lower():
                    score += 1.0
        if any(k in str(el.get("type", "")).lower()
               for k in ("button", "edit", "hyperlink", "menuitem")):
            score += 0.35
        if score <= 0:
            continue
        confidence = min(0.99, 0.35 + score / max(2.0, len(words) + 1.0))
        item = dict(el)
        item.setdefault("element_id", _eid(
            item.get("source", "uia"), name, item.get("rect")))
        item["confidence"] = round(confidence, 3)
        scored.append(item)
    scored.sort(key=lambda x: (-x["confidence"], x.get("depth", 0)))
    return scored[:top_k]


def best_match(goal, elements, min_confidence=0.55):
    hits = ground(goal, elements, top_k=1)
    if hits and hits[0]["confidence"] >= min_confidence:
        return hits[0]
    return None


def parse_ocr_text(text, screen_rect=None):
    """把 OCR/视觉描述拆成候选。

    OCR 引擎若能返回 ``文字 @(x,y,w,h)``，这里会保留坐标；没有坐标的
    文本仍可用于规划，但不会直接用来点击。
    """
    out = []
    base_rect = list(screen_rect or [])
    for i, line in enumerate(str(text or "").splitlines()):
        name = line.strip()
        if not name:
            continue
        rect = list(base_rect)
        m = _RECT_RE.search(name)
        if m:
            rect = [int(m.group("x")), int(m.group("y")),
                    int(m.group("w")), int(m.group("h"))]
            name = _RECT_RE.sub("", name).strip(" \t-:：")
        out.append({
            "element_id": _eid("ocr", name, rect, i),
            "name": name[:200], "value": "",
            "type": "OCRText", "rect": rect,
            "depth": 99, "source": "ocr",
        })
    return out


def fuse_grounding(goal, uia_elements=None, ocr_text="", vision_text="",
                   top_k=10):
    """融合 UIA + OCR + 多模态描述，返回统一可执行候选。"""
    elements = list(uia_elements or [])
    elements += parse_ocr_text(ocr_text)
    elements += parse_ocr_text(vision_text)
    hits = ground(goal, elements, top_k=top_k)
    # 没有坐标的 OCR/视觉候选降低置信度，避免被直接当成可点击目标。
    for h in hits:
        if h.get("source") in ("ocr", "vision") and not h.get("rect"):
            h["confidence"] = round(max(0.1, h.get("confidence", 0.5) - 0.25), 3)
            h["actionable"] = False
        else:
            h["actionable"] = bool(h.get("rect") or h.get("name"))
    hits.sort(key=lambda x: -x.get("confidence", 0))
    return hits
