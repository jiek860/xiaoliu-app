# -*- coding: utf-8 -*-
"""更新对话框 - 检查更新 / 回滚 / 历史

这一轮修掉的三件事
------------------
1. 「检查更新」在 GUI 线程里同步拉远端清单 —— 网络慢时窗口直接假死，
   用户以为更新功能坏了。现在走 UpdateCheckThread，结果用信号回主线程。
2. 更新历史只记版本号，**不记备份目录** —— 界面写着"回滚"，实际无从下手。
   现在历史里记 backup，选中一条就能回滚到那次更新之前。
3. 回滚本身原来是"删掉 core/modules 再整目录拷回" —— 更新后新装的插件、
   用户改过的文件会一起消失。改成了逐文件覆盖（见 core/auto_update.rollback）。
"""
import os
import json

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

from gui.feedback_states import make_action_links
from gui.workers import _log_path, _reg_finish, _reg_start


class UpdateCheckThread(QThread):
    """后台拉取更新清单并验签（网络请求不能放在 GUI 线程）"""
    done = pyqtSignal(dict)

    def __init__(self, updater, url, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.url = url

    def run(self):
        try:
            r = self.updater.check_update(self.url)
        except Exception as e:
            r = {"ok": False, "error": str(e)[:120]}
        if not isinstance(r, dict):
            r = {"ok": False, "error": "更新模块返回格式不对"}
        self.done.emit(r)


class RollbackThread(QThread):
    """后台回滚（备份里有上千个文件，不能在 GUI 线程里拷）"""
    done = pyqtSignal(bool)

    def __init__(self, updater, backup, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.backup = backup

    def run(self):
        try:
            ok = bool(self.updater.rollback(self.backup))
        except Exception as e:
            _x6_swallowed(__name__, e, "update rollback")
            ok = False
        self.done.emit(ok)


class UpdateThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)

    def __init__(self, updater, manifest, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.manifest = manifest

    def run(self):
        ver = str((self.manifest or {}).get("version", ""))
        rid = _reg_start("update_install",
                         "下载并安装更新 v%s" % (ver or "?"),
                         _log_path(getattr(self.updater, "trunk", None)))

        def cb(cur, total, name):
            self.progress.emit(cur, total, name)
        try:
            # 已在对话框确认过，不再重复弹窗
            r = self.updater.download_and_install(self.manifest,
                                                  progress_cb=cb, confirm=False)
        except Exception as e:
            r = {"ok": False, "错误": str(e)[:120]}
            _reg_finish(rid, "failed", str(e)[:200])
        else:
            _reg_finish(rid, "completed" if r.get("ok") else "failed",
                        str(r.get("错误", ""))[:200])
        self.finished.emit(r)


class UpdateDialog(QDialog):
    """更新管理对话框"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self._manifest = None
        self._entries = []
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
        layout.addWidget(QLabel("更新历史（选中一条可回滚到那次更新之前）:"))
        self.history_list = QListWidget()
        self.history_list.setStyleSheet("font-size:12px;")
        layout.addWidget(self.history_list, stretch=1)
        self.rollback_link = make_action_links([
            ("↩ 回滚到选中记录之前", lambda: self._rollback_selected()),
        ])
        layout.addWidget(self.rollback_link)

    def _load_history(self):
        """加载更新历史（同时记住每条记录的备份目录）"""
        history_path = os.path.join(self.trunk.base, "updates", "update_history.jsonl")
        self._entries = []
        self.history_list.clear()
        if not os.path.exists(history_path):
            return
        try:
            lines = open(history_path, encoding="utf-8").readlines()
        except Exception as e:
            _x6_swallowed(__name__, e, "read update history")
            return
        for line in reversed(lines[-20:]):
            try:
                h = json.loads(line.strip())
            except Exception as e:
                _x6_swallowed(__name__, e, "parse update history line")
                continue
            self._entries.append(h)
            bk = str(h.get("backup") or "")
            can_rb = bool(bk and os.path.isdir(bk))
            item = QListWidgetItem(
                "%s  %s → %s  (%d个文件)  %s" % (
                    h.get("time", ""), h.get("from", ""), h.get("to", ""),
                    h.get("files", 0),
                    "可回滚" if can_rb else ("备份已清理" if bk else "无备份记录")
                )
            )
            self.history_list.addItem(item)

    def _get_updater(self):
        """按微核约定取更新模块实例（星型拓扑，不直接 import 模块文件）"""
        try:
            return self.trunk._load_lazy("auto_updater")
        except Exception:
            return None

    def _check_update(self):
        """检查更新（远端清单必须验签通过）"""
        rid = _reg_start("update_check", "检查更新",
                         _log_path(getattr(self, "trunk", None)))
        self.log_browser.setPlainText("正在检查更新...")
        self.btn_update.setVisible(False)
        self.btn_check.setEnabled(False)
        self._manifest = None
        updater = self._get_updater()
        if updater is None:
            self.btn_check.setEnabled(True)
            _reg_finish(rid, "failed", "更新模块未登记或加载失败")
            self.log_browser.setPlainText(
                "检查更新失败: 更新模块未登记或加载失败（core/lazy_config.py 的 auto_updater）")
            return
        # 不再内置任何第三方更新源；升级源必须由用户或部署方显式配置。
        url = str(self.trunk.config.get("update_manifest_url", "") or "").strip()
        if not url:
            self.btn_check.setEnabled(True)
            _reg_finish(rid, "failed", "未配置 update_manifest_url")
            self.log_browser.setPlainText(
                "检查更新失败: 未配置 update_manifest_url。\n"
                "为避免从第三方仓库自动下载代码，本版本不再内置更新源。")
            return
        self._check_rid = rid
        self._check_thread = UpdateCheckThread(updater, url, parent=self)
        self._check_thread.done.connect(self._on_check_done)
        self._check_thread.start()

    def _on_check_done(self, r):
        """检查结果回主线程后再动界面"""
        rid = getattr(self, "_check_rid", "")
        self.btn_check.setEnabled(True)
        if not r.get("ok"):
            _reg_finish(rid, "failed", str(r.get("error", "未知错误"))[:200])
            self.log_browser.setPlainText("检查更新失败:\n" + str(r.get("error", "未知错误")))
            return
        if not r.get("has_update"):
            _reg_finish(rid, "completed")
            self.log_browser.setPlainText(
                "✅ 已是最新版本\n当前版本: v%s%s" % (
                    r.get("current", "?"),
                    "" if r.get("verified") else "\n（提示：清单未签名）"))
            return
        _reg_finish(rid, "completed")
        text = ("发现新版本: v%s\n当前版本: v%s\n"
                "签名校验: %s\n\n更新日志:\n%s") % (
            r.get("latest", ""), r.get("current", ""),
            "通过" if r.get("verified") else "未通过（按配置放行）",
            r.get("changelog", "") or "（无）")
        self.log_browser.setPlainText(text)
        self._manifest = r.get("manifest")
        # 验签没通过的包不给「立即更新」按钮
        self.btn_update.setVisible(bool(r.get("verified")))

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
                "✅ 更新完成：%d 个文件\n备份目录: %s\n\n请重启程序以完全生效。\n"
                "如果新版本有问题，在下方「更新历史」选中这一条，点「回滚」。"
                % (r.get("更新数", 0), r.get("备份", "")))
            self.btn_update.setVisible(False)
            self._load_history()
        else:
            self.log_browser.setPlainText(
                "❌ 更新失败: %s\n\n没有改动生效（替换失败会自动还原已替换的文件）。"
                % str(r.get("错误", "未知")))

    def _rollback_selected(self):
        """回滚到选中那条更新之前的备份"""
        row = self.history_list.currentRow()
        if row < 0 or row >= len(self._entries):
            QMessageBox.information(
                self, "回滚", "先在「更新历史」里选中一条记录，再点回滚")
            return
        entry = self._entries[row]
        backup = str(entry.get("backup") or "")
        if not backup:
            QMessageBox.information(
                self, "回滚",
                "这条记录没有备份目录（旧版本只记了版本号），没法自动回滚。\n"
                "需要手动回滚的话，到 backups/ 目录里找对应时间的备份。")
            return
        if not os.path.isdir(backup):
            QMessageBox.information(
                self, "回滚", "备份目录已经不在了：\n%s\n（只保留最近 5 次更新）" % backup)
            return
        if QMessageBox.question(
                self, "确认回滚",
                "将把 core/ 与 modules/ 恢复到 %s 那次更新之前：\n%s\n\n"
                "回滚不会删除更新之后新装的文件，但同名文件会被覆盖。\n"
                "回滚完请重启程序。确定继续？"
                % (entry.get("time", ""), backup),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        updater = self._get_updater()
        if updater is None:
            QMessageBox.warning(self, "回滚失败", "更新模块未加载")
            return
        self.btn_check.setEnabled(False)
        self.btn_update.setEnabled(False)
        self.log_browser.setPlainText("正在回滚...")
        self._rollback_thread = RollbackThread(updater, backup, parent=self)
        self._rollback_thread.done.connect(self._on_rollback_done)
        self._rollback_thread.start()

    def _on_rollback_done(self, ok):
        self.btn_check.setEnabled(True)
        self.btn_update.setEnabled(True)
        if ok:
            self.log_browser.setPlainText(
                "✅ 已回滚到所选更新之前。\n请重启程序让旧代码生效。")
        else:
            self.log_browser.setPlainText(
                "❌ 回滚失败：备份目录读不了或拷贝出错。\n"
                "详情见 data/logs/app.log，必要时用 backups/ 目录里的备份手动还原。")
        self._load_history()

    def run(self):
        return {"状态": "更新对话框已打开"}
