# -*- coding: utf-8 -*-
"""统一日志工具 v3.0
所有模块用同一个日志文件，分级：debug/info/warn/error
升级：日志轮转、日志统计、日志搜索、日志清理、彩色控制台
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import time
from datetime import datetime


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
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            finally:
                try:
                    self._log_queue.task_done()
                except Exception as e:
                    _x6_swallowed(__name__, e)
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
        except Exception as e:
            _x6_swallowed(__name__, e)
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
        except Exception as e:
            _x6_swallowed(__name__, e)
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


# 默认轮转阈值：10MB，与 Logger.max_size 保持一致
DEFAULT_MAX_SIZE = 10 * 1024 * 1024


def rotate_if_needed(path, max_size=DEFAULT_MAX_SIZE, keep=1):
    """日志文件超限就转成 .old（保留 keep 代）

    抽成公共函数的原因：项目里**有两条写日志的路** ——
        core/logger.py  写 app.log，本来就有轮转 ✅
        core/trunk.py   写 trunk.log，直接 open(path,"a") 追加 ❌
    同一件事两个实现，其中一个漏了。实测 trunk.log 已经 914 KB 且无限增长，
    而 gui/log_dialog.py 打开日志中心时用 `f.readlines()` **读整个文件** ——
    跑久了自己都打不开日志中心。

    保留 keep 代（默认只留 1 个 .old）：日志是排查用的，留一代足够，
    再多只会占地方。

    ⚠️ 这里踩过一个自己写的 bug（测试"连续转两次"时抓到的）：
       第一版把"后移各代"写成了一个循环 `for i in range(keep, 0, -1)`，
       而 keep=1 时这个循环里 src 和 dst **是同一个路径**（都是 .old）——
       于是先 os.remove(dst) 删掉它，再 os.replace(src, dst) 找不到源，
       必然抛异常被外层吞掉。
       后果：**每隔一次轮转就失败一次，并且把上一代日志删掉**。
       连续写入时看起来"正常"，只是因为它在"成功/失败"交替 ——
       不写"连着转两次"的测试根本发现不了。
    """
    try:
        if not os.path.exists(path):
            return False
        if os.path.getsize(path) <= max_size:
            return False
        old = path + ".old"
        if keep <= 1:
            # 只留一代：直接覆盖（os.replace 会替换已存在的目标，不用先删）
            os.replace(path, old)
            return True
        # 多代：最老的丢掉，其余依次后移，最后把当前文件变成第 1 代
        oldest = "%s.old.%d" % (path, keep)
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(keep - 1, 0, -1):
            src = old if i == 1 else "%s.old.%d" % (path, i)
            dst = "%s.old.%d" % (path, i + 1)
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(path, old)
        return True
    except Exception:
        # 轮转失败不能影响"写日志"这件事本身
        return False


def append_line(path, line, max_size=DEFAULT_MAX_SIZE):
    """追加一行到日志文件（带轮转）。写失败也不抛 —— 日志不能反过来搞挂程序。"""
    try:
        rotate_if_needed(path, max_size)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line if line.endswith("\n") else line + "\n")
        return True
    except Exception:
        return False
