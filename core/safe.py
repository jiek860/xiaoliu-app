# -*- coding: utf-8 -*-
"""安全装饰器 - 统一错误处理，替代重复的 try/except
对外只有三个：`safe`（吞异常返回 None）、`safe_log`（记日志后重抛）、
`last_error`（查"刚才这次 None 是真没结果还是出错了"）。

2026-11-02 删掉了零引用的 6 个装饰器（safe_return / safe_retry / safe_timeout /
safe_validate / safe_async / safe_chain）和一个从不递增的计数器 get_safe_count：
它们看着像"通用工具箱"，实际全项目没有一处使用，留着只会让人误以为有统一重试/超时。
真需要重试的调用点自己写循环（见 core/llm_client.py 的重试），不要指望装饰器魔法。

关于"静默的 None"
-----------------
@safe 出错时返回 None。它**确实记了日志**（error + 完整堆栈），
但调用方拿到的是 None —— 和"这个方法本来就返回空"**完全无法区分**。
实测吃过这个亏：`ocr_available()` 被传了个多余参数，TypeError 被 @safe
吞掉变成 None，从现象上看就是"这功能没反应"，查了很久。

所以这里多记一份**最近一次错误**（按函数名），让调用方能问一句
"刚才这次 None，是真没结果，还是出错了？" —— 见 last_error()。
这正是 core/tool_caller._invoke 用的：它把静默的 None 变成明确的失败信息。
"""
import threading
import traceback
import time
import functools
from core.logger import get_logger

# 函数名 -> (时间戳, "异常类型: 描述")，只保留最近一次
_LAST_ERROR = {}
_ERR_LOCK = threading.Lock()


def last_error(func_name, within=10.0):
    """取某函数最近一次错误；超过 within 秒的算过期（避免误判成这次的）

    key 可以用函数名（"stats"），也可以用限定名（"Todo.stats"）。
    **建议用限定名** —— 实测 stats / run / status 这类名字在多个模块里都有，
    只按函数名查会串台（A 模块的错误被算到 B 模块头上）。
    返回 "异常类型: 描述" 或 None。
    """
    key = str(func_name)
    with _ERR_LOCK:
        rec = _LAST_ERROR.get(key)
    if not rec:
        return None
    ts, msg = rec
    if time.time() - ts > within:
        return None
    return msg


def clear_errors():
    """清空记录（测试用）"""
    with _ERR_LOCK:
        _LAST_ERROR.clear()


def _record(func, e):
    """记下错误：同时按函数名和限定名记，查哪个都行"""
    rec = (time.time(), "%s: %s" % (type(e).__name__, str(e)[:120]))
    with _ERR_LOCK:
        _LAST_ERROR[str(func.__name__)] = rec
        q = getattr(func, "__qualname__", None)
        if q and q != func.__name__:
            _LAST_ERROR[str(q)] = rec


def safe(func):
    """装饰器：出错不崩，打印完整错误日志+堆栈，返回 None
    注意：只在 GUI回调/后台线程入口用，内部函数请用 safe_log
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            _record(func, e)
            logger = get_logger()
            logger.error("[安全] %s 出错: %s" % (func.__name__, str(e)[:80]))
            # 打印完整堆栈，方便排查（之前只打了消息，不知道哪里错的）
            logger.debug(traceback.format_exc())
            return None
    return wrapper


def safe_log(func):
    """装饰器：出错打日志+堆栈，但不吞异常（重新抛出）
    内部函数默认用这个，让异常冒泡，问题不被掩盖
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            get_logger().error("[安全] %s 出错: %s" % (func.__name__, str(e)[:80]))
            get_logger().debug(traceback.format_exc())
            raise
    return wrapper


def atomic_write_json(path, obj, indent=2, ensure_ascii=False):
    """P1-3: 原子写JSON：先写.tmp再os.replace，防止中途崩损坏文件"""
    import os, json
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=ensure_ascii, indent=indent)
    os.replace(tmp, path)
