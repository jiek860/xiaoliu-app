# -*- coding: utf-8 -*-
"""过程可见：回复步骤 / 工具调用事件总线（第 5 批 A4 + 深度⑥⑦⑧）。

设计要点：
- **core 不 import 任何界面库**。这里只做"记 + 广播"，GUI 用订阅回调把事件
  转成 Qt 信号（跨线程 emit 由 Qt 自动排队），于是离线测试也不需要 Qt。
- **每个事件都是扁平 dict**，GUI 直接拿去填步骤条，不用再解析。
- **单步取消**：``Step.cancel()`` 只停当前这一步；如果是"模型生成"这种长步骤，
  ``on_cancel`` 会顺手把取消令牌也点掉（真正的流式停止）。
- **进度 ETA**：``Progress`` 按已完成步骤的平均耗时估算剩余时间，不猜假数据。

事件形状::

    {"event": "stage", "stage": "模型生成", "status": "running",
     "detail": "…", "step": "s3", "seq": 12, "percent": 0.5,
     "eta": 4.2, "elapsed": 3.1, "done": 3, "total": 6}
    {"event": "tool_call", "tool": "code_runner", "args": {...}, "step": "s4"}
    {"event": "tool_result", "tool": "code_runner", "ok": True,
     "result": "运行成功 42", "ms": 820, "step": "s4"}

状态：running / ok / fail / cancelled / skipped。
"""
import threading
import time
from collections import deque

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MAX_EVENTS = 200
MAX_DETAIL = 200
STATUSES = ("running", "ok", "fail", "cancelled", "skipped")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

_LOCK = threading.RLock()
_SUBSCRIBERS = []
_EVENTS = deque(maxlen=MAX_EVENTS)
_STEPS = {}
_STATE = {"progress": None, "seq": 0, "step_seq": 0}


# ---------------------------------------------------------------- 订阅 / 广播
def subscribe(callback):
    """订阅事件：callback(event, payload)。返回 True/False，重复订阅不报错。"""
    if not callable(callback):
        return False
    with _LOCK:
        if callback not in _SUBSCRIBERS:
            _SUBSCRIBERS.append(callback)
    return True


def unsubscribe(callback):
    """取消订阅；没订阅过也返回 False，不抛异常。"""
    with _LOCK:
        try:
            _SUBSCRIBERS.remove(callback)
            return True
        except ValueError:
            return False


def subscriber_count():
    with _LOCK:
        return len(_SUBSCRIBERS)


def emit(event, payload=None):
    """广播一个事件，并留最近 MAX_EVENTS 条在内存里（供"查看详情"用）。"""
    data = dict(payload or {})
    data["event"] = str(event)
    with _LOCK:
        _STATE["seq"] += 1
        data.setdefault("seq", _STATE["seq"])
        data.setdefault("time", round(time.time(), 3))
        _EVENTS.append(data)
        callbacks = list(_SUBSCRIBERS)
    for cb in callbacks:
        try:
            cb(data["event"], data)
        except Exception as e:  # 静默是故意的 - 一个订阅者坏了不能拖垮回复
            _x6_swallowed(__name__, e, "stage subscriber")
    return data


def clear_events():
    with _LOCK:
        _EVENTS.clear()


def reset():
    """清空订阅者/事件/步骤/进度。测试和"新建会话"用，不影响正在跑的旧引用。"""
    with _LOCK:
        del _SUBSCRIBERS[:]
        _EVENTS.clear()
        _STEPS.clear()
        _STATE["progress"] = None
        _STATE["seq"] = 0
        _STATE["step_seq"] = 0


def snapshot(limit=20):
    """最近 N 条事件（按发生顺序）。"""
    with _LOCK:
        rows = list(_EVENTS)
    if limit and limit > 0:
        return rows[-int(limit):]
    return rows


def events_by_kind(kind):
    with _LOCK:
        rows = list(_EVENTS)
    return [r for r in rows if str(r.get("event")) == str(kind)]


