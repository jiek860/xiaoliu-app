# -*- coding: utf-8 -*-
"""工作台 AI 面板的接线层：后台任务（46.1）与可点击引用（47.3）。

为什么单独一个文件
------------------
`gui/workbench_ai_dock.py` 已经到 600 行上限附近，按批次 35/36 搬
`editor_parts.py` 的老办法，把"接线"代码搬出来：

    AgentDockServiceMixin  后台任务（AgentService + 线程）与代码问答
    LinkPlainTextEdit      只读文本视图，识别 `文件:行` 并可点击跳转

只搬代码不改行为：方法签名、提示文案、按钮状态与原来逐行一致。
"""
from __future__ import annotations

import os
import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QPlainTextEdit

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


class LinkPlainTextEdit(QPlainTextEdit):
    """只读文本：`路径:行` 可点击（双击 / Ctrl+单击）跳转。

    面板里全是纯文本 + appendPlainText，换成 QTextBrowser 会牵动一大片
    调用点；这里只在鼠标事件里认 `文件:行` 的 token，行为完全不变。
    """

    refClicked = pyqtSignal(str, int)
    _REF_RE = re.compile(r"([\w\-./\\]+\.[A-Za-z0-9]{1,8}):(\d{1,6})")

    def mouseDoubleClickEvent(self, e):
        if self._emit_ref(e.pos()):
            return
        super().mouseDoubleClickEvent(e)

    def mousePressEvent(self, e):
        if e.modifiers() & Qt.ControlModifier and self._emit_ref(e.pos()):
            return
        super().mousePressEvent(e)

    def _emit_ref(self, pos):
        """光标落在 `路径:行` 上就发信号，返回是否命中。"""
        try:
            cur = self.cursorForPosition(pos)
            text = cur.block().text()
            col = cur.positionInBlock()
            for m in self._REF_RE.finditer(text):
                if m.start() <= col <= m.end() + 1:
                    self.refClicked.emit(m.group(1), int(m.group(2)))
                    return True
        except Exception as e:  # 静默是故意的 - 点击失败不能影响输入
            _x6_swallowed(__name__, e, "dock ref click")
        return False


