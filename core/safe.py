# -*- coding: utf-8 -*-
"""安全装饰器 - 统一错误处理，替代重复的 try/except
升级：safe_return / safe_log / safe_retry / safe_timeout / safe_validate

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


def safe_return(default=None):
    """装饰器：出错不崩，返回默认值"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                _record(func, e)
                get_logger().warn("[安全] %s 出错，返回默认值 %s: %s" % (func.__name__, default, str(e)[:60]))
                get_logger().debug(traceback.format_exc())
                return default
        return wrapper
    return decorator


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


def safe_retry(times=3, delay=1):
    """装饰器：失败自动重试 N 次"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    get_logger().warn("[安全] %s 第 %d/%d 次失败: %s" % (func.__name__, i+1, times, str(e)[:60]))
                    if i < times - 1:
                        time.sleep(delay)
            get_logger().error("[安全] %s 重试 %d 次仍失败: %s" % (func.__name__, times, str(last_err)[:80]))
            return None
        return wrapper
    return decorator


def safe_timeout(seconds=10):
    """BUG-21: 超时自动断开（用ThreadPoolExecutor实现，Windows可用）"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(func, *args, **kwargs)
                try:
                    return fut.result(timeout=seconds)
                except concurrent.futures.TimeoutError:
                    get_logger().error("[安全] %s 超时 %ds" % (func.__name__, seconds))
                    return None
        return wrapper
    return decorator


def safe_validate(validator):
    """装饰器：参数校验"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                validator(*args, **kwargs)
            except Exception as e:
                get_logger().warn("[安全] %s 参数校验失败: %s" % (func.__name__, str(e)[:60]))
                return None
            return func(*args, **kwargs)
        return wrapper
    return decorator


def safe_async(func):
    """异步版本装饰器"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            get_logger().error("[安全] %s 出错: %s" % (func.__name__, str(e)[:80]))
            get_logger().debug(traceback.format_exc())
            return None
    return wrapper


def safe_chain(*decorators):
    """装饰器链：组合多个装饰器"""
    def decorator(func):
        for d in reversed(decorators):
            func = d(func)
        return func
    return decorator


# 统计：被装饰的函数数
_SAFE_COUNT = 0


def get_safe_count():
    """返回被safe装饰的函数数"""
    return _SAFE_COUNT


def atomic_write_json(path, obj, indent=2, ensure_ascii=False):
    """P1-3: 原子写JSON：先写.tmp再os.replace，防止中途崩损坏文件"""
    import os, json
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=ensure_ascii, indent=indent)
    os.replace(tmp, path)