# ------------------------------------------------------------------- 进度 ETA
class Progress:
    """一次回复的进度：已完成步数 / 百分比 / 预计剩余秒数。"""

    def __init__(self, total=6, now=None, eta=True):
        self.total = max(1, int(total or 1))
        self.done = 0
        self.started = float(now if now is not None else time.time())
        self.durations = []
        self.with_eta = bool(eta)

    def finish(self, seconds=None, now=None):
        if self.done >= self.total:
            return self.snapshot(now=now)
        self.done += 1
        if seconds is not None:
            try:
                self.durations.append(max(0.0, float(seconds)))
            except (TypeError, ValueError):
                pass
        return self.snapshot(now=now)

    def average(self, now=None):
        """平均每步秒数：优先用已完成步骤的真实耗时，没有就用总耗时推算。"""
        if self.durations:
            return sum(self.durations) / float(len(self.durations))
        if not self.done:
            return 0.0
        now = float(now if now is not None else time.time())
        return max(0.0, now - self.started) / float(self.done)

    def snapshot(self, now=None):
        now = float(now if now is not None else time.time())
        elapsed = max(0.0, now - self.started)
        remaining = max(0, self.total - self.done)
        out = {
            "percent": round(min(1.0, self.done / float(self.total)), 3),
            "done": self.done,
            "total": self.total,
            "elapsed": round(elapsed, 1),
        }
        if self.with_eta:
            out["eta"] = round(self.average(now=now) * remaining, 1)
        return out


def begin_run(total=6, now=None, eta=True):
    """开一轮进度追踪（一次回复 = 一轮）。"""
    progress = Progress(total=total, now=now, eta=eta)
    with _LOCK:
        _STATE["progress"] = progress
    return progress


def current_progress():
    with _LOCK:
        return _STATE["progress"]


def progress_snapshot(now=None):
    progress = current_progress()
    if progress is None:
        return {}
    try:
        return progress.snapshot(now=now)
    except Exception as e:
        _x6_swallowed(__name__, e, "progress snapshot")
        return {}


# ------------------------------------------------------------------- 步骤对象
class Step:
    """一个可见步骤：running → ok / fail / cancelled / skipped。"""

    def __init__(self, sid, name, detail="", on_cancel=None):
        self.sid = str(sid)
        self.name = str(name or "")
        self.detail = str(detail or "")[:MAX_DETAIL]
        self.status = "running"
        self.started = time.time()
        self.ended = None
        self._on_cancel = on_cancel if callable(on_cancel) else None

    @property
    def cancelled(self):
        return self.status == "cancelled"

    @property
    def finished(self):
        return self.status != "running"

    def elapsed(self):
        end = self.ended if self.ended is not None else time.time()
        return max(0.0, end - self.started)

    def cancel(self, reason="已取消这一步"):
        """取消这一步；长步骤会顺手触发它的 on_cancel（例如停掉流式生成）。"""
        if self.finished:
            return False
        self.status = "cancelled"
        try:
            if self._on_cancel is not None:
                self._on_cancel()
        except Exception as e:  # 静默是故意的 - 取消钩子失败不能挡住取消
            _x6_swallowed(__name__, e, "step on_cancel")
        stage(self.name, status="cancelled", detail=reason, step=self.sid)
        return True

    def __repr__(self):
        return "<Step %s %s %s>" % (self.sid, self.name, self.status)


def begin_step(name, detail="", on_cancel=None, step_id=None):
    """开始一步：登记 + 广播 running 事件，返回 Step。"""
    with _LOCK:
        _STATE["step_seq"] += 1
        sid = str(step_id or ("s%d" % _STATE["step_seq"]))
        step = Step(sid, name, detail, on_cancel=on_cancel)
        _STEPS[sid] = step
        # 只留最近 50 个，避免长会话无限增长
        if len(_STEPS) > 50:
            for old in list(_STEPS.keys())[:-50]:
                _STEPS.pop(old, None)
    stage(step.name, status="running", detail=step.detail, step=sid)
    return step


def get_step(sid):
    with _LOCK:
        return _STEPS.get(str(sid))


def end_step(step, status="ok", detail="", now=None):
    """结束一步：广播终态 + 推进进度（skipped 不计入进度）。"""
    if step is None:
        return {}
    status = status if status in STATUSES else "ok"
    if step.finished:
        status = step.status          # 已经取消/结束过的，不覆盖成 ok
    step.status = status
    step.ended = float(now if now is not None else time.time())
    if detail:
        step.detail = str(detail)[:MAX_DETAIL]
    if status != "skipped":
        progress = current_progress()
        if progress is not None:
            progress.finish(seconds=step.elapsed(), now=now)
    # stage() 会自己带上最新的 percent/eta
    return stage(step.name, status=status, detail=step.detail, step=step.sid,
                 ms=int(step.elapsed() * 1000))


