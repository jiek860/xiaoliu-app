# -*- coding: utf-8 -*-
"""模块生命周期契约（Module-Level Standard 4.1 / 4.2 / 6.4）。

标准要求每个模块声明"初始化 → 运行 → 关闭"，并且需要释放资源的模块
必须提供清理入口。历史上的 ``BaseModule`` 只有 ``run()``，
清理由调用方靠 ``stop/close/shutdown/cleanup`` 的名字去猜
（见 ``trunk._auto_unload_loop``），既不可靠也无法测试。

本模块提供：

``ModuleLifecycle``
    统一的四阶段状态机：``new → started → running → stopped``。
    任何阶段都可重复调用（幂等），非法顺序返回结构化错误而不是抛异常。

``LifecycleMixin``
    给模块类混入的默认实现：``start()`` / ``stop()`` / ``health()``。
    子类只覆盖自己关心的那一两个，其余走默认。

约定：
  * ``start()``  只做一次性准备（连接、加载），**不阻塞**超过 1 秒；
  * ``run()``    真正干活，可被并发调用，必须无共享可变状态或自行加锁；
  * ``stop()``   必须幂等；重复调用不报错，返回 ``already_stopped`` 标记；
  * ``health()`` 必须快速返回（< 50ms），不得发起网络请求。
"""
from __future__ import annotations

import threading
import time

from core.plugin_errors import make_error

STAGE_NEW = "new"
STAGE_STARTED = "started"
STAGE_STOPPED = "stopped"
_STAGES = (STAGE_NEW, STAGE_STARTED, STAGE_STOPPED)


class ModuleLifecycle:
    """四阶段生命周期状态机（线程安全、幂等）。"""

    def __init__(self, name=""):
        self.name = str(name or "")
        self._stage = STAGE_NEW
        self._lock = threading.RLock()
        self.started_at = 0.0
        self.stopped_at = 0.0
        self.start_count = 0
        self.stop_count = 0
        self.last_error = ""

    @property
    def stage(self):
        with self._lock:
            return self._stage

    @property
    def started(self):
        return self.stage == STAGE_STARTED

    def transition(self, target):
        """把状态推进到 target；返回 (ok, info)。"""
        with self._lock:
            if target not in _STAGES:
                return False, make_error(
                    "PLUGIN_BAD_INPUT", "未知生命周期阶段: %s" % target,
                    context={"stage": target}, module=self.name)
            if target == self._stage:
                return True, {"stage": self._stage, "already": True}
            if target == STAGE_STARTED:
                if self._stage == STAGE_STOPPED:
                    # 允许重启：重新走 start
                    self.start_count += 1
                    self._stage = STAGE_STARTED
                    self.started_at = time.time()
                    return True, {"stage": self._stage, "restarted": True}
                self.start_count += 1
                self._stage = STAGE_STARTED
                self.started_at = time.time()
                return True, {"stage": self._stage}
            if target == STAGE_STOPPED:
                self.stop_count += 1
                self._stage = STAGE_STOPPED
                self.stopped_at = time.time()
                return True, {"stage": self._stage}
        return False, make_error("PLUGIN_INTERNAL_ERROR",
                                 "非法生命周期转换",
                                 context={"from": self._stage, "to": target},
                                 module=self.name)

    def health(self):
        with self._lock:
            return {
                "ok": self._stage != STAGE_STOPPED,
                "stage": self._stage,
                "uptime_s": round(time.time() - self.started_at, 3)
                if self.started_at else 0.0,
                "start_count": self.start_count,
                "stop_count": self.stop_count,
                "last_error": self.last_error[:200],
            }


class LifecycleMixin:
    """模块默认生命周期实现。子类覆盖 ``_on_start`` / ``_on_stop`` 即可。"""

    lifecycle: ModuleLifecycle = None

    def _lifecycle(self):
        lc = getattr(self, "lifecycle", None)
        if lc is None:
            lc = ModuleLifecycle(getattr(self, "NAME", "") or
                                 type(self).__name__)
            self.lifecycle = lc
        return lc

    # ---- 子类可覆盖的钩子：默认什么都不做 ----
    def _on_start(self):
        return None

    def _on_stop(self):
        return None

    # ---- 对外标准接口 ----
    def start(self):
        lc = self._lifecycle()
        ok, info = lc.transition(STAGE_STARTED)
        if not ok:
            return info
        try:
            self._on_start()
        except Exception as e:  # 启动失败要回滚状态，避免"半启动"
            lc.last_error = str(e)[:200]
            lc.transition(STAGE_STOPPED)
            return make_error("PLUGIN_INTERNAL_ERROR",
                              "模块启动失败: %s" % str(e)[:200],
                              context={"exception": type(e).__name__},
                              module=lc.name)
        return {"ok": True, "stage": lc.stage}

    def stop(self):
        lc = self._lifecycle()
        already = lc.stage == STAGE_STOPPED
        # 幂等：已停止就不再调用 _on_stop。
        # 标准 4.2 要求"重复调用不报错"，但重复**执行清理逻辑**会让
        # 关连接/删临时文件这类操作被跑两次，反而引入新问题。
        if already:
            return {"ok": True, "stage": lc.stage, "already_stopped": True}
        ok, info = lc.transition(STAGE_STOPPED)
        if not ok:
            return info
        try:
            self._on_stop()
        except Exception as e:
            lc.last_error = str(e)[:200]
            # 关闭阶段的异常不应阻止其它模块卸载，记录后继续
            return {"ok": False, "stage": lc.stage, "already_stopped": already,
                    "error": make_error(
                        "PLUGIN_INTERNAL_ERROR",
                        "模块关闭时出错: %s" % str(e)[:200],
                        context={"exception": type(e).__name__},
                        module=lc.name)["error"]}
        return {"ok": True, "stage": lc.stage, "already_stopped": already}

    def health(self):
        return self._lifecycle().health()

    # 兼容旧代码里按名字猜的清理调用
    def close(self):
        return self.stop()

    def shutdown(self):
        return self.stop()


def call_hook(module, names):
    """按顺序尝试调用模块上的任意一个清理方法（兼容历史命名）。

    返回 {"ok": bool, "called": 方法名或 "", "error": 结构化错误或 None}。
    """
    for name in names:
        fn = getattr(module, name, None)
        if not callable(fn):
            continue
        try:
            fn()
            return {"ok": True, "called": name, "error": None}
        except Exception as e:
            return {"ok": False, "called": name,
                    "error": make_error(
                        "PLUGIN_INTERNAL_ERROR",
                        "清理方法 %s 抛异常: %s" % (name, str(e)[:160]),
                        context={"exception": type(e).__name__})["error"]}
    return {"ok": True, "called": "", "error": None}


CLEANUP_HOOK_NAMES = ("stop", "close", "shutdown", "cleanup")
