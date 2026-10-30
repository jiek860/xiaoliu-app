# -*- coding: utf-8 -*-
"""成长面板（M1）：把批次 48 的反思闭环接到界面上。

只读 + 人工确认：低分样本、复现率、候选规则确认/撤销、周报。
逻辑全在 ``core.chat.fewshot``，本模块只负责展示与调用，
不新增按钮（用 ``make_action_links`` 的文字链接），不调模型。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QSplitter, QTextBrowser,
                             QVBoxLayout, QWidget)

from gui.feedback_states import make_action_links

try:
    from core.chat import fewshot
except ImportError:  # pragma: no cover
    fewshot = None


def failure_title(row):
    """列表行：类别 + 总分 + 用户摘要（脱敏后的短句）。"""
    if not isinstance(row, dict):
        return ""
    cat = str(row.get("类别") or "general")
    total = row.get("总分", "-")
    user = str(row.get("用户") or "").replace("\n", " ")[:48]
    return "[%s] %s 分 · %s" % (cat, total, user)


def failure_detail(row):
    """详情块：问题维度、回答摘要、复现与建议。"""
    if not isinstance(row, dict):
        return ""
    issues = row.get("问题") or []
    lines = [
        "类别：%s" % row.get("类别", "general"),
        "总分：%s" % row.get("总分", "-"),
        "问题：%s" % "、".join(str(i) for i in issues) if issues else "问题：-",
        "用户：%s" % str(row.get("用户") or ""),
        "回答：%s" % str(row.get("回答") or ""),
        "复现：%s 次 / 复查：%s 次" % (row.get("复现", 0), row.get("复查", 0)),
        "建议：%s" % (row.get("建议") or "-"),
        "状态：%s" % (row.get("状态") or "open"),
    ]
    return "\n".join(lines)


def stats_lines(stats):
    """把 failure_stats 字典翻成两行摘要。"""
    stats = stats or {}
    cats = stats.get("类别") or {}
    top = "、".join("%s×%s" % (k, v) for k, v in list(cats.items())[:4]) or "无"
    return [
        "样本 %s 条 · 未解决 %s 条 · 累计出现 %s 次"
        % (stats.get("总数", 0), stats.get("未解决", 0),
           stats.get("累计出现", 0)),
        "复现率 %s · 复查 %s 次 · 主要类别：%s"
        % (stats.get("复现率", 0), stats.get("复查次数", 0), top),
    ]


def candidate_title(item):
    if not isinstance(item, dict):
        return ""
    rule = item.get("rule") or {}
    return "[%s] %s · %s" % (item.get("status", "pending"),
                             item.get("category", "general"),
                             str(rule.get("value") or "")[:60])


def weekly_text(base, days=7, now=None):
    """近 N 天周报（纯规则统计，不生成自由文本）。"""
    if fewshot is None:
        return "成长模块不可用。"
    now = int(now or time.time())
    since = now - max(1, int(days)) * 86400
    rows = [r for r in fewshot.failure_rows(base)
            if int(r.get("ts") or 0) >= since]
    stats = fewshot.failure_stats(base)
    cands = fewshot.load_candidates(base).get("candidates") or []
    pending = [c for c in cands if c.get("status") == "pending"]
    active = [c for c in cands if c.get("status") == "active"]
    audit = fewshot.audit_rows(base, limit=10)
    lines = [
        "== 近 %d 天成长周报 ==" % days,
        "新增低分样本：%d 条" % len(rows),
        "累计样本：%s 条（未解决 %s）" % (stats.get("总数", 0),
                                        stats.get("未解决", 0)),
        "复现率：%s（复查 %s 次）" % (stats.get("复现率", 0),
                                    stats.get("复查次数", 0)),
        "待确认候选：%d 个 / 已生效规则：%d 条" % (len(pending), len(active)),
    ]
    for row in rows[-5:]:
        lines.append("· %s" % failure_title(row))
    if audit:
        lines.append("-- 最近操作 --")
        for row in audit[-5:]:
            lines.append("· %s %s (%s)" % (
                time.strftime("%Y-%m-%d %H:%M", time.localtime(
                    int(row.get("ts") or 0))),
                row.get("action", "?"), row.get("by", "user")))
    return "\n".join(lines)


class GrowthPanel(QWidget):
    """成长页：样本 / 候选 / 周报，全部人工确认。"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self._message = ""
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.summary = QLabel("暂无低分样本")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("低分样本（可复查/标记）"))
        self.failures = QListWidget()
        self.failures.currentRowChanged.connect(self._show_failure)
        lv.addWidget(self.failures)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("候选规则（必须人工确认）"))
        self.candidates = QListWidget()
        self.candidates.currentRowChanged.connect(self._show_candidate)
        rv.addWidget(self.candidates)
        split.addWidget(right)
        split.setSizes([320, 280])
        layout.addWidget(split, 2)

        self.detail = QTextBrowser()
        self.detail.setMaximumHeight(150)
        layout.addWidget(self.detail)

        row = QHBoxLayout()
        row.addWidget(make_action_links([
            ("复查低分", self._recheck),
            ("生成候选", self._promote),
            ("确认候选", self._confirm),
            ("撤销规则", self._revoke),
            ("标记已解决", self._resolve),
            ("刷新", self._refresh_all),
        ]))
        row.addStretch(1)
        layout.addLayout(row)

        self.report = QTextBrowser()
        self.report.setMaximumHeight(140)
        layout.addWidget(self.report)

    # ------------------------------------------------------------------
    def refresh(self):
        if fewshot is None:
            self.summary.setText("成长模块不可用（core.chat.fewshot 导入失败）")
            return
        try:
            stats = fewshot.failure_stats(self.base)
            self.summary.setText("  |  ".join(stats_lines(stats)))
            self.failures.clear()
            for row in reversed(fewshot.failure_rows(self.base)[-50:]):
                item = QListWidgetItem(failure_title(row))
                item.setData(Qt.UserRole, row.get("id"))
                self.failures.addItem(item)
            self.candidates.clear()
            for cand in fewshot.load_candidates(self.base).get("candidates") or []:
                item = QListWidgetItem(candidate_title(cand))
                item.setData(Qt.UserRole, cand.get("id"))
                self.candidates.addItem(item)
            self.report.setPlainText(self._message or weekly_text(self.base))
        except Exception as e:
            _x6_swallowed(__name__, e, "refresh growth panel")
            self.summary.setText("读取成长数据失败，已跳过本次刷新")

    # ------------------------------------------------------------------
    def _selected_id(self, widget):
        item = widget.currentItem()
        return "" if item is None else str(item.data(Qt.UserRole) or "")

    def _show_failure(self, row):
        if fewshot is None:
            return
        fid = self._selected_id(self.failures)
        for item in fewshot.failure_rows(self.base):
            if item.get("id") == fid:
                self.detail.setPlainText(failure_detail(item))
                return

    def _show_candidate(self, row):
        if fewshot is None:
            return
        cid = self._selected_id(self.candidates)
        for item in fewshot.load_candidates(self.base).get("candidates") or []:
            if item.get("id") == cid:
                self.detail.setPlainText(candidate_title(item))

    # ------------------------------------------------------------------
    def _say(self, text):
        self._message = str(text)
        self.report.setPlainText(self._message)

    def _refresh_all(self):
        """回到周报视图（清掉上一次动作提示）。"""
        self._message = ""
        self.refresh()

    def _recheck(self):
        if fewshot is None:
            return
        try:
            out = fewshot.recheck_failures(self.base)
            self._say("复查 %s 条：复现 %s，达标转已解决 %s，复现率 %s"
                      % (out.get("checked"), out.get("reproduced"),
                         out.get("resolved"), out.get("复现率")))
        except Exception as e:  # 面板动作失败只提示，不静默
            _x6_swallowed(__name__, e, "recheck failures")
            self._say("复查失败：%s" % e)
        self.refresh()

    def _promote(self):
        if fewshot is None:
            return
        try:
            out = fewshot.promote_candidates(self.base)
            self._say("新增候选 %s 个（同类 ≥%s 次才生成）"
                      % (out.get("created"), out.get("threshold")))
        except Exception as e:
            _x6_swallowed(__name__, e, "promote candidates")
            self._say("生成候选失败：%s" % e)
        self.refresh()

    def _confirm(self):
        cid = self._selected_id(self.candidates)
        if not cid:
            self._say("先在右上候选列表里选一条")
            return
        self._decide(cid, "confirm")

    def _revoke(self):
        cid = self._selected_id(self.candidates)
        if not cid:
            self._say("先选一条已生效候选")
            return
        self._decide(cid, "revoke")

    def _decide(self, cid, action):
        if fewshot is None:
            return
        try:
            out = fewshot.decide_candidate(self.base, cid, action, by="user")
            self._say(("已确认并生效：%s" if action == "confirm"
                       else "已撤销：%s") % candidate_title(out.get("candidate")))
        except Exception as e:
            _x6_swallowed(__name__, e, "decide candidate")
            self._say("操作失败：%s" % e)
        self.refresh()

    def _resolve(self):
        fid = self._selected_id(self.failures)
        if not fid:
            self._say("先在左侧样本列表里选一条")
            return
        try:
            fewshot.mark_failure(self.base, fid, "resolved")
            self._say("已标记为 resolved")
        except Exception as e:
            _x6_swallowed(__name__, e, "mark failure")
            self._say("标记失败：%s" % e)
        self.refresh()