class AgentDockServiceMixin:
    """AgentDock 的后台执行与代码问答（宿主提供 wb/timeline/service 等）。"""

    # ------------------------------------------------------ 后台任务（46.1）
    def _background_enabled(self):
        try:
            from core.patch_protocol import background_enabled
            return bool(background_enabled(self.wb.trunk))
        except Exception as e:  # 静默是故意的 - 读不到开关就按前台执行
            _x6_swallowed(__name__, e, "background switch")
            return False

    def _start_background(self, goal, open_files):
        """把任务交给 AgentService，再由 AgentServiceWorker 后台消费。"""
        from gui.workbench_ai_dock import resolve_explicit
        try:
            from core.agent_service import get_agent_service
        except Exception as e:
            self.timeline.appendPlainText("[错误] 后台服务不可用: %s"
                                          % str(e)[:200])
            return
        root = getattr(self.wb, "root", None) or getattr(
            self.wb.trunk, "base", ".")
        try:
            self.service = get_agent_service(self.wb.trunk, root=root)
            submitted = self.service.submit(
                goal, open_files=open_files,
                max_rounds=self.rounds_spin.value(),
                explicit=resolve_explicit(goal))
        except Exception as e:  # 静默是故意的 - 出错显示给用户而不是崩
            self.timeline.appendPlainText("[错误] 无法提交后台任务: %s"
                                          % str(e)[:200])
            return
        if not submitted.get("ok"):
            self.timeline.appendPlainText(
                "[错误] %s" % submitted.get("error", "提交失败"))
            return
        self.queue = self.service.queue
        self.current_job_id = submitted["job_id"]
        self.timeline.clear()
        self.timeline.appendPlainText("▶ 目标: " + goal)
        if open_files:
            self.timeline.appendPlainText(
                "  参考文件: " + ", ".join(os.path.basename(f)
                                          for f in open_files))
        self.timeline.appendPlainText(
            "  轮次上限: %d" % self.rounds_spin.value())
        self.timeline.appendPlainText(
            "  执行域: 代码 Agent（后台任务，可切回窗口继续用）")
        self._running = True
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._refresh_queue()
        self._launch_worker()

    def _launch_worker(self):
        from gui.workers import AgentServiceWorker
        self.worker = AgentServiceWorker(self.service, trunk=self.wb.trunk)
        self.worker.event.connect(self._on_service_event)
        self.worker.done.connect(self._on_service_done)
        self.worker.start()

    def _resume_background(self, job):
        """后台模式下续跑：把断点任务重新置为 queued 再起线程。"""
        try:
            from core.agent_service import get_agent_service
        except Exception as e:
            self.timeline.appendPlainText("[错误] 后台服务不可用: %s"
                                          % str(e)[:200])
            return
        root = getattr(self.wb, "root", None) or getattr(
            self.wb.trunk, "base", ".")
        self.service = get_agent_service(self.wb.trunk, root=root)
        self.queue = self.service.queue
        result = self.service.resume(job.get("job_id"))
        if not result.get("ok"):
            self.timeline.appendPlainText("[错误] %s"
                                          % result.get("error", "无法续跑"))
            return
        self.current_job_id = job.get("job_id")
        state = self.queue.checkpoint_of(job)
        self.timeline.clear()
        self.timeline.appendPlainText(
            "↯ 继续任务（从第 %s 轮）" % (state.get("round") or 1))
        self.timeline.appendPlainText("▶ 目标: " + str(job.get("goal") or ""))
        self.timeline.appendPlainText("  执行域: 代码 Agent（后台任务）")
        self._running = True
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("⏸ 暂停")
        self.cancel_btn.setEnabled(True)
        self._refresh_queue()
        self._launch_worker()

    def _on_service_event(self, event, data=None):
        """后台线程的事件在 GUI 线程处理；审批走"事件-应答"而不是弹窗线程。"""
        data = data if isinstance(data, dict) else {}
        if str(event) == "approval" and data.get("request_id"):
            ok = self._approve(data.get("kind"), data.get("payload"))
            if self.service is not None:
                self.service.answer(data.get("request_id"), ok)
            return
        self._handle_event(event, data)

    def _on_service_done(self, result):
        self.worker = None
        self._refresh_queue()
        self._on_done(result)

    # ------------------------------------------------------ 代码问答（47.3）
    def try_code_qa(self, goal):
        """开关开且识别为代码问题时，用本地索引直接回答，返回是否已答。"""
        try:
            from core.agent_router import answer_code_question, code_qa_enabled
            trunk = getattr(self.wb, "trunk", None)
            if not code_qa_enabled(trunk):
                return False
            idx = None
            try:
                idx = trunk.get_workspace_index()
            except Exception as e:  # 静默是故意的 - 没索引就让 core 现场建
                _x6_swallowed(__name__, e, "code qa trunk index")
            root = getattr(self.wb, "root", None) or getattr(trunk, "base", ".")
            result = answer_code_question(goal, root=root, index=idx)
            if not result.get("ok"):
                return False
            self.timeline.clear()
            self.timeline.appendPlainText(str(result.get("answer") or ""))
            self.timeline.appendPlainText(
                "💡 双击（或 Ctrl+单击）引用可跳转到对应代码")
            return True
        except Exception as e:  # 静默是故意的 - 问答失败就走正常执行
            _x6_swallowed(__name__, e, "code qa answer")
            return False

    def open_reference(self, path, line):
        """点击 `文件:行`：在工作台编辑器里打开并定位。"""
        try:
            editor = getattr(self.wb, "_editor", None)
            if editor is not None and hasattr(editor, "open_path_at"):
                editor.open_path_at(path, line)
                return
            if hasattr(self.wb, "open_path"):
                self.wb.open_path(path)
        except Exception as e:  # 静默是故意的 - 跳转失败只提示
            self.timeline.appendPlainText("[错误] 跳转失败: %s" % str(e)[:200])
