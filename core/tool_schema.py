# -*- coding: utf-8 -*-
"""工具参数校验。"""
import json


def _depth(obj, level=0):
    if level > 8:
        return level
    if isinstance(obj, dict):
        return max([level] + [_depth(v, level + 1) for v in obj.values()])
    if isinstance(obj, list):
        return max([level] + [_depth(v, level + 1) for v in obj])
    return level


def _size(obj):
    try:
        return len(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return len(repr(obj))


def validate_args(args, declared=None):
    """校验工具参数，返回 (ok, message)。

    不强制 JSON Schema；先做低成本的结构、参数名和大小检查，避免模型把
    巨大/畸形参数直接送进模块。
    """
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return False, "工具参数必须是 JSON 对象"
    if _size(args) > 200_000:
        return False, "工具参数过大（超过 200KB）"
    if _depth(args) > 8:
        return False, "工具参数嵌套过深"
    declared = declared or {}
    if declared:
        unknown = [k for k in args if k not in declared]
        if unknown:
            return False, "未知参数: " + ", ".join(map(str, unknown[:5]))
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 100_000:
            return False, "参数 %s 的字符串过长" % k
        if isinstance(v, str) and "\x00" in v:
            return False, "参数 %s 含非法 NUL 字符" % k
    return True, ""
