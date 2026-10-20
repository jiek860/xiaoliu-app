# -*- coding: utf-8 -*-
"""更新对话框 - 检查更新/回滚/历史"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QTextBrowser,
)
from PyQt5.QtCore import QThread, pyqtSignal
import os
import json
import time


class UpdateThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)

    def __init__(self, updater, manifest, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.manifest = manifest

    def run(self):
        def cb(cur, total, name):
            self.progress.emit(cur, total, name)
        try:
            # 已在对话框确认过，不再重复弹窗
            r = self.updater.download_and_install(self.manifest,
                                                  progress_cb=cb, confirm=False)
        except Exception as e:
            r = {"ok": False, "错误": str(e)[:120]}
        self.finished.emit(r)


class UpdateDialog(QDialog):
    """更新管理对话框"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self._manifest = None
        self.setWindowTitle("小6智能体 · 软件更新")
        self.setMinimumSize(640, 520)
        self._build_ui()
        self._load_history()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("软件更新")
        title.setStyleSheet("font-size:18px;font-weight:bold;padding:6px;")
        layout.addWidget(title)

        # 当前版本
        try:
            from core.version import __version__
            ver = __version__.lstrip("vV")
        except Exception:
            ver = "未知"
        self.lbl_ver = QLabel("当前版本: v" + ver)
        self.lbl_ver.setStyleSheet("color:#475569;padding:4px;")
        layout.addWidget(self.lbl_ver)

        # 检查更新按钮
        btn_row = QHBoxLayout()
        self.btn_check = QPushButton("检查更新")
        self.btn_check.setStyleSheet(
            "padding:8px 20px;background:#4a9eff;color:white;"
            "border:none;border-radius:6px;font-size:13px;"
        )
        self.btn_check.clicked.connect(self._check_update)
        btn_row.addWidget(self.btn_check)

        # 有可用且已验签的更新时才显示
        self.btn_update = QPushButton("立即更新")
        self.btn_update.setStyleSheet(
            "padding:8px 20px;background:#16a34a;color:white;"
            "border:none;border-radius:6px;font-size:13px;"
        )
        self.btn_update.clicked.connect(self._start_update)
        self.btn_update.setVisible(False)
        btn_row.addWidget(self.btn_update)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # 更新日志
        self.log_browser = QTextBrowser()
        self.log_browser.setReadOnly(True)
        self.log_browser.setStyleSheet(
            "font-family:'Microsoft YaHei UI';font-size:13px;"
            "background:#fafafa;border:1px solid #e5e6eb;min-height:150px;"
        )
        self.log_browser.setPlainText("点击「检查更新」查看新版本")
        layout.addWidget(self.log_browser, stretch=2)

        # 更新历史
        layout.addWidget(QLabel("更新历史:"))
        self.history_list = QListWidget()
        self.history_list.setStyleSheet("font-size:12px;")
        layout.addWidget(self.history_list, stretch=1)

    def _load_history(self):
        """加载更新历史"""
        history_path = os.path.join(self.trunk.base, "updates", "update_history.jsonl")
        if not os.path.exists(history_path):
            return
        try:
            lines = open(history_path, encoding="utf-8").readlines()
            for line in reversed(lines[-20:]):
                try:
                    h = json.loads(line.strip())
                    item = QListWidgetItem(
                        "%s  %s → %s  (%d个文件)" % (
                            h.get("time", ""), h.get("from", ""),
                            h.get("to", ""), h.get("files", 0)
                        )
                    )
                    self.history_list.addItem(item)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def _get_updater(self):
        """按微核约定取更新模块实例（星型拓扑，不直接 import 模块文件）"""
        try:
            return self.trunk._load_lazy("auto_updater")
        except Exception:
            return None

    def _check_update(self):
        """检查更新（远端清单必须验签通过）"""
        self.log_browser.setPlainText("正在检查更新...")
        self.btn_update.setVisible(False)
        self._manifest = None
        updater = self._get_updater()
        if updater is None:
            self.log_browser.setPlainText(
                "检查更新失败: 更新模块未登记或加载失败（core/lazy_config.py 的 auto_updater）")
            return
        try:
            # 不再内置任何第三方更新源；升级源必须由用户或部署方显式配置。
            url = str(self.trunk.config.get("update_manifest_url", "") or "").strip()
            if not url:
                self.log_browser.setPlainText(
                    "检查更新失败: 未配置 update_manifest_url。\n"
                    "为避免从第三方仓库自动下载代码，本版本不再内置更新源。")
                return
            r = updater.check_update(url)
            if not r.get("ok"):
                self.log_browser.setPlainText("检查更新失败:\n" + r.get("error", "未知错误"))
                return
            if not r.get("has_update"):
                self.log_browser.setPlainText(
                    "✅ 已是最新版本\n当前版本: v%s%s" % (
                        r.get("current", "?"),
                        "" if r.get("verified") else "\n（提示：清单未签名）"))
                return
            text = ("发现新版本: v%s\n当前版本: v%s\n"
                    "签名校验: %s\n\n更新日志:\n%s") % (
                r.get("latest", ""), r.get("current", ""),
                "通过" if r.get("verified") else "未通过（按配置放行）",
                r.get("changelog", "") or "（无）")
            self.log_browser.setPlainText(text)
            self._manifest = r.get("manifest")
            # 验签没通过的包不给「立即更新」按钮
            self.btn_update.setVisible(bool(r.get("verified")))
        except Exception as e:
            self.log_browser.setPlainText("检查更新失败: " + str(e)[:100])

    def _start_update(self):
        """下载并安装更新（仅对已验签的更新包开放）"""
        if not self._manifest:
            return
        ver = self._manifest.get("version", "?")
        ret = QMessageBox.question(
            self, "确认更新",
            "将更新到 v%s，更新过程中请勿关闭程序。\n是否继续？" % ver,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        updater = self._get_updater()
        if updater is None:
            QMessageBox.warning(self, "更新失败", "更新模块未加载")
            return
        self.btn_check.setEnabled(False)
        self.btn_update.setEnabled(False)
        self.log_browser.setPlainText("正在下载更新包...")
        self._thread = UpdateThread(updater, self._manifest, parent=self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_update_done)
        self._thread.start()

    def _on_progress(self, cur, total, name):
        self.log_browser.setPlainText("下载中 %d/%d\n%s" % (cur, total, name))

    def _on_update_done(self, r):
        self.btn_check.setEnabled(True)
        self.btn_update.setEnabled(True)
        if r.get("ok"):
            self.log_browser.setPlainText(
                "✅ 更新完成：%d 个文件\n备份目录: %s\n\n请重启程序以完全生效。"
                % (r.get("更新数", 0), r.get("备份", "")))
            self.btn_update.setVisible(False)
            self._load_history()
        else:
            self.log_browser.setPlainText("❌ 更新失败: " + str(r.get("错误", "未知")))

    def run(self):
        return {"状态": "更新对话框已打开"}
