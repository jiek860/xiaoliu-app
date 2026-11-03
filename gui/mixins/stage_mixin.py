# -*- coding: utf-8 -*-
"""过程可见混入（第 5 批 A4）：把 core 步骤事件接到聊天界面。

聊天线程里 core 只广播事件，StreamWorker 用 Qt 信号把它们搬到 GUI 线程，
这里再把事件喂给 `gui/chat_stage_strip.py` 的步骤条。任何一步失败都不影响回复。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None


class StageMixin:
    """步骤条：接入 worker 的 stage 信号、开/收一轮、处理单步取消。"""

    def _stage_strip(self):
        return getattr(self, "stage_strip", None)

    def _stage_attach(self, worker):
        """新一轮开始：清空步骤条并订阅 worker 的过程事件。"""
        strip = self._stage_strip()
        if strip is not None:
            try:
                strip.reset()
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "stage reset")
        try:
            if worker is not None and hasattr(worker, "stage"):
                worker.stage.connect(self._on_stage)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "stage connect")

    def _stage_finish(self):
        strip = self._stage_strip()
        if strip is None:
            return
        try:
            strip.finish()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "stage finish")

    def _on_stage(self, event, payload):
        """接收一条过程事件（已在 GUI 线程）：只在"过程可见=on"时才渲染。"""
        strip = self._stage_strip()
        if strip is None:
            return
        try:
            strip.apply(event, payload if isinstance(payload, dict) else {})
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "stage apply")

    def _stage_cancel_step(self, step_id):
        """界面点了"取消这一步"：走总线，只停那一步。"""
        try:
            from core.pipeline import stage_bus
            return stage_bus.cancel_step(str(step_id))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "stage cancel step")
            return False

    def _stage_rows(self):
        strip = self._stage_strip()
        return list(getattr(strip, "rows", lambda: [])() or [])