def cancel_step(target):
    """按 Step 或 id 取消一步（GUI 的"取消这一步"链接走这里）。"""
    step = target if isinstance(target, Step) else get_step(target)
    if step is None:
        return False
    return step.cancel()


def running_step():
    """最近一个还在跑的步骤（供"取消这一步"定位）。"""
    with _LOCK:
        rows = list(_STEPS.values())
    for step in reversed(rows):
        if step.status == "running":
            return step
    return None


# --------------------------------------------------------------------- 事件壳
def stage(name, status="running", detail="", step=None, **extra):
    """广播一条步骤事件（进度信息自动带上）。"""
    payload = {"stage": str(name), "status": str(status),
               "detail": str(detail or "")[:MAX_DETAIL]}
    if step:
        payload["step"] = str(step)
    payload.update(progress_snapshot())
    payload.update({k: v for k, v in extra.items() if v is not None})
    return emit("stage", payload)


def tool_call(tool, args=None, step=None):
    """工具开始调用（深度⑥）：带参数，GUI 可展开成调用卡片。"""
    return emit("tool_call", {"tool": str(tool),
                              "args": dict(args or {}) if isinstance(args, dict)
                              else {"input": str(args)[:MAX_DETAIL]},
                              "step": str(step) if step else ""})


def tool_result(tool, ok=True, result="", ms=None, step=None):
    """工具调用结束（深度⑥）：带结果与耗时。"""
    return emit("tool_result", {"tool": str(tool), "ok": bool(ok),
                                "result": str(result or "")[:500],
                                "ms": int(ms) if ms is not None else None,
                                "step": str(step) if step else ""})


def circled(index):
    """① ② ③ …（第 10 个以后用数字），供步骤条排版。"""
    try:
        i = int(index)
    except (TypeError, ValueError):
        return ""
    if 0 <= i < len(CIRCLED):
        return CIRCLED[i]
    return "%d." % (i + 1)


def format_line(payload):
    """把一条 stage 事件压成一行中文（GUI 步骤条 / 日志共用，纯字符串无 Qt）。"""
    payload = payload or {}
    name = str(payload.get("stage") or "")
    status = str(payload.get("status") or "running")
    detail = str(payload.get("detail") or "")
    mark = {"running": "…", "ok": "✓", "fail": "✗",
            "cancelled": "⏹", "skipped": "⏭"}.get(status, "")
    head = "%s %s" % (mark, name) if name else mark
    if detail:
        head = "%s：%s" % (head, detail)
    extra = []
    if payload.get("percent") is not None:
        try:
            extra.append("%d%%" % int(float(payload["percent"]) * 100))
        except (TypeError, ValueError):
            pass
    if str(status) == "running" and payload.get("eta"):
        try:
            eta = float(payload["eta"])
            if eta > 0:
                extra.append("预计还需 %.0f 秒" % eta)
        except (TypeError, ValueError):
            pass
    if payload.get("ms"):
        try:
            extra.append("%.1f 秒" % (float(payload["ms"]) / 1000.0))
        except (TypeError, ValueError):
            pass
    return "%s（%s）" % (head, " · ".join(extra)) if extra else head


def format_events(rows=None, limit=40):
    """把事件列表压成多行中文，供"查看详情"弹窗直接显示。"""
    rows = list(rows if rows is not None else snapshot(limit))
    lines = []
    for row in rows[-int(limit or 40):]:
        kind = str(row.get("event") or "")
        if kind == "tool_call":
            args = row.get("args") or {}
            brief = ", ".join("%s=%s" % (k, str(v)[:40]) for k, v in args.items())
            lines.append("▶ 调用 %s(%s)" % (row.get("tool", ""), brief))
        elif kind == "tool_result":
            mark = "✓" if row.get("ok") else "✗"
            ms = row.get("ms")
            cost = (" %.1f 秒" % (float(ms) / 1000.0)) if ms else ""
            lines.append("%s %s 返回：%s%s" % (mark, row.get("tool", ""),
                                              str(row.get("result") or "")[:200], cost))
        else:
            lines.append(format_line(row))
    return "\n".join(lines)
