# -*- coding: utf-8 -*-
"""系统混入：状态栏刷新、数据导出导入"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
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
        """从日志中心「📂 导入数据」恢复迁移包。

        以前直接把 zip 里的成员解到 ``self.base``（**程序根目录**）：照包里写的
        路径落盘，一个 ``../core/evil.py`` 就能覆盖程序文件（zip slip），
        而提示文案只说了"覆盖 data/"。现在统一走
        ``core.migration.Migration``：先读包算清单，会覆盖才问，逐成员
        ``safe_join``，越界成员单独报「拒绝」——同一个功能只留一份安全实现。
        """
        try:
            fn, _ = QFileDialog.getOpenFileName(
                self, "选择数据备份 zip", "", "Zip (*.zip)")
            if not fn:
                return
            from core.migration import Migration
            mg = Migration(getattr(self, "trunk", None) or self)

            r = mg.import_zip(fn)
            if r.get("需要确认"):
                top = "、".join(str(x) for x in (r.get("将覆盖") or [])[:10])
                q = QMessageBox.question(
                    self, "确认覆盖",
                    "这个包会盖掉当前这些文件：\n%s\n\n继续导入？" % top,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if q != QMessageBox.Yes:
                    return
                r = mg.import_zip(fn, overwrite=True)

            if not r.get("ok"):
                QMessageBox.warning(
                    self, "恢复失败",
                    str(r.get("error") or r.get("说明")
                        or "包里没有可导入的文件")[:300])
                return

            lines = ["已恢复 %d 个文件。" % int(r.get("解压") or 0)]
            if r.get("拒绝"):
                lines.append("安全拦截 %d 个越界路径（未写入）：%s" % (
                    len(r["拒绝"]), "、".join(map(str, r["拒绝"][:5]))))
            if r.get("写入失败"):
                lines.append("有 %d 个文件没写进去：%s" % (
                    len(r["写入失败"]), "、".join(map(str, r["写入失败"][:5]))))
            lines.append("建议重启程序。")
            QMessageBox.information(self, "完成", "\n".join(lines))
        except Exception as e:
            QMessageBox.warning(self, "恢复失败", str(e)[:300])
