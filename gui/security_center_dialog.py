# -*- coding: utf-8 -*-
"""安全中心：权限、网络、审计和紧急停止。"""
import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTabWidget, QWidget, QTableWidget, QTableWidgetItem, QMessageBox,
    QFileDialog, QInputDialog)


class SecurityCenterDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle(" 安全中心")
        self.resize(860, 620)
        self._build()
        self._refresh()

    def _build(self):
        lay = QVBoxLayout(self)
        self.summary = QLabel("正在加载安全状态")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            "background:#f0f7ff;border:1px solid #bcdcff;border-radius:8px;"
            "padding:10px;color:#1f3b57;")
        lay.addWidget(self.summary)
        top = QHBoxLayout()
        top.addWidget(QLabel("网络模式:"))
        self.net_mode = QComboBox()
        self.net_mode.addItems(["off", "learning", "standard", "strict"])
        sec = (self.trunk.config.get("security") or {})
        self.net_mode.setCurrentText(sec.get("network_mode", "standard"))
        top.addWidget(self.net_mode)
        self.lock_btn = QPushButton(" 紧急停止")
        self.lock_btn.setStyleSheet("background:#dc2626;color:white;font-weight:bold;padding:6px 14px;")
        self.lock_btn.clicked.connect(self._toggle_lock)
        top.addWidget(self.lock_btn)
        save = QPushButton("保存")
        save.clicked.connect(self._save)
        top.addWidget(save)
        top.addStretch(1)
        lay.addLayout(top)

        self.tabs = QTabWidget()
        self.audit = QTableWidget(0, 5)
        self.audit.setHorizontalHeaderLabels(["时间", "对象", "决定", "结果", "原因"])
        self.perms = QTableWidget(0, 6)
        self.perms.setHorizontalHeaderLabels(
            ["ID", "对象", "范围", "约束", "命中次数", "最后命中"])
        self.net = QTableWidget(0, 6)
        self.net.setHorizontalHeaderLabels(["时间", "模块", "目的", "域名", "允许", "原因"])
        for t in (self.audit, self.perms, self.net):
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            t.horizontalHeader().setStretchLastSection(True)
        w1 = QWidget(); l1 = QVBoxLayout(w1); l1.addWidget(self.audit)
        w2 = QWidget(); l2 = QVBoxLayout(w2); l2.addWidget(self.perms)
        w3 = QWidget(); l3 = QVBoxLayout(w3); l3.addWidget(self.net)
        self.tabs.addTab(w1, "审计")
        self.tabs.addTab(w2, "工具权限")
        self.tabs.addTab(w3, "网络")
        lay.addWidget(self.tabs)
        actions = QHBoxLayout()
        revoke = QPushButton("撤销选中权限")
        revoke.clicked.connect(self._revoke)
        edit_scope = QPushButton("编辑规则范围")
        edit_scope.clicked.connect(self._edit_scope)
        export = QPushButton("导出审计")
        export.clicked.connect(self._export)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh)
        actions.addWidget(revoke)
        actions.addWidget(edit_scope)
        actions.addWidget(export)
        actions.addWidget(refresh)
        actions.addStretch(1)
        lay.addLayout(actions)

    def _fill(self, table, rows, cols):
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, key in enumerate(cols):
                table.setItem(i, j, QTableWidgetItem(str(r.get(key, ""))[:200]))

    def _refresh(self):
        from core.permission_center import get_permission_center
        from core.net_guard import get_net_guard
        pc = get_permission_center(self.trunk)
        self._fill(self.audit, pc.list_audit(100),
                   ["time", "subject", "decision", "result", "reason"])
        rules = []
        for r in pc.list_rules():
            r = dict(r)
            r["constraints"] = json.dumps(r.get("constraints") or {},
                                          ensure_ascii=False)
            r["hit_count"] = r.get("hit_count", 0)
            ts = r.get("last_hit_at")
            r["last_hit_at"] = (__import__("time").strftime(
                "%m-%d %H:%M:%S", __import__("time").localtime(ts))
                if ts else "")
            rules.append(r)
        self._fill(self.perms, rules,
                   ["id", "subject", "scope", "constraints", "hit_count",
                    "last_hit_at"])
        self._fill(self.net, get_net_guard(self.trunk).list_recent(100),
                   ["time", "module", "purpose", "domain", "allow", "reason"])
        audit = pc.list_audit(100)
        denied = sum(1 for a in audit
                     if str(a.get("decision")) == "deny"
                     or str(a.get("result")) in ("blocked", "cancel"))
        mode = (self.trunk.config.get("security") or {}).get(
            "network_mode", "standard")
        self.summary.setText(
            "小6当前能做：聊天、只读检索、已授权工具、任务执行。\n"
            "网络模式：%s　工具权限规则：%d 条　最近拒绝：%d 次　"
            "紧急锁定：%s\n"
            "需要撤销权限时切到『工具权限』选中规则；"
            "需要立即停止时点右上角『紧急停止』。"
            % (mode, len(pc.list_rules()), denied,
               "是" if pc.locked else "否"))
        locked = pc.locked
        self.lock_btn.setText(" 解除锁定" if locked else " 紧急停止")
        self.lock_btn.setStyleSheet(
            "background:%s;color:white;font-weight:bold;padding:6px 14px;"
            % ("#16a34a" if locked else "#dc2626"))

    def _toggle_lock(self):
        from core.permission_center import get_permission_center
        pc = get_permission_center(self.trunk)
        if not pc.locked:
            if QMessageBox.question(
                    self, "紧急停止",
                    "将立即阻断所有写/执行/控制类工具和出站网络，确定吗？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                return
        pc.lockdown(not pc.locked)
        self._refresh()

    def _revoke(self):
        row = self.perms.currentRow()
        if row < 0:
            QMessageBox.information(self, "安全中心", "请先在『工具权限』里选中一条规则")
            return
        item = self.perms.item(row, 0)
        rule_id = item.text() if item else ""
        if not rule_id:
            return
        from core.permission_center import get_permission_center
        if get_permission_center(self.trunk).revoke(rule_id):
            self._refresh()
        else:
            QMessageBox.warning(self, "安全中心", "撤销失败或规则不存在")

    def _edit_scope(self):
        row = self.perms.currentRow()
        if row < 0:
            QMessageBox.information(self, "安全中心", "请先选中一条权限规则")
            return
        rule_id = self.perms.item(row, 0).text() if self.perms.item(row, 0) else ""
        current = self.perms.item(row, 3).text() if self.perms.item(row, 3) else "{}"
        text, ok = QInputDialog.getMultiLineText(
            self, "编辑规则范围",
            "约束 JSON（空对象表示不限制）：\n"
            "支持 path_prefix / file_ext / domain / max_size",
            current)
        if not ok:
            return
        try:
            constraints = json.loads(text or "{}")
            if not isinstance(constraints, dict):
                raise ValueError("必须是 JSON 对象")
        except Exception as e:
            QMessageBox.warning(self, "安全中心", "约束 JSON 非法: %s" % e)
            return
        from core.permission_center import get_permission_center
        r = get_permission_center(self.trunk).update_constraints(
            rule_id, constraints)
        if not r.get("ok"):
            QMessageBox.warning(self, "安全中心", r.get("error", "更新失败"))
        self._refresh()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出审计", "audit_export.json", "JSON (*.json)")
        if not path:
            return
        from core.permission_center import get_permission_center
        r = get_permission_center(self.trunk).audit.export_redacted(path, 1000)
        QMessageBox.information(self, "安全中心",
                                "已导出 %d 条到\n%s"
                                % (r.get("count", 0), r.get("path", "")))

    def _save(self):
        self.trunk.config.setdefault("security", {})
        self.trunk.config["security"]["network_mode"] = self.net_mode.currentText()
        self.trunk.save_config()
        QMessageBox.information(self, "安全中心", "网络模式已保存")
        self._refresh()
