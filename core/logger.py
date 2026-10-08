# -*- coding: utf-8 -*-
"""统一日志工具 v3.0
所有模块用同一个日志文件，分级：debug/info/warn/error
升级：日志轮转、日志统计、日志搜索、日志清理、彩色控制台
"""
import os
import time
from datetime import datetime, timedelta


# 颜色码
COLORS = {
    "DEBUG": "\033[36m",    # 青色
    "INFO": "\033[32m",     # 绿色
    "WARN": "\033[33m",     # 黄色
    "ERROR": "\033[31m",    # 红色
    "RESET": "\033[0m",
}


class Logger:
    def __init__(self, base_dir=None):
        if not base_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.log_dir = os.path.join(base_dir, "data", "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "app.log")
        self.max_size = 10 * 1024 * 1024  # 10MB轮转
        self._counts = {"debug": 0, "info": 0, "warn": 0, "error": 0}
        self.level = "info"  # 只打info以上
        # P1-5: 异步日志队列，不阻塞主线程
        import queue as _q
        import threading as _t
        self._log_queue = _q.Queue(maxsize=1000)
        self._log_worker = _t.Thread(target=self._log_loop, daemon=True)
        self._log_worker.start()

    def _log_loop(self):
        """P1-5: 后台日志写线程"""
        while True:
            try:
                item = self._log_queue.get()
                if item is None:
                    break
                level, msg = item
                self._write_sync(level, msg)
            except Exception:
                pass
            finally:
                try:
                    self._log_queue.task_done()
                except Exception:
                    pass

    def _write(self, level, msg):
        """P1-5: 异步写日志，不阻塞主线程"""
        try:
            self._log_queue.put_nowait((level, msg))
        except Exception:
            # 队列满了就同步写一次
            self._write_sync(level, msg)

    def _write_sync(self, level, msg):
        """同步写日志（后台线程调用）"""
        try:
            # 日志轮转
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > self.max_size:
                old = self.log_path + ".old"
                if os.path.exists(old):
                    os.remove(old)
                os.rename(self.log_path, old)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = "[%s] [%s] %s\n" % (ts, level, str(msg)[:200])
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
            self._counts[level.lower()] = self._counts.get(level.lower(), 0) + 1
            # 控制台彩色输出
            color = COLORS.get(level, "")
            reset = COLORS["RESET"]
            print("%s[%s]%s %s" % (color, level, reset, str(msg)[:100]))
        except:
            pass

    def debug(self, msg):
        """BUG-22: debug写文件但不打控制台，复用_write_sync逻辑"""
        try:
            # 复用_write_sync，但level用DEBUG，控制台不打（避免噪音）
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > self.max_size:
                old = self.log_path + ".old"
                if os.path.exists(old):
                    os.remove(old)
                os.rename(self.log_path, old)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = "[%s] [DEBUG] %s\n" % (ts, str(msg)[:200])
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
            self._counts["debug"] = self._counts.get("debug", 0) + 1
        except:
            pass

    def info(self, msg):
        self._write("INFO", msg)

    def warn(self, msg):
        self._write("WARN", msg)

    def error(self, msg):
        self._write("ERROR", msg)

    def get_stats(self):
        """日志统计"""
        return {
            "debug": self._counts.get("debug", 0),
            "info": self._counts.get("info", 0),
            "warn": self._counts.get("warn", 0),
            "error": self._counts.get("error", 0),
        }

    def search(self, keyword, limit=20):
        """搜索日志"""
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path, encoding="utf-8") as f:
            lines = f.readlines()
        found = [l.strip() for l in lines if keyword in l]
        return found[-limit:]

    def get_recent(self, count=50):
        """获取最近N条日志"""
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path, encoding="utf-8") as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-count:]]

    def clear_old(self, days=7):
        """清理N天前的日志"""
        if not os.path.exists(self.log_path):
            return 0
        cutoff = time.time() - days * 86400
        with open(self.log_path, encoding="utf-8") as f:
            lines = f.readlines()
        kept = []
        removed = 0
        for l in lines:
            try:
                ts_str = l.split("]")[0].strip("[")
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").timestamp()
                if ts > cutoff:
                    kept.append(l)
                else:
                    removed += 1
            except:
                kept.append(l)
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.writelines(kept)
        return removed


# 全局单例
_global_logger = None


def get_logger():
    """获取全局 logger 单例"""
    global _global_logger
    if not _global_logger:
        _global_logger = Logger()
    return _global_logger
