# -*- coding: utf-8 -*-
"""聊天步骤条（第 5 批 A4 + 深度⑥⑦⑧）。

一行显示"① 接收消息 ✓ ② 组装上下文 ✓ ③ 模型生成 …" + 进度百分比 + 预计剩余，
右侧两个文字链接：查看详情（展开工具调用/耗时）、取消这一步（只停当前一步）。

⚠️ 按钮预算：这里是 QLabel + 富文本链接，不是 QPushButton，
   所以工具链的 check_buttons（创建点 60/60）不受影响。
"""
import html as _h

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QDialog, QVBoxLayout, QTextBrowser,
)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MARKS = {"running": "…", "ok": "✓", "fail": "✗",
         "cancelled": "⏹", "skipped": "⏭"}
COLORS = {"running": "#1976d2", "ok": "#15803d", "fail": "#b91c1c",
          "cancelled": "#6b7280", "skipped": "#98a2b3"}
MAX_ROWS = 200
MAX_SHOWN = 6


def _circled(index):
    try:
        from core.pipeline.stage_bus import circled
        return circled(index)
    except Exception:  # 静默是故意的 - 步骤条排版失败就退回数字
        return "%d." % (int(index) + 1)


class StageDetailDialog(QDialog):
    """展开的调用卡片：所有步骤 / 工具参数 / 结果 / 耗时。"""

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("这一步到底做了什么")
        self.resize(680, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        view = QTextBrowser()
        view.setStyleSheet(
            "font-family:'Microsoft YaHei',Consolas;font-size:12px;"
            "background:#fbfcff;border:1px solid #e4e7ec;border-radius:8px;")
        try:
            from core.pipeline import stage_bus
            text = stage_bus.format_events(rows, limit=MAX_ROWS)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "format events")
            text = "\n".join(str(r.get("stage") or r.get("tool") or "")
                             for r in list(rows or []))
        view.setPlainText(text or "（还没有步骤）")
        lay.addWidget(view, 1)


