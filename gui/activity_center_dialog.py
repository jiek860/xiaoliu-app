# -*- coding: utf-8 -*-
"""运行中活动中心：统一查看任务、后台活动和等待确认。"""
from __future__ import annotations

import os
import time
from html import escape
from urllib.parse import parse_qs, quote

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QSplitter,
    QTextBrowser, QWidget,
)

from core.agent_harness import (
    ACTIVE_STATUSES, TERMINAL_STATUSES, get_run_registry, normalize_error,
)
from gui.feedback_states import make_action_links


class _RunBridge(QObject):
    changed = pyqtSignal(object, str)


class ActivityCenterDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.registry = get_run_registry()
        self.rt = trunk.get_task_runtime()
        self._selected = ""
        self._log_view_for = ""
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
        self.detail = QTextBrowser()
        self.detail.setReadOnly(True)
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(self._on_anchor)
        rl.addWidget(self.detail, 1)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([380, 600])
        root.addWidget(split, 1)

        actions = QHBoxLayout()
        # 动作行用链接表达：活动中心是「看」的窗口，操作是次要入口。
        actions.addWidget(make_action_links([
            ("打开任务中心", self._open_task),
            ("暂停", self._pause),
            ("继续", self._resume),
            ("取消", self._cancel),
            ("清理已结束", self._clear_finished),
            ("刷新", self._refresh),
        ]))
        actions.addStretch(1)
        hint = QLabel("Esc 关闭")
        hint.setStyleSheet("color:#667085;font-size:11px;")
        actions.addWidget(hint)
        root.addLayout(actions)

    def _run_rows(self):
        runs = self.registry.list_runs(limit=200)
        # 运行中在前，同一状态按更新时间倒序
        runs.sort(key=lambda r: (r.get("status") in TERMINAL_STATUSES,
                                 -float(r.get("updated_at", 0))))
        return runs

    @staticmethod
    def _failure_reason(run):
        raw = str(run.get("error") or "").strip()
        if not raw:
            return "未记录原因"
        return normalize_error(raw)["title"]

    def _row_text(self, run):
        status = run.get("status", "?")
        title = run.get("title") or "未命名活动"
        step = run.get("current_step", "")
        if status in ("failed", "cancelled"):
            text = "[%s] %s   失败原因：%s" % (
                status, title, self._failure_reason(run))
        elif status == "completed":
            text = "[完成] %s" % title
        else:
            text = "[运行中] %s" % title
        if step:
            text += "    " + str(step)
        return text

    def _add_row(self, run, selected):
        item = QListWidgetItem(self._row_text(run))
        item.setData(256, run.get("run_id", ""))
        if run.get("run_id") == selected:
            self.list.setCurrentItem(item)
        self.list.addItem(item)

    def _refresh(self):
        rows = self._run_rows()
        selected = self._selected
        self.list.clear()
        active = [r for r in rows if r.get("status") in ACTIVE_STATUSES]
        failed = [r for r in rows if r.get("status") in ("failed", "cancelled")]
        finished = [r for r in rows if r.get("status") == "completed"]
        for label, group in (("运行中", active), ("失败", failed),
                             ("最近完成", finished)):
            if not group:
                continue
            head = QListWidgetItem("%s（%d）" % (label, len(group)))
            head.setFlags(Qt.NoItemFlags)
            self.list.addItem(head)
            for run in group:
                self._add_row(run, selected)
        self.count_label.setText(
            "运行中 %d  最近 %d  保留最近 %d 条" % (
                len(active), len(rows), self.registry.max_runs))
        if not rows:
            self.list.hide()
            self.empty.show()
            self.detail.setPlainText("当前没有运行中的任务或后台活动。")
            self._selected = ""
            return
        self.empty.hide()
        self.list.show()
        if not selected:
            self._selected = self._first_run_id() or rows[0].get("run_id", "")
            self._select_run(self._selected)
            self._show(self._selected)
        elif self._log_view_for == selected:
            pass  # 正在看日志时每秒刷新不要把用户拽回详情
        else:
            self._select_run(selected)
            self._show(selected)

    def _first_run_id(self):
        for i in range(self.list.count()):
            rid = self.list.item(i).data(256)
            if rid:
                return rid
        return ""

    def _select_run(self, run_id):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(256) == run_id:
                self.list.setCurrentItem(item)
                return

    def _on_changed(self, _run, event):
        if event in ("started", "updated", "removed"):
            QTimer.singleShot(0, self._refresh)

    def _select(self, item):
        rid = item.data(256)
        if not rid:  # 分组标题不可选
            return
        self._selected = rid
        self._log_view_for = ""
        self._show(rid)

    def _show(self, run_id):
        run = self.registry.get_run(run_id)
        if not run:
            return
        self._log_view_for = ""
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
        body = escape("\n".join(lines)).replace("\n", "<br>")
        body += ('<br><br><a href="activity://log?run=%s">查看日志</a>'
                 % quote(run_id, safe=""))
        self.detail.setHtml(body)

    def _log_path(self, run):
        meta = (run or {}).get("metadata") or {}
        path = str(meta.get("log_path") or "")
        if path:
            return path
        base = getattr(self.trunk, "base", "") or os.getcwd()
        return os.path.join(base, "data", "logs", "app.log")

    @staticmethod
    def _tail_text(path, max_chars=20000):
        if not os.path.isfile(path):
            return "日志文件不存在：%s" % path
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - max_chars))
                return f.read()
        except OSError as e:
            return "读取日志失败：%s" % e

    def _show_log(self, run_id):
        run = self.registry.get_run(run_id) or {}
        path = self._log_path(run)
        text = self._tail_text(path)
        self._log_view_for = run_id
        self.detail.setHtml(
            '<p><a href="activity://detail?run=%s">← 返回活动详情</a></p>'
            '<p style="color:#667085;">%s</p>'
            '<pre style="white-space:pre-wrap;">%s</pre>'
            % (quote(run_id, safe=""), escape(path), escape(text)))

    def _on_anchor(self, url):
        if url.scheme() != "activity":
            return
        run_id = parse_qs(url.query()).get("run", [""])[0]
        if not run_id:
            return
        if url.host() == "log":
            self._show_log(run_id)
        else:
            self._selected = run_id
            self._select_run(run_id)
            self._show(run_id)

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
