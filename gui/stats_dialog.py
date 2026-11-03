# -*- coding: utf-8 -*-
"""v26-6.2: 数据统计报表（GUI 对话框）

数值全部来自 ``core.stats_report.StatsReport``，这里只负责展示与导出 ——
原来本文件自己又写了一套 ``SELECT COUNT(*)``，两套口径迟早对不上
（事实也确实对不上：能力表里的「日历事件」和这里曾经都不区分
「真的 0 条」和「读失败」）。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:      # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, \
    QTextBrowser, QComboBox

from gui.feedback_states import make_action_links


class StatsDialog(QDialog):
    """数据统计报表对话框"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("数据统计")
        self.setMinimumSize(700, 600)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("时间范围:"))
        self.period = QComboBox()
        self.period.addItems(["今天", "本周", "本月", "全部"])
        self.period.setCurrentText("全部")
        self.period.currentIndexChanged.connect(self._refresh)
        top.addWidget(self.period)
        top.addStretch(1)
        # 「导出」是纯展示弹窗里的次要动作：链接同样能点，不占按钮预算
        top.addWidget(make_action_links([("导出 Markdown", self._export_md)]))
        layout.addLayout(top)
        self.tb = QTextBrowser()
        layout.addWidget(self.tb)

    def _refresh(self):
        self.tb.setMarkdown(self._render_md(self._collect()))

    def _collect(self):
        """结构化统计；读失败时 StatsReport 会标 status=失败（不再是 0）"""
        try:
            from core.stats_report import StatsReport
            return StatsReport(self.trunk).generate(self.period.currentText())
        except Exception as e:
            _x6_swallowed(__name__, e, "stats collect")
            return {"ok": False, "范围": self.period.currentText(),
                    "统计": {}, "合计": 0,
                    "说明": "统计模块不可用：%s" % str(e)[:80]}

    def _render_md(self, data):
        try:
            from core.stats_report import StatsReport
            return StatsReport(self.trunk).to_markdown(
                self.period.currentText())
        except Exception as e:
            _x6_swallowed(__name__, e, "stats render")
            return "# 小6使用统计\n\n统计模块不可用：%s\n" % str(e)[:80]

    def _export_md(self):
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(self, "导出", "stats.md",
                                              "Markdown (*.md)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.tb.toMarkdown())
        except Exception as e:
            QMessageBox.warning(self, "导出失败", "写入失败：%s" % str(e)[:80])
            return
        QMessageBox.information(self, "成功", "已导出: " + path)
