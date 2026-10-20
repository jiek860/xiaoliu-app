# -*- coding: utf-8 -*-
"""工具结果标准化。"""
import json


def normalize(result, *, limit=2000):
    if isinstance(result, dict) and "ok" in result and "data" in result:
        return result
    if isinstance(result, dict):
        ok = result.get("ok") is not False
        err = result.get("错误") or result.get("error") or ""
        summary = result.get("摘要") or result.get("summary") or ""
        if not summary:
            summary = str(result.get("结果", result))[:200]
        return {"ok": ok, "summary": str(summary)[:limit],
                "data": result, "error": str(err)[:limit],
                "artifacts": result.get("artifacts", [])}
    return {"ok": True, "summary": str(result)[:limit],
            "data": result, "error": "", "artifacts": []}
