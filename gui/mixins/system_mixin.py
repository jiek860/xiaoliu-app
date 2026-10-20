# -*- coding: utf-8 -*-
"""系统混入：状态栏刷新、数据导出导入"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
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
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    # export_logs() / export_data() 已删除 —— 它们是**重复实现**：
    # 同一件事能力注册表里各有一份，而且那份更完整：
    #     crash_export   打包日志+配置+系统信息，密钥自动脱敏
    #     migrate_export 把整份数据打包，换电脑时用
    # 这两份本地实现原来只被「日志中心」的两个按钮用，按钮撤掉后就没有调用者了。
    # 留着只会让同一件事有两个真相（改了一份忘另一份）。

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
