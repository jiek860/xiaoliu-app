# -*- coding: utf-8 -*-
"""运行中活动中心：统一查看任务、后台活动和等待确认。"""
from __future__ import annotations

import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTextEdit, QPushButton, QMessageBox, QSplitter,
    QWidget,
)

from core.agent_harness import get_run_registry, normalize_error, TERMINAL_STATUSES


class _RunBridge(QObject):
    changed = pyqtSignal(object, str)


class ActivityCenterDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.registry = get_run_registry()
        self.rt = trunk.get_task_runtime()
        self._selected = ""
        self._build()
        # 首次打开时把已有任务同步一次；之后完全依赖 TaskRuntime 事件。
        try:
            self.registry.sync_tasks(self.rt.list_tasks())
        except Exception:  # 静默是故意的
            pass
        self._bridge = _RunBridge(self)
        self._bridge.changed.connect(self._on_changed)
        self._registry_cb = self._bridge.changed.emit
        self.registry.subscribe(self._registry_cb)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh)
        self._tick.start(1000)
        self._refresh()

    def _build(self):
        self.setWindowTitle("运行中活动")
        self.resize(980, 640)
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.title_label = QLabel("运行中活动")
        self.title_label.setStyleSheet("font-size:16px;font-weight:700;")
        top.addWidget(self.title_label)
        top.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#667085;")
        top.addWidget(self.count_label)
        root.addLayout(top)

        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("任务 / 后台活动"))
        self.list = QListWidget()
        self.list.itemClicked.connect(self._select)
        ll.addWidget(self.list)
        from gui.feedback_states import EmptyStateWidget
        self.empty = EmptyStateWidget(
            "没有运行中活动", "任务或后台活动启动后会出现在这里。")
        self.empty.hide()
        ll.addWidget(self.empty, 1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("详情"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        rl.addWidget(self.detail, 1)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([380, 600])
        root.addWidget(split, 1)

        actions = QHBoxLayout()
        for text, fn in (("打开任务中心", self._open_task),
                         ("暂停", self._pause),
                         ("继续", self._resume),
                         ("取消", self._cancel),
                         ("清理已结束", self._clear_finished),
                         ("刷新", self._refresh)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            actions.addWidget(b)
        actions.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)

    def _run_rows(self):
        runs = self.registry.list_runs(limit=200)
        # 运行中在前，同一状态按更新时间倒序
        runs.sort(key=lambda r: (r.get("status") in TERMINAL_STATUSES,
                                 -float(r.get("updated_at", 0))))
        return runs

    def _refresh(self):
        rows = self._run_rows()
        selected = self._selected
        self.list.clear()
        for run in rows:
            status = run.get("status", "?")
            title = run.get("title", "未命名活动")
            step = run.get("current_step", "")
            text = "[%s] %s" % (status, title)
            if step:
                text += "    " + str(step)
            item = QListWidgetItem(text)
            item.setData(256, run.get("run_id", ""))
            if run.get("run_id") == selected:
                self.list.setCurrentItem(item)
            self.list.addItem(item)
        active = sum(1 for r in rows if r.get("status") not in TERMINAL_STATUSES)
        self.count_label.setText("运行中 %d  最近 %d" % (active, len(rows)))
        if not rows:
            self.list.hide()
            self.empty.show()
            self.detail.setPlainText("当前没有运行中的任务或后台活动。")
            self._selected = ""
            return
        self.empty.hide()
        self.list.show()
        if rows and not selected:
            self._selected = rows[0].get("run_id", "")
            self.list.setCurrentRow(0)
            self._show(self._selected)
        elif selected:
            self._show(selected)

    def _on_changed(self, _run, event):
        if event in ("started", "updated", "removed"):
            QTimer.singleShot(0, self._refresh)

    def _select(self, item):
        self._selected = item.data(256)
        self._show(self._selected)

    def _show(self, run_id):
        run = self.registry.get_run(run_id)
        if not run:
            return
        now = time.time()
        started = float(run.get("started_at") or now)
        updated = float(run.get("updated_at") or now)
        finished = float(run.get("finished_at") or 0)
        elapsed = (finished or now) - started
        lines = [
            "活动：%s" % run.get("title", ""),
            "类型：%s" % run.get("kind", ""),
            "状态：%s" % run.get("status", ""),
            "当前步骤：%s" % (run.get("current_step") or "无"),
            "进度：%.0f%%" % (float(run.get("progress") or 0) * 100),
            "开始：%s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                       time.localtime(started)),
            "已耗时：%.1fs" % elapsed,
            "最近更新：%s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(updated)),
        ]
        if run.get("waiting_for"):
            lines.append("等待：%s" % run["waiting_for"])
        budget = run.get("budget") or {}
        if budget:
            parts = []
            for k, label in (("max_seconds", "时间"), ("max_steps", "步骤"),
                             ("max_tokens", "token")):
                if budget.get(k):
                    parts.append("%s %s" % (label, budget[k]))
            if parts:
                lines.append("预算：" + " / ".join(parts))
        usage = run.get("usage") or {}
        if usage:
            lines.append("用量：%s" % json_dumps(usage))
        if run.get("error"):
            env = normalize_error(run["error"])
            lines += ["", "错误：" + env["title"], env["message"],
                      "下一步：" + env["next_action"]["label"]]
        if run.get("trace_id"):
            lines.append("Trace：%s" % run["trace_id"])
        meta = run.get("metadata") or {}
        if meta:
            lines += ["", "元数据：", json_dumps(meta)[:1000]]
        self.detail.setPlainText("\n".join(lines))

    def _current_task_id(self):
        run = self.registry.get_run(self._selected)
        return (run or {}).get("task_id", "")

    def _open_task(self):
        tid = self._current_task_id()
        p = self.parent()
        if tid and p is not None and hasattr(p, "open_task_center"):
            p.open_task_center(task_id=tid)
        else:
            QMessageBox.information(self, "活动中心", "这个活动没有关联任务页面")

    def _pause(self):
        tid = self._current_task_id()
        if tid:
            r = self.rt.pause(tid)
            if not r.get("ok"):
                QMessageBox.warning(self, "暂停", str(r.get("错误", "操作失败")))
            self._refresh()

    def _resume(self):
        tid = self._current_task_id()
        if tid:
            r = self.rt.resume(tid)
            if not r.get("ok"):
                QMessageBox.warning(self, "继续", str(r.get("错误", "操作失败")))
            self._refresh()

    def _cancel(self):
        tid = self._current_task_id()
        if tid:
            self.rt.cancel(tid)
            self._refresh()

    def _clear_finished(self):
        for run in self.registry.list_runs(limit=1000):
            if run.get("status") in TERMINAL_STATUSES:
                self.registry.remove_run(run.get("run_id", ""))
        self._refresh()

    def closeEvent(self, event):
        try:
            self.registry.unsubscribe(getattr(self, "_registry_cb", None))
        except Exception:  # 静默是故意的
            pass
        try:
            self._tick.stop()
        except Exception:  # 静默是故意的
            pass
        super().closeEvent(event)


def json_dumps(obj):
    import json
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:  # 静默是故意的
        return str(obj)
