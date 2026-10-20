# -*- coding: utf-8 -*-
"""首次设置：Ollama 下载、安装、进度和取消。"""
from __future__ import annotations

import os
import subprocess
import time
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtWidgets import QMessageBox

import threading
from core import ollama_installer

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class OnboardingInstallMixin:
    def _on_dl_button(self):
        """同一个按钮按状态换动作：还没下完 -> 下载；下好了 -> 安装"""
        if getattr(self, "_dl_ready_path", None):
            self._run_installer()
        else:
            self._start_download()

    def _start_download(self):
        """起线程下载，进度通过信号回主线程（Qt 控件只能在主线程碰）"""
        if getattr(self, "_dl_busy", False):
            return
        self._dl_busy = True
        self._dl_stop = False
        self._dl_ready_path = None
        self.btn_dl.setEnabled(False)
        self.btn_cancel_dl.setVisible(True)
        self.bar_dl.setVisible(True)
        self.bar_dl.setValue(0)
        self.lbl_dl.setVisible(True)
        self.lbl_dl.setText("正在挑下载源…")
        self.lbl_dl.setStyleSheet("color:#475569;")

        def _work():
            try:
                best = ollama_installer.pick_best(
                    progress=lambda m: self.dl_msg.emit(m))
                if not best:
                    self.dl_done.emit({"ok": False,
                                       "错误": "所有下载源都连不上（可能是断网）"})
                    return
                self.dl_msg.emit("用「%s」下载中 —— 实测 %s"
                                 % (best["名字"], best.get("实测", "")))

                def prog(got, total, sp, eta):
                    self.dl_prog.emit(got, total or 0, sp, eta)

                r = ollama_installer.download(
                    best["url"], progress=prog,
                    should_stop=lambda: self._dl_stop)
                r["源"] = best["名字"]
                self.dl_done.emit(r)
            except Exception as e:
                self.dl_done.emit({"ok": False,
                                   "错误": "%s: %s" % (type(e).__name__,
                                                       str(e)[:80])})

        threading.Thread(target=_work, daemon=True,
                         name="onboarding-download").start()

    def _cancel_download(self):
        """取消当前正在进行的下载（安装包 或 模型，两种共用这个按钮）"""
        self._dl_stop = True
        self.lbl_dl.setText("正在取消…")

    def _on_dl_progress(self, got, total, sp, eta):
        if total:
            self.bar_dl.setValue(int(got * 100 / total))
            self.lbl_dl.setText(
                "已下 %.0f / %.0f MB　%.1f MB/s　剩余约 %d 秒"
                % (got / 1048576, total / 1048576, sp, int(eta)))
        else:
            self.lbl_dl.setText("已下 %.0f MB　%.1f MB/s"
                                % (got / 1048576, sp))

    def _on_dl_done(self, r):
        self._dl_busy = False
        self.btn_dl.setEnabled(True)
        self.btn_cancel_dl.setVisible(False)
        if r.get("ok"):
            self._dl_ready_path = r.get("路径") or ollama_installer.default_path()
            self.bar_dl.setValue(100)
            self.lbl_dl.setText(
                "✅ 下载完成：%.0f MB（%s，用了 %.0f 秒）—— 点下面的按钮安装"
                % (r.get("MB", 0), r.get("源", ""), r.get("耗时秒", 0)))
            self.lbl_dl.setStyleSheet("color:#16a34a;")
            self.btn_dl.setText("📦 立即安装")
        elif r.get("取消"):
            self.bar_dl.setVisible(False)
            self.lbl_dl.setText("已取消下载（没留下半个文件）")
            self.lbl_dl.setStyleSheet("color:#64748b;")
        else:
            self.bar_dl.setVisible(False)
            self.lbl_dl.setText(
                "❌ 下载失败：%s\n可以点上面的下载链接用浏览器手动下，"
                "或稍后重试。" % r.get("错误", "")[:90])
            self.lbl_dl.setStyleSheet("color:#dc2626;")

    def _run_installer(self):
        r = ollama_installer.run_installer(
            getattr(self, "_dl_ready_path", None))
        if r.get("ok"):
            self.lbl_dl.setText("📦 %s" % r["提示"])
            self.lbl_dl.setStyleSheet("color:#16a34a;")
            self._dl_ready_path = None
            self.btn_dl.setText("⬇️ 重新下载安装包")
        else:
            self.lbl_dl.setText("❌ %s" % r.get("错误", ""))
            self.lbl_dl.setStyleSheet("color:#dc2626;")
