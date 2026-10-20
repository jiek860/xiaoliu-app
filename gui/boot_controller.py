# -*- coding: utf-8 -*-
"""主窗口的"先出界面、后台补 trunk"启动补丁。

做法（与 Web 前端的 skeleton 一个思路）：
  1. 窗口先建出来并 show()，用户立刻看到界面；
  2. QTimer 把重活排到事件循环里，避免和首帧抢时间；
  3. Trunk 在后台线程创建，完成后通过信号回到 GUI 线程补挂依赖；
  4. 补挂失败时降级为"同步重建"，不能出现空壳按钮点了没反应。

这里不改 JarvisWindow 的构造签名，只提供两个可复用的组件：
  SplashWindow   —— 首帧占位（可选）
  BootController —— 后台启动状态机
"""
from __future__ import annotations

import time
import traceback

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class BootController(QObject):
    """把 Trunk 的创建/装配拆到事件循环之后执行。"""

    progress = pyqtSignal(str)      # 给状态栏/占位页显示进度
    finished = pyqtSignal(bool, str)

    def __init__(self, window, startup=None, parent=None):
        # parent 必须是 QObject；window 可能不是（测试替身），不能直接当父对象。
        from PyQt5.QtCore import QObject as _QObject
        owner = parent if isinstance(parent, _QObject) else (
            window if isinstance(window, _QObject) else None)
        super().__init__(owner)
        self.window = window
        self.startup = startup
        self.ok = False
        self.error = ""
        self.started_at = 0.0

    def start(self, delay_ms=0):
        QTimer.singleShot(max(0, int(delay_ms)), self._step_trunk)

    def _step_trunk(self):
        self.started_at = time.perf_counter()
        self.progress.emit("正在加载核心模块…")
        try:
            trunk = self.window._boot_trunk()
        except Exception as e:
            self.error = str(e)[:200]
            traceback.print_exc()
            self.progress.emit("核心加载失败，正在重试…")
            # 一帧后再试一次：偶发失败（文件被占用）通常第二次就过
            QTimer.singleShot(300, self._retry_trunk)
            return
        self._install(trunk)

    def _retry_trunk(self):
        try:
            trunk = self.window._boot_trunk()
        except Exception as e:
            self.error = str(e)[:200]
            traceback.print_exc()
            self._finish(False, "核心模块加载失败：" + self.error)
            return
        self._install(trunk)

    def _install(self, trunk):
        self.progress.emit("正在装配界面…")
        try:
            self.window._init_from_trunk(trunk)
        except Exception as e:
            self.error = str(e)[:200]
            traceback.print_exc()
            self._finish(False, "界面装配失败：" + self.error)
            return
        if self.startup is not None:
            self.startup.mark("核心模块装配完成")
        try:
            elapsed = (time.perf_counter() - self.started_at) * 1000
            trunk.perf.record("startup.attach", elapsed / 1000.0)
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")
        self._finish(True, "已就绪")

    def _finish(self, ok, message):
        self.ok = ok
        self.error = "" if ok else message
        self.progress.emit(message)
        self.finished.emit(ok, message)