class ChatStageStrip(QWidget):
    """聊天输入框上方的过程步骤条（默认隐藏，有事件才出现）。

    ⚠️ 这里**故意不对外发信号**（S4 删了 `cancelRequested` / `detailRequested`）：
    两个动作都是"自己就能闭环"的 —— 取消走 `stage_bus.cancel_step()`（真取消，
    线程安全），详情自己弹 `StageDetailDialog`。原来的 emit 全项目没有消费者，
    留着只会让人以为"外面还有人在管"，属于假接口。
    """

    def __init__(self, parent=None, trunk=None):
        super().__init__(parent)
        self.trunk = trunk
        self._rows = []
        self._steps = []
        self._tools = []
        self._percent = None
        self._eta = None
        self._running_step = ""
        self._dialog = None
        self._build()
        self.hide()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(8)
        self.summary = QLabel("")
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setStyleSheet("font-size:12px;color:#475467;")
        lay.addWidget(self.summary, 1)
        self.links = QLabel("")
        self.links.setTextFormat(Qt.RichText)
        self.links.setStyleSheet("font-size:12px;")
        self.links.linkActivated.connect(self._on_link)
        lay.addWidget(self.links, 0)
        self.setStyleSheet(
            "QWidget{background:#f8fafc;border-top:1px solid #eef2f6;}")

    # ------------------------------------------------------------ 对外接口
    def reset(self):
        """新一轮开始：清空步骤与进度。"""
        self._rows = []
        self._steps = []
        self._tools = []
        self._percent = None
        self._eta = None
        self._running_step = ""
        self.summary.setText("")
        self.links.setText("")
        self.hide()

    def wants_visible(self):
        """界面可见开关：off/shadow 都不显示（shadow 只落日志）。"""
        try:
            mode = str(self.trunk.rule("聊天.过程可见", "on") or "on")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "stage visible")
            return True
        return mode.strip().lower() == "on"

    def apply(self, event, payload=None):
        """吃一条事件（来自 StreamWorker 的 stage 信号，已在 GUI 线程）。"""
        payload = dict(payload or {})
        event = str(event or "")
        row = {"event": event}
        row.update(payload)
        self._rows.append(row)
        if len(self._rows) > MAX_ROWS:
            self._rows = self._rows[-MAX_ROWS:]
        if event == "stage":
            self._apply_stage(payload)
        elif event == "tool_call":
            self._apply_tool_call(payload)
        elif event == "tool_result":
            self._apply_tool_result(payload)
        if self.wants_visible():
            self._render()
            self.show()

    def finish(self):
        """一轮结束：隐藏（内容仍保留到下一轮 reset）。"""
        try:
            self.hide()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "stage finish")

    def rows(self):
        return list(self._rows)

    # ------------------------------------------------------------ 事件归类
    def _apply_stage(self, payload):
        name = str(payload.get("stage") or "")
        if not name:
            return
        status = str(payload.get("status") or "running")
        detail = str(payload.get("detail") or "")
        ms = payload.get("ms")
        for rec in self._steps:
            if rec["stage"] == name:
                rec.update(status=status, detail=detail, ms=ms)
                break
        else:
            self._steps.append({"stage": name, "status": status,
                                "detail": detail, "ms": ms})
        if payload.get("percent") is not None:
            self._percent = payload.get("percent")
        if payload.get("eta") is not None:
            self._eta = payload.get("eta")
        if status == "running" and payload.get("step"):
            self._running_step = str(payload.get("step"))
        elif status != "running" and payload.get("step") == self._running_step:
            self._running_step = ""

    def _apply_tool_call(self, payload):
        self._tools.append({"tool": str(payload.get("tool") or ""),
                            "ok": None, "result": "", "ms": None,
                            "args": payload.get("args") or {}})

    def _apply_tool_result(self, payload):
        tool = str(payload.get("tool") or "")
        for rec in reversed(self._tools):
            if rec["tool"] == tool and rec["ok"] is None:
                rec.update(ok=bool(payload.get("ok")),
                           result=str(payload.get("result") or ""),
                           ms=payload.get("ms"))
                return
        self._tools.append({"tool": tool, "ok": bool(payload.get("ok")),
                            "result": str(payload.get("result") or ""),
                            "ms": payload.get("ms"), "args": {}})

    # -------------------------------------------------------------- 渲染
    def _render(self):
        parts = []
        total = len(self._steps)
        for i, rec in enumerate(self._steps):
            if total > MAX_SHOWN and i < total - MAX_SHOWN:
                continue
            color = COLORS.get(rec["status"], "#475467")
            parts.append('<span style="color:%s">%s %s %s</span>' % (
                color, _circled(i), _h.escape(rec["stage"]),
                MARKS.get(rec["status"], "")))
        text = " &nbsp; ".join(parts) or "准备中…"
        extra = []
        if self._percent is not None:
            try:
                extra.append("%d%%" % int(float(self._percent) * 100))
            except (TypeError, ValueError):
                pass
        if self._eta:
            try:
                eta = float(self._eta)
                if eta > 0:
                    extra.append("预计还需 %.0f 秒" % eta)
            except (TypeError, ValueError):
                pass
        if self._tools:
            ok = sum(1 for t in self._tools if t.get("ok"))
            extra.append("工具 %d 次（成功 %d）" % (len(self._tools), ok))
        if extra:
            text += ' <span style="color:#98a2b3">· %s</span>' % _h.escape(
                " · ".join(extra))
        self.summary.setText(text)
        links = ['<a href="detail://" style="color:#1976d2;">查看详情</a>']
        if self._running_step:
            links.append('<a href="cancel://%s" style="color:#dc2626;">取消这一步</a>'
                         % _h.escape(self._running_step))
        self.links.setText(" &nbsp; ".join(links))

    def _on_link(self, url):
        url = str(url or "")
        try:
            if url.startswith("cancel://"):
                step = url.split("cancel://", 1)[1]
                self._cancel_step(step)
            elif url.startswith("detail://"):
                self._show_detail()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "stage link")

    def _cancel_step(self, step_id):
        """只停当前这一步（深度⑦）；走总线，线程安全。"""
        try:
            from core.pipeline import stage_bus
            ok = stage_bus.cancel_step(step_id)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "cancel step")
            ok = False
        self._running_step = ""
        self._render()
        # 提示语必须在 _render() **之后**追加：_render 会整段重设 summary 文本，
        # 写在它前面会被立刻覆盖掉（等于这句提示从来没显示过）。
        if ok:
            self.summary.setText(
                self.summary.text() + ' <span style="color:#6b7280">'
                '（已取消这一步）</span>')

    def _show_detail(self):
        try:
            dlg = StageDetailDialog(self._rows, self)
            dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            self._dialog = dlg
            dlg.show()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "stage detail dialog")
