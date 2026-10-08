# -*- coding: utf-8 -*-
"""系统混入：状态栏刷新、数据导出导入"""
import os
import json
import zipfile
import datetime
from PyQt5.QtWidgets import QMessageBox, QFileDialog


class SystemMixin:
    """系统相关方法"""
    def _update_status(self):
        try:
            n = len(self.trunk.modules) + len(self.trunk._lazy)
            mode = self.trunk.config.get("model_mode", "?")
            model = self.trunk.config.get(
                "cloud_model" if "云端" in str(mode) else "local_model", "?"
            )
            self.statusBar().showMessage(
                "✅ 就绪 | 模块:%d | 模型:%s(%s) | %s" % (
                    n, model, mode,
                    datetime.datetime.now().strftime("%H:%M")), 5000)
        except Exception:
            pass

    def export_logs(self):
        try:
            desk = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out = os.path.join(desk, f"小6日志_{ts}.zip")
            data = os.path.join(self.base, "data")
            n = 0
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                logs = os.path.join(data, "logs")
                if os.path.isdir(logs):
                    for f in os.listdir(logs):
                        p = os.path.join(logs, f)
                        if os.path.isfile(p):
                            z.write(p, "logs/" + f)
                            n += 1
            QMessageBox.information(self, "导出成功",
                                    "已打包 %d 个文件到:\n%s" % (n, out))
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def export_data(self):
        try:
            desk = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out = os.path.join(desk, f"小6数据备份_{ts}.zip")
            data = os.path.join(self.base, "data")
            n = 0
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _, files in os.walk(data):
                    for f in files:
                        fp = os.path.join(root, f)
                        arc = os.path.relpath(fp, self.base)
                        z.write(fp, arc)
                        n += 1
            QMessageBox.information(self, "导出成功",
                                    "已备份 %d 个文件到：\n%s" % (n, out))
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def import_data(self):
        try:
            fn, _ = QFileDialog.getOpenFileName(self, "选择数据备份 zip", "", "Zip (*.zip)")
            if not fn:
                return
            r = QMessageBox.question(self, "确认恢复",
                                     "将覆盖当前 data/ 目录，继续？",
                                     QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
            with zipfile.ZipFile(fn) as z:
                z.extractall(self.base)
            QMessageBox.information(self, "完成", "数据已恢复，建议重启程序。")
        except Exception as e:
            QMessageBox.warning(self, "恢复失败", str(e))
