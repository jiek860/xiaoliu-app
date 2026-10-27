# -*- coding: utf-8 -*-
"""v26-7.1: 日历+待办+笔记 统一工具对话框"""
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QTabWidget, QWidget, QMessageBox, QDateEdit, QTextBrowser
from PyQt5.QtCore import QDate, QTimer

from gui.feedback_states import make_action_links


class ToolsDialog(QDialog):
    """日历/待办/笔记 统一面板"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("实用工具")
        self.setMinimumSize(600, 500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # 日历 tab
        tab1 = QWidget()
        l1 = QVBoxLayout(tab1)
        row = QHBoxLayout()
        self.cal_title = QLineEdit()
        self.cal_title.setPlaceholderText("事件标题（回车添加）")
        self.cal_title.returnPressed.connect(self._add_cal)
        row.addWidget(self.cal_title)
        self.cal_date = QDateEdit()
        self.cal_date.setDate(QDate.currentDate())
        row.addWidget(self.cal_date)
        # 「添加」也可以直接敲回车 → 用链接表达，省一个按钮位
        row.addWidget(make_action_links([("添加", self._add_cal)]))
        row.addStretch(1)
        l1.addLayout(row)
        self.cal_list = QListWidget()
        l1.addWidget(self.cal_list)
        tabs.addTab(tab1, "日历")

        # 待办 tab
        tab2 = QWidget()
        l2 = QVBoxLayout(tab2)
        row2 = QHBoxLayout()
        self.todo_input = QLineEdit()
        self.todo_input.setPlaceholderText("待办事项（回车添加）")
        self.todo_input.returnPressed.connect(self._add_todo)
        row2.addWidget(self.todo_input)
        row2.addWidget(make_action_links([("添加", self._add_todo)]))
        row2.addStretch(1)
        l2.addLayout(row2)
        self.todo_list = QListWidget()
        l2.addWidget(self.todo_list)
        tabs.addTab(tab2, "待办")

        # 工作流 tab（复用现有对话框，不新增 GUI 文件/按钮）
        tab3 = QWidget()
        l3 = QVBoxLayout(tab3)
        row3 = QHBoxLayout()
        self.wf_name = QLineEdit()
        self.wf_name.setPlaceholderText("工作流名（回车运行）")
        self.wf_name.returnPressed.connect(self._run_workflow)
        row3.addWidget(self.wf_name)
        self.wf_input = QLineEdit()
        self.wf_input.setPlaceholderText("初始输入（可选）")
        row3.addWidget(self.wf_input)
        row3.addWidget(make_action_links([
            ("模板", self._create_templates),
            ("刷新", self._reload_workflows),
            ("运行", self._run_workflow),
        ]))
        l3.addLayout(row3)
        self.wf_list = QListWidget()
        self.wf_list.itemDoubleClicked.connect(
            lambda item: self._run_workflow(item.text()))
        l3.addWidget(self.wf_list)
        self.wf_result = QTextBrowser()
        self.wf_result.setReadOnly(True)
        l3.addWidget(self.wf_result, stretch=1)
        tabs.addTab(tab3, "工作流")
        self._wf_timer = QTimer(self)
        self._wf_timer.setInterval(1000)
        self._wf_timer.timeout.connect(self._poll_workflow)

        layout.addWidget(tabs)
        close_row = QHBoxLayout()
        close_row.addWidget(QLabel("Esc 关闭"))
        close_row.addStretch(1)
        layout.addLayout(close_row)
        self._reload_workflows()

    def _add_cal(self):
        title = self.cal_title.text().strip()
        if not title:
            return
        date = self.cal_date.date().toString("yyyy-MM-dd")
        self.cal_list.addItem("%s %s" % (date, title))
        self.cal_title.clear()
        QMessageBox.information(self, "成功", "已添加事件")

    def _add_todo(self):
        text = self.todo_input.text().strip()
        if not text:
            return
        self.todo_list.addItem("☐ " + text)
        self.todo_input.clear()

    def _reload_workflows(self):
        result = self.trunk.call("workflow_runner", "list_workflows")
        names = []
        if isinstance(result, list):
            names = [str(x) for x in result]
        elif isinstance(result, dict):
            if not result.get("ok"):
                err = result.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else str(err)
                self.wf_result.setPlainText("读取工作流失败: " + str(msg or "未知错误"))
                return
            names = [str(x) for x in (result.get("workflows") or [])]
        self.wf_list.clear()
        for name in names:
            self.wf_list.addItem(name)
        if names:
            self.wf_result.setPlainText("可用工作流：\n" + "\n".join(names))
        else:
            self.wf_result.setPlainText("暂无工作流；可在命令面板让 workflow_runner 创建模板")

    def _create_templates(self):
        result = self.trunk.call("workflow_runner", "ensure_templates")
        if not isinstance(result, dict) or not result.get("ok"):
            err = result.get("error") if isinstance(result, dict) else result
            msg = err.get("message") if isinstance(err, dict) else str(err)
            self.wf_result.setPlainText("创建模板失败: " + str(msg or "未知错误"))
            return
        written = result.get("written") or []
        existing = result.get("existing") or []
        self.wf_result.setPlainText(
            "已写入模板：%s\n已存在：%s" % (
                "、".join(written) or "无", "、".join(existing) or "无"))
        self._reload_workflows()

    def _run_workflow(self, name=None):
        current = name or self.wf_name.text().strip()
        if not current:
            self.wf_result.setPlainText("先填写工作流名，或双击列表中的工作流")
            return
        context = {"input": self.wf_input.text().strip()}
        result = self.trunk.call("workflow_runner", "start", current, context)
        if not isinstance(result, dict) or not result.get("ok"):
            err = result.get("error") if isinstance(result, dict) else result
            msg = err.get("message") if isinstance(err, dict) else str(err)
            self.wf_result.setPlainText("启动失败: " + str(msg or "未知错误"))
            return
        self.wf_name.setText(current)
        self.wf_result.setPlainText("已开始：%s\n运行中…" % current)
        self._wf_timer.start()

    def _poll_workflow(self):
        result = self.trunk.call("workflow_runner", "status")
        if not isinstance(result, dict) or not result.get("ok"):
            self._wf_timer.stop()
            self.wf_result.setPlainText("状态读取失败")
            return
        if result.get("running"):
            self.wf_result.setPlainText("运行中…")
            return
        self._wf_timer.stop()
        last = result.get("last") or {}
        lines = ["工作流：%s" % (last.get("workflow") or "未知"),
                 "结果：%s" % ("成功" if last.get("ok") else "失败")]
        if last.get("cancelled"):
            lines.append("状态：已取消")
        if last.get("failed_step"):
            lines.append("失败步骤：%s" % last.get("failed_step"))
        if last.get("error"):
            lines.append("错误：%s" % last.get("error"))
        for row in last.get("results") or []:
            if row.get("skipped"):
                continue
            if row.get("ok") is False:
                lines.append("- %s 失败: %s" % (row.get("step", ""),
                                            row.get("error", "")))
            else:
                value = row.get("result", "")
                lines.append("- %s: %s" % (row.get("step", ""),
                                          str(value)[:500]))
        self.wf_result.setPlainText("\n".join(lines))

    def closeEvent(self, event):
        self._wf_timer.stop()
        super().closeEvent(event)
