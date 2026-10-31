# -*- coding: utf-8 -*-
"""任务中心的富文本视图与失败引导（2026-10-31 拆分）。

从 `gui/task_center_dialog.py` 拆出（该文件已到 600 行上限）：
步骤/定时任务/trace 的 HTML 渲染，以及「下一步」引导条都在这里；
对话框只保留窗口搭建、事件订阅与动作执行。TaskCenterDialog 继承本 Mixin，
对外行为与入口不变。
"""
import html

from PyQt5.QtWidgets import QMessageBox

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


# 步骤状态 -> 显示文案 + 颜色（失败标红，可一眼定位）。
_STEP_STATUS = {
    "done": ("✅ 已完成", "#027a48"),
    "running": ("▶ 运行中", "#175cd3"),
    "failed": ("✗ 失败", "#b42318"),
    "paused": ("⏸ 已暂停", "#b54708"),
    "cancelled": ("⊘ 已取消", "#667085"),
    "pending": ("○ 待执行", "#667085"),
}
_LINK_CSS = "color:#1d4ed8;text-decoration:underline;font-size:12px;"


class TaskCenterViewMixin:
    def _empty_html(self):
        return (
            "<div style='font-size:13px;color:#475467;'>还没有任务。<br><br>"
            "输入目标后点「新建任务」，计划、步骤、确认和结果都会在这里显示。</div>"
            + self._schedule_html())

    def _step_html(self, step):
        sid = str(step.get("id") or "")
        status = str(step.get("status") or "pending")
        label, color = _STEP_STATUS.get(status, (status, "#667085"))
        out = [
            "<div style='margin-top:8px;'>",
            "<span style='color:%s;font-weight:600;'>%s</span> "
            "<span style='color:#667085;'>%s</span> "
            "<span style='color:%s;font-weight:600;'>[%s]</span> "
            "<span style='color:#344054;'>%s</span>"
            % (color, html.escape(label), html.escape(sid), color,
               html.escape(status), html.escape(str(step.get("title", ""))))
        ]
        if step.get("error"):
            out.append(
                "<div style='color:#b42318;margin:2px 0 0 14px;'>"
                "<b>为什么失败：</b>%s</div>"
                % html.escape(str(step.get("error"))[:300]))
        if step.get("result_preview") and not step.get("error"):
            out.append(
                "<div style='color:#667085;margin-left:14px;'>结果：%s</div>"
                % html.escape(str(step["result_preview"])[:300]))
        if status == "failed" or step.get("error"):
            out.append(
                "<div style='margin:2px 0 0 14px;'>%s</div>"
                % self._step_links(sid))
            out.append(self._trace_html(sid))
        out.append("</div>")
        return "".join(out)

    def _step_links(self, sid):
        return "　·　".join([
            self._link("重试此步", "step-retry", sid),
            self._link("换个做法", "step-replan"),
            self._link("补充说明", "step-ask"),
            self._link("失败经过", "step-trace", sid),
        ])

    @staticmethod
    def _link(label, scheme, arg=""):
        return "<a href='%s://%s' style='%s'>%s</a>" % (
            scheme, html.escape(str(arg), quote=True), _LINK_CSS,
            html.escape(str(label)))

    def _trace_html(self, sid):
        rows = self._step_events(sid)
        if not rows:
            return ""
        out = [
            "<div style='margin:4px 0 0 14px;color:#667085;font-size:11px;'>"
            "<a name='trace-%s'>失败经过（trace）：</a></div>"
            % html.escape(sid, quote=True),
        ]
        for ev in rows:
            kind = str(ev.get("kind") or ev.get("event") or "?")
            detail = str(ev.get("detail") or "")[:120]
            color = "#b42318" if ("fail" in kind.lower()
                                  or "error" in kind.lower()) else "#667085"
            out.append(
                "<div style='margin-left:22px;color:%s;font-size:11px;'>"
                "%s　%s　%s</div>"
                % (color, html.escape(str(ev.get("time") or "")),
                   html.escape(kind), html.escape(detail)))
        return "".join(out)

    def _step_events(self, sid):
        """复用 Trace 数据，在失败步骤处聚合展示（不再单独开 Trace 窗口）。"""
        if not sid or not hasattr(self.rt, "events"):
            return []
        try:
            return self.rt.events(self._current, step_id=sid, limit=12) or []
        except Exception as e:
            _x6_swallowed(__name__, e, "aggregate step trace")
            return []

    def _module(self, name):
        cache = getattr(self, "_module_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._module_cache = cache
        if name in cache:
            return cache[name]
        mods = getattr(self.trunk, "modules", None)
        if not isinstance(mods, dict):
            return None
        mod = mods.get(name)
        if mod is None:
            call = getattr(self.trunk, "call", None)
            if callable(call):
                try:
                    call(name, "__no__")
                except Exception as e:
                    _x6_swallowed(__name__, e, "lazy load " + name)
                mod = mods.get(name)
        cache[name] = mod
        return mod

    def _scheduled_jobs(self):
        runner = self._module("workflow_runner")
        jobs = []
        if runner is not None and hasattr(runner, "list_workflows"):
            try:
                for name in runner.list_workflows():
                    workflow = runner.load(name) \
                        if hasattr(runner, "load") else None
                    schedule = (workflow or {}).get("schedule")
                    if schedule:
                        jobs.append((str(name), str(schedule)))
            except Exception as e:
                _x6_swallowed(__name__, e, "list scheduled workflows")
        return runner, jobs

    def _schedule_html(self):
        """定时调度在任务中心里可见、可停用/启用、可改间隔、可立即运行。"""
        sc = self._module("scheduler")
        running = bool(getattr(sc, "running", False)) if sc else False
        if sc is None:
            state, control = "未安装调度模块", ""
        elif running:
            state = "运行中"
            control = "　%s" % self._link("停用调度", "schedule-stop")
        else:
            state = "已停用"
            control = "　%s" % self._link("启用调度", "schedule-start")
        if sc is not None:
            control += "　%s" % self._link("修改间隔", "schedule-interval")
        runner, jobs = self._scheduled_jobs()
        parts = [
            "<div style='margin-top:12px;font-weight:700;'>定时任务："
            "<span style='font-weight:400;color:%s;'>%s</span>%s</div>"
            % ("#027a48" if running else "#667085", html.escape(state),
               control),
        ]
        if not jobs:
            parts.append(
                "<div style='color:#667085;font-size:12px;'>"
                "暂无带 schedule 的工作流（可在 data/workflows 里配置）。</div>")
        for name, schedule in jobs[:8]:
            run_link = self._link("立即运行", "schedule-run", name) \
                if runner is not None else ""
            parts.append(
                "<div style='margin-left:14px;font-size:12px;'>"
                "· %s（%s）　%s</div>"
                % (html.escape(name), html.escape(schedule), run_link))
        return "".join(parts)

    def _update_guidance(self, task):
        if not task or task.get("status") not in (
                "failed", "cancelled", "paused", "completed"):
            self.guide_box.hide()
            self._guide_action = ""
            return
        if task.get("status") == "completed":
            self.guide_box.hide()
            return
        guide = None
        # 优先用运行时给出的恢复建议：同一步失败两次会建议「换方案」，
        # 超时/预算会建议加预算，环境问题直接指向设置/安全中心。
        try:
            rec = self.rt.recovery_suggestion(task.get("id")) \
                if hasattr(self.rt, "recovery_suggestion") else None
            if isinstance(rec, dict) and rec.get("ok"):
                guide = {"title": "为什么失败",
                         "message": str(rec.get("why") or ""),
                         "action": rec.get("action", "retry_failed_step"),
                         "action_label": rec.get("label", "下一步")}
        except Exception as e:  # 静默是故意的 - 建议失败不影响重试
            _x6_swallowed(__name__, e, "task recovery suggestion")
        if not guide:
            try:
                from gui.guidance import next_step_for_error
                guide = next_step_for_error(task.get("error", "") or
                                            task.get("status", ""))
            except Exception:  # 静默是故意的
                guide = {"title": "任务未完成", "message": "查看错误后重试。",
                         "action": "retry_failed_step",
                         "action_label": "重试失败步骤"}
        self._guide_action = guide.get("action", "")
        self.guide_label.setText(
            "<b>%s</b>　%s" % (html.escape(str(guide.get("title", ""))),
                               html.escape(str(guide.get("message", "")))))
        self._set_guide_link(guide.get("action_label", "下一步"))
        self.guide_box.show()

    def _set_guide_link(self, text):
        self.guide_btn.setText(
            '<a href="go" style="color:#1976d2;font-weight:600;">%s</a>'
            % html.escape(text or "下一步"))

    def _run_guide_action(self):
        action = self._guide_action
        p = self.parent()
        try:
            if action == "retry_failed_step":
                self._retry()
            elif action == "replan":
                self._replan()
            elif action == "ask_user":
                self._ask_user()
            elif action == "increase_task_budget":
                self._increase_budget()
            elif action == "open_plugin_market" and p is not None:
                p.plugin_dialog()
            elif action in ("open_security_center",
                            "open_security_network_events") and p is not None:
                p.security_center_dialog()
            elif action == "open_model_settings" and p is not None:
                p.set_dialog()
            else:
                self._retry()
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "下一步", str(e)[:120])
