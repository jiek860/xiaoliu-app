# -*- coding: utf-8 -*-
"""安全装饰器 - 统一错误处理，替代重复的 try/except
升级：safe_return / safe_log / safe_retry / safe_timeout / safe_validate
"""
import traceback
import time
import functools
from core.logger import get_logger


def safe(func):
    """装饰器：出错不崩，打印完整错误日志+堆栈，返回 None
    注意：只在 GUI回调/后台线程入口用，内部函数请用 safe_log
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
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
