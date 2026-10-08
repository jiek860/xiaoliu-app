# -*- coding: utf-8 -*-
"""数据导出/导入：日志包、数据备份、恢复"""
import os
import zipfile
import datetime
from PyQt5.QtWidgets import QMessageBox, QFileDialog


class DataExporter:
    def __init__(self, trunk, base_dir, parent_widget):
        self.trunk = trunk
        self.base = base_dir
        self.parent = parent_widget

    def export_logs(self):
        """导出日志包"""
        try:
            desk = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out = os.path.join(desk, f"小6日志_{ts}.zip")
            data = os.path.join(self.base, "data")
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                logs_dir = os.path.join(data, "logs")
                if os.path.exists(logs_dir):
                    for root, _, files in os.walk(logs_dir):
                        for f in files:
                            p = os.path.join(root, f)
                            z.write(p, os.path.relpath(p, data))
            QMessageBox.information(self.parent, "导出成功", "已打包到:\n" + out)
        except Exception as e:
            QMessageBox.warning(self.parent, "导出失败", str(e))

    def export_data(self):
        """导出数据备份"""
        try:
            desk = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out = os.path.join(desk, f"小6数据备份_{ts}.zip")
            data = os.path.join(self.base, "data")
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _, files in os.walk(data):
                    for f in files:
                        fp = os.path.join(root, f)
                        z.write(fp, os.path.relpath(fp, self.base))
            QMessageBox.information(self.parent, "导出成功", "已备份到:\n" + out)
        except Exception as e:
            QMessageBox.warning(self.parent, "导出失败", str(e))

    def import_data(self):
        """导入数据备份"""
        fn, _ = QFileDialog.getOpenFileName(self.parent, "选择数据备份 zip", "", "Zip (*.zip)")
        if not fn:
            return
        r = QMessageBox.question(self.parent, "确认恢复", "将覆盖当前 data/ 目录，继续？",
                                 QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        try:
            with zipfile.ZipFile(fn) as z:
                z.extractall(self.base)
            QMessageBox.information(self.parent, "完成", "数据已恢复，建议重启程序。")
        except Exception as e:
            QMessageBox.warning(self.parent, "恢复失败", str(e))
