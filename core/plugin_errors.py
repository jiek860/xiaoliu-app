# -*- coding: utf-8 -*-
"""插件结构化错误（Module-Level Standard 6.1 / 6.2）。

为什么需要
----------
历史上插件用中文自由文本报错：``return {"错误": "天气查询失败"}``
（全项目实测 70 处）。调用方拿到的是**一句话**，既不能分类重试、
也没法做统一 UI 提示，更没法测试。

本模块把错误统一成：

    {"error": {"code": "PLUGIN_TIMEOUT",
               "message": "天气服务 8 秒内没有响应",
               "retryable": True,
               "context": {"module": "weather", "upstream": "wttr.in"}}}

* ``code``      稳定机器可读的错误码；**不允许**用自然语言句子
* ``message``   给人看的说明，允许中文
* ``retryable`` 可恢复（True）/ 不可恢复（False）—— 标准 6.2 的落地
* ``context``   定位问题需要的上下文，必须是纯 JSON 可序列化

同时提供 ``normalize_error()``：把历史的中文自由文本或异常对象
转换成结构化错误，便于渐进迁移（不要求 70 处一次性改完）。
"""
from __future__ import annotations

import json

PLUGIN_ERROR_SCHEMA_VERSION = "1.0"

# 错误码 → 是否可恢复。新增错误码必须在这里登记，否则 normalize 会退化为
# PLUGIN_UNKNOWN 并保留原消息（宁可丢分类，也不能编个假码）。
ERROR_CATALOG = {
    # 输入类
    "PLUGIN_BAD_INPUT": {"retryable": False, "zh": "参数不合法"},
    "PLUGIN_MISSING_ARG": {"retryable": False, "zh": "缺少必填参数"},
    "PLUGIN_BAD_PATH": {"retryable": False, "zh": "路径不合法"},
    # 权限/策略类
    "PLUGIN_PERMISSION_DENIED": {"retryable": False, "zh": "能力未授权"},
    "PLUGIN_NEEDS_CONFIRM": {"retryable": True, "zh": "需要用户确认"},
    "PLUGIN_UNSUPPORTED_CAPABILITY": {"retryable": False, "zh": "不具备该能力"},
    # 依赖/环境类
    "PLUGIN_MISSING_DEPENDENCY": {"retryable": False, "zh": "缺少依赖"},
    "PLUGIN_NOT_AVAILABLE": {"retryable": True, "zh": "依赖服务不可用"},
    # 运行时类
    "PLUGIN_TIMEOUT": {"retryable": True, "zh": "执行超时"},
    "PLUGIN_CANCELLED": {"retryable": True, "zh": "已取消"},
    "PLUGIN_BUSY": {"retryable": True, "zh": "繁忙，稍后重试"},
    "PLUGIN_UPSTREAM_ERROR": {"retryable": True, "zh": "上游返回错误"},
    "PLUGIN_RATE_LIMITED": {"retryable": True, "zh": "被限流"},
    "PLUGIN_RESOURCE_EXHAUSTED": {"retryable": True, "zh": "资源耗尽"},
    "PLUGIN_CIRCUIT_OPEN": {"retryable": True, "zh": "插件已熔断"},
    "PLUGIN_CLOSE_TIMEOUT": {"retryable": True, "zh": "关闭超时"},
    # 契约/内部类
    "PLUGIN_BAD_OUTPUT": {"retryable": False, "zh": "返回格式不符合契约"},
    "PLUGIN_NOT_IMPLEMENTED": {"retryable": False, "zh": "尚未实现"},
    "PLUGIN_INTERNAL_ERROR": {"retryable": False, "zh": "插件内部错误"},
    "PLUGIN_UNKNOWN": {"retryable": False, "zh": "未知错误"},
}

# 历史中文文本 → 错误码（渐进迁移用，按命中优先级排列）
_TEXT_RULES = (
    ("PLUGIN_MISSING_DEPENDENCY", ("缺少", "未安装", "no module", "importerror",
                                   "not installed", "依赖")),
    ("PLUGIN_TIMEOUT", ("超时", "timeout", "timed out")),
    ("PLUGIN_PERMISSION_DENIED", ("权限", "拒绝", "denied", "forbidden",
                                  "unauthorized", "permission")),
    ("PLUGIN_BAD_INPUT", ("参数", "不合法", "invalid", "无法解析", "格式错误")),
    ("PLUGIN_NOT_AVAILABLE", ("未启动", "连不上", "不可用", "unavailable",
                              "connection", "refused")),
    ("PLUGIN_RATE_LIMITED", ("限流", "too many", "rate limit", "429")),
    ("PLUGIN_BUSY", ("busy", "繁忙", "占用中", "正在执行")),
    ("PLUGIN_CANCELLED", ("取消", "cancelled", "canceled", "aborted")),
    ("PLUGIN_RESOURCE_EXHAUSTED", ("内存不足", "磁盘满", "out of memory",
                                   "no space", "resource")),
    ("PLUGIN_NOT_IMPLEMENTED", ("未实现", "not implemented")),
)


