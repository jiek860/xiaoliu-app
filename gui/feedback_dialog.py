# -*- coding: utf-8 -*-
"""反馈对话框 - 右上角反馈按钮

发送通道走 core/notifier（飞书 / 企业微信 / 钉钉 群机器人），不再用邮箱。

为什么不再用 SMTP
-----------------
邮箱授权码 = 邮箱控制权（能发也能收）。打进程序发给别人，等于把邮箱
交出去 -- Nuitka / 加固都挡不住，因为程序运行时必须把明文交给
smtplib.login()，断点或内存 dump 就能拿到。
群机器人 webhook 只是个"公开地址"，泄露了删掉机器人重建即可。

自动附带日志（后台完成，界面不增加任何控件）
--------------------------------------------
点「提交」后，后台线程会自动：
  1. 收集**系统信息 + 最近错误行 + 崩溃现场**（core/log_digest）
  2. 脱敏、截断
  3. 和你写的内容一起发出去
界面保持原样  没有开关、没有额外按钮。

注意：网络请求 / 读日志一律丢到 QThread，绝不在 UI 线程上做同步 IO
（check_threads / ui_responsiveness 两条守卫都盯着这个）。
"""
import os
import time

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextEdit, QMessageBox)

from core import log_digest
from core.notifier import Notifier

MAX_CHARS = 500             # 反馈正文上限
MAX_MESSAGE_CHARS = 4500    # 整条消息上限（飞书单条消息有长度限制）
MIN_INTERVAL = 60           # 同一台机器 60 秒内只发一次


class _SendWorker(QThread):
    """后台发反馈：自动附带日志摘要。线程里绝不碰任何 Qt 控件。"""
    ok = pyqtSignal()
    fail = pyqtSignal(str)

    def __init__(self, config, text, base="", parent=None):
        super().__init__(parent)
        self.config = config
        self.text = text
        self.base = base
        self.sent_chars = 0

    def _compose(self):
        msg = self.text
        if self.base:
            msg = msg + "\n\n" + log_digest.collect(self.base)["text"]
        if len(msg) > MAX_MESSAGE_CHARS:
            msg = msg[:MAX_MESSAGE_CHARS] + "\n（已截断）"
        return msg

    def run(self):
        try:
            msg = self._compose()
        except Exception as e:
            # 日志收集失败不能拦住反馈本身：退回只发正文，并说明原因
            msg = self.text + "\n\n（日志摘要收集失败：%s）" % str(e)[:80]
        self.sent_chars = len(msg)
        try:
            ok, err = Notifier(self.config).send(msg)
        except Exception as e:
            ok, err = False, "%s: %s" % (type(e).__name__, str(e)[:80])
        if ok:
            self.ok.emit()
        else:
            self.fail.emit(err or "未知错误")


class FeedbackDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self._worker = None
        self.setWindowTitle("意见反馈")
        self.setFixedSize(460, 340)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("\U0001F4AC 意见反馈")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        layout.addWidget(QLabel("遇到什么问题？有什么建议？"))
        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText(
            "请输入反馈内容（最多 %d 字）..." % MAX_CHARS)
        layout.addWidget(self.content_edit)

        self.tip = QLabel("")
        self.tip.setStyleSheet("color:#888;font-size:11px;")
        layout.addWidget(self.tip)

        btn_row = QHBoxLayout()
        self.submit_btn = QPushButton("提交")
        self.submit_btn.setStyleSheet(
            "background-color: #2196f3; color: white; border: none; "
            "padding: 8px 20px; border-radius: 6px;")
        self.submit_btn.clicked.connect(self._submit)
        btn_row.addWidget(self.submit_btn)
        btn_row.addStretch(1)
        hint = QLabel("Esc 取消")
        hint.setStyleSheet("color:#888;font-size:11px;")
        btn_row.addWidget(hint)
        layout.addLayout(btn_row)

    # ---------- 本地限流（防连点 / 误触） ----------
    def _rate_path(self):
        base = getattr(self.trunk, "base", "") or ""
        return os.path.join(base, "data", ".feedback_last")

    def _rate_left(self):
        """还要等几秒；0 = 可以发"""
        try:
            last = float(open(self._rate_path(), encoding="utf-8").read().strip() or 0)
        except Exception:
            return 0
        return max(0, int(MIN_INTERVAL - (time.time() - last)))

    def _rate_mark(self):
        p = self._rate_path()
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
            return True
        except Exception:
            # 限流文件写不下来就别拦用户（这是体验优化，不是功能）
            return True

    def _rate_clear(self):
        try:
            os.remove(self._rate_path())
            return True
        except Exception:
            # 本来就不存在（或没权限），当作清掉
            return True

    # ---------- 提交 ----------
    def _submit(self):
        content = self.content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "提示", "请输入反馈内容")
            return
        if len(content) > MAX_CHARS:
            QMessageBox.warning(self, "提示",
                                "反馈太长啦，最多 %d 字（现在 %d 字）"
                                % (MAX_CHARS, len(content)))
            return
        left = self._rate_left()
        if left > 0:
            QMessageBox.warning(self, "提示", "刚发过了，请 %d 秒后再试" % left)
            return

        cfg = getattr(self.trunk, "config", {}) or {}
        if not Notifier(cfg).channel():
            QMessageBox.warning(self, "提示", "反馈通道未配置，请联系开发者")
            return

        self._rate_mark()
        self.submit_btn.setEnabled(False)
        self.tip.setText("发送中...")
        base = getattr(self.trunk, "base", "") or ""
        self._worker = _SendWorker(cfg, self._format(content), base, self)
        self._worker.ok.connect(self._on_ok)
        self._worker.fail.connect(self._on_fail)
        self._worker.start()

    def _format(self, content):
        try:
            from core.version import __version__
        except Exception:
            __version__ = "?"
        name = (getattr(self.trunk, "config", {}) or {}).get("ai_name", "小6")
        return ("【%s 反馈】\n%s\n\n版本: %s\n时间: %s"
                % (name, content, __version__,
                   time.strftime("%Y-%m-%d %H:%M:%S")))

    def _on_ok(self):
        self.submit_btn.setEnabled(True)
        QMessageBox.information(self, "成功", "感谢反馈！")
        self.close()

    def _on_fail(self, err):
        self.submit_btn.setEnabled(True)
        self.tip.setText("")
        self._rate_clear()          # 没发出去就允许立刻重试
        QMessageBox.critical(self, "错误", "发送失败: " + str(err)[:120])
