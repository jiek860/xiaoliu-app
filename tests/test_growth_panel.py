# -*- coding: utf-8 -*-
"""成长面板（M1）逻辑与空态测试。"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.chat import fewshot  # noqa: E402
from gui import chat_growth_panel as gp  # noqa: E402


def _seed(base):
    os.makedirs(os.path.join(base, "data"), exist_ok=True)
    fewshot.record_failure(
        base, "这个函数为什么报错", "不知道，你自己看",
        category="accuracy", suggestion="先解释报错位置", enabled=True)
    fewshot.record_failure(
        base, "帮我改一下这个函数", "好的，已改", category="useful", enabled=True)
    fewshot.promote_candidates(base, threshold=1)


def test_stats_lines_and_titles(tmp_path):
    base = str(tmp_path)
    _seed(base)
    stats = fewshot.failure_stats(base)
    lines = gp.stats_lines(stats)
    assert len(lines) == 2
    assert "未解决" in lines[0] and "复现率" in lines[1]
    row = fewshot.failure_rows(base)[0]
    assert row["类别"] in gp.failure_title(row)
    detail = gp.failure_detail(row)
    assert "用户：" in detail and "回答：" in detail
    cand = fewshot.load_candidates(base)["candidates"][0]
    assert "pending" in gp.candidate_title(cand)


def test_weekly_text_counts_and_audit(tmp_path):
    base = str(tmp_path)
    _seed(base)
    text = gp.weekly_text(base, days=7)
    assert "成长周报" in text
    assert "新增低分样本" in text and "待确认候选" in text


def test_panel_actions(tmp_path):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    base = str(tmp_path)
    _seed(base)
    panel = gp.GrowthPanel(SimpleNamespace(base=base))
    assert panel.failures.count() >= 2
    assert panel.candidates.count() >= 1
    panel.failures.setCurrentRow(0)
    panel._resolve()
    assert panel.report.toPlainText().startswith("已标记")
    panel.recheck_reported = panel._recheck()
    panel.candidates.setCurrentRow(0)
    panel._confirm()
    assert panel.report.toPlainText().startswith("已确认")
    assert fewshot.promoted_rules(base)
    panel.candidates.setCurrentRow(0)
    panel._revoke()
    assert panel.report.toPlainText().startswith("已撤销")
    assert not fewshot.promoted_rules(base)
    app.processEvents()
    panel.deleteLater()


def test_panel_empty_state(tmp_path):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    panel = gp.GrowthPanel(SimpleNamespace(base=str(tmp_path)))
    assert "样本 0 条" in panel.summary.text() or "暂无" in panel.summary.text()
    assert panel.failures.count() == 0
    app.processEvents()
    panel.deleteLater()