def is_known_code(code):
    return str(code) in ERROR_CATALOG


def is_retryable(code):
    meta = ERROR_CATALOG.get(str(code)) or {}
    return bool(meta.get("retryable"))


def _json_safe(value, depth=0):
    """把 context 收敛成纯 JSON 可序列化结构（标准 1.5）。"""
    if depth > 4:
        return "<depth>"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, depth + 1) for v in list(value)[:30]]
    return str(value)[:200]


def make_error(code, message="", *, retryable=None, context=None, module=""):
    """构造标准错误对象。未知错误码会自动降级为 PLUGIN_UNKNOWN 并保留原码。"""
    raw_code = str(code or "PLUGIN_UNKNOWN").strip().upper()
    final_code = raw_code if is_known_code(raw_code) else "PLUGIN_UNKNOWN"
    ctx = _json_safe(context or {})
    if module and "module" not in ctx:
        ctx["module"] = str(module)
    if final_code != raw_code:
        ctx["original_code"] = raw_code[:80]
    text = str(message or "").strip() or ERROR_CATALOG[final_code]["zh"]
    retry = is_retryable(final_code) if retryable is None else bool(retryable)
    return {"error": {"code": final_code, "message": text[:400],
                      "retryable": retry, "context": ctx,
                      "schema_version": PLUGIN_ERROR_SCHEMA_VERSION}}


def error_result(code, message="", **kwargs):
    """直接返回给调用方的结果字典（与成功结果同层，便于统一判断）。"""
    return make_error(code, message, **kwargs)


def ok_result(payload=None, **extra):
    """标准成功结果：``{"ok": True, "data": ...}``。"""
    out = {"ok": True, "data": _json_safe(payload)}
    out.update({k: _json_safe(v) for k, v in extra.items()})
    return out


def code_from_text(text):
    """从历史中文/英文错误文本推断错误码（尽力而为，不抛异常）。"""
    low = str(text or "").lower()
    for code, needles in _TEXT_RULES:
        if any(n.lower() in low for n in needles):
            return code
    return "PLUGIN_INTERNAL_ERROR"


def normalize_error(value, *, module="", context=None):
    """把任意历史返回/异常转换成标准错误结构。

    支持的输入：
      * 已是标准结构：原样返回（补齐 schema_version）
      * ``{"错误": "..."}`` / ``{"error": "..."}`` / ``{"msg": "..."}``
      * ``Exception`` 实例
      * 纯字符串
      * 其他（None/数字等）→ PLUGIN_BAD_OUTPUT
    """
    if isinstance(value, dict) and isinstance(value.get("error"), dict):
        err = dict(value["error"])
        err.setdefault("schema_version", PLUGIN_ERROR_SCHEMA_VERSION)
        err["retryable"] = bool(err.get(
            "retryable", is_retryable(err.get("code"))))
        err["context"] = _json_safe(err.get("context") or {})
        if module:
            err["context"].setdefault("module", module)
        return {"error": err}
    if isinstance(value, BaseException):
        code = "PLUGIN_TIMEOUT" if isinstance(value, TimeoutError) else (
            "PLUGIN_PERMISSION_DENIED" if isinstance(value, PermissionError)
            else "PLUGIN_INTERNAL_ERROR")
        ctx = dict(context or {})
        ctx["exception"] = type(value).__name__
        return make_error(code, str(value)[:300], context=ctx, module=module)
    text = ""
    if isinstance(value, dict):
        for key in ("错误", "error", "msg", "message", "原因"):
            if value.get(key):
                text = str(value[key])
                break
        if not text and value:
            text = json.dumps(_json_safe(value), ensure_ascii=False)[:200]
    elif isinstance(value, str):
        text = value
    if not text:
        return make_error("PLUGIN_BAD_OUTPUT",
                          "插件没有返回可识别的结果",
                          context=context, module=module)
    return make_error(code_from_text(text), text[:300],
                      context=context, module=module)


def is_error(value):
    return isinstance(value, dict) and isinstance(value.get("error"), dict)


def error_code(value):
    if is_error(value):
        return value["error"].get("code", "")
    return ""


def error_of(value):
    """取错误对象（非错误返回 None）。"""
    return value.get("error") if is_error(value) else None


def describe(value):
    """一句话描述错误，供日志/UI 直接用。"""
    err = error_of(normalize_error(value) if not is_error(value) else value)
    if not err:
        return ""
    return "[%s] %s" % (err.get("code"), err.get("message"))
