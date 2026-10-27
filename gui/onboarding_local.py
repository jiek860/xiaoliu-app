# -*- coding: utf-8 -*-
"""首次设置：本地模型检测、拉取和刷新。"""
from __future__ import annotations

import os
import time
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtWidgets import QMessageBox

import threading
from core import model_setup, ollama_installer
from gui.onboarding_utils import _model_text, _set_model_text

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class OnboardingLocalMixin:
    def _refresh_local_status(self, async_=True):
        """检测本地 Ollama 并把结果显示到状态标签

        默认**异步**：原来是在 initializePage 里同步发请求（timeout=3），
        向导窗口要等这次探测完才显示出来 —— Ollama 不在线时就是先卡 3 秒。
        """
        url = self.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA
        if not async_:
            self._apply_local_status(model_setup.probe_ollama(url, timeout=3), url)
            return
        self.lbl_local_status.setText("⏳ 正在检测 %s …" % url)
        self.lbl_local_status.setStyleSheet("color:#64748b;")

        def _work():
            try:
                info = model_setup.probe_ollama(url, timeout=3)
            except Exception:
                info = {"reachable": False, "models": []}
            try:
                self.probe_done.emit(info, url)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass

        threading.Thread(target=_work, daemon=True,
                         name="onboarding-probe").start()

    def _apply_local_status(self, info, url):
        # 检测到的模型自动刷进下拉框 —— 用户点一下就能选，不用照着文档手打。
        # （手打模型名打错一个字符，表现就是"发了消息没反应"，很难自己查出来。）
        if info.get("reachable"):
            models = [m for m in (info.get("models") or []) if m]
            cur = _model_text(self.ed_local_model)
            if models:
                self.ed_local_model.blockSignals(True)
                self.ed_local_model.clear()
                self.ed_local_model.addItems(models)
                # 优先保留用户/配置里已经选好的那个
                if cur and cur in models:
                    self.ed_local_model.setCurrentText(cur)
                elif model_setup.RECOMMENDED_LOCAL_MODEL in models:
                    self.ed_local_model.setCurrentText(
                        model_setup.RECOMMENDED_LOCAL_MODEL)
                else:
                    # 没指定就用第一个可用的 —— 比让用户自己猜强
                    self.ed_local_model.setCurrentIndex(0)
                self.ed_local_model.blockSignals(False)

        if info["reachable"]:
            n = len(info["models"])
            if n:
                self.lbl_local_status.setText(
                    "✅ 连上了，已装 %d 个模型：%s"
                    % (n, "、".join(info["models"][:5])))
                self.lbl_local_status.setStyleSheet("color:#16a34a;")
                self.lbl_local_howto.setText(
                    "下面「模型」一栏已经自动列出上面这些，选一个就行 → "
                    "然后点「保存并检测」。")
                self.lbl_local_howto.setStyleSheet("color:#16a34a;")
            else:
                self.lbl_local_status.setText(
                    "⚠️ Ollama 在跑，但还没有任何模型。")
                self.lbl_local_status.setStyleSheet("color:#d97706;")
                self.lbl_local_howto.setText(self._download_steps())
                self.lbl_local_howto.setStyleSheet("color:#475569;")
        else:
            self.lbl_local_status.setText("❌ 连不上 %s" % url)
            self.lbl_local_status.setStyleSheet("color:#dc2626;")
            self.lbl_local_howto.setText(self._download_steps())
            self.lbl_local_howto.setStyleSheet("color:#475569;")

        # 说明文字从一句变成四步、或者反过来，页面高度会变 —— 重算一次，
        # 不然新加的那几行会被窗口裁掉。
        #
        # ⚠️ 必须先让布局算完再量：刚 setText 完就调 fit_to_content 的话，
        #    QLabel 的 sizeHint 还是**旧文字**的尺寸，算出来的窗口高度不够，
        #    四步说明照样被切（实测：宽 580 时那段文字需要 280px，只给了 80px）。
        #    activate() 强制立刻重排；再补一个 0 延时的兜底，
        #    因为有些平台下 activate() 之后还要等一轮事件循环才准。
        try:
            self.currentPage().layout().activate()
        # 静默是故意的：强制重排只是为了让下面的尺寸量得准 ——
        # 它失败顶多量得偏小、退回上一步的尺寸，不该因此拦住用户配模型
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")
        self.fit_to_content(grow=True)
        # 再排一次延时重算：activate() 之后页面 sizeHint 有时还没跟上
        # （Qt 要等一轮事件循环）。用挂在 self 上的定时器，见 __init__ 里的说明。
        try:
            self._fit_timer.start(0)
        # 静默是故意的：这只是"再排一次重算"，起不来也不影响
        # 本次已经算好的尺寸
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _download_steps(self):
        """没装/没模型时给**能照着做**的步骤

        对比同类程序后两步都改成程序内一键完成了：
        装 Ollama 不用自己开浏览器找，下模型不用自己开命令行跑
        `ollama run xxx`（要会开 cmd、会粘命令、看着黑窗口、
        还得自己判断什么时候算下完）。
        """
        return (
            "按这个顺序来：<br>"
            "&nbsp;&nbsp;<b>1.</b> 点上面的 <b>⬇️ 一键下载 Ollama 安装包</b>"
            "（约 %d MB，自动走国内加速源）<br>"
            "&nbsp;&nbsp;<b>2.</b> 下完点 <b>📦 立即安装</b>，"
            "按弹出的安装向导点完（装到哪可以自己选）<br>"
            "&nbsp;&nbsp;<b>3.</b> 装完 Ollama 会自己在后台运行"
            "（右下角托盘有个小羊驼图标）<br>"
            "&nbsp;&nbsp;<b>4.</b> 回到这里点 <b>🔄 重新检测</b>，"
            "连上以后点 <b>⬇️ 下载模型</b>（模型约 2GB，带进度条，可以取消）<br>"
            "&nbsp;&nbsp;<b>5.</b> 下完模型会自动出现在下拉框里，"
            "选中它，再点「💾 保存并检测」<br><br>"
            "下载不动的备选：去 <a href='%s'>%s</a> 用浏览器手动下安装包。"
            % (ollama_installer.APPROX_MB, model_setup.OLLAMA_DOWNLOAD,
               model_setup.OLLAMA_DOWNLOAD))

    def _start_pull(self):
        """从 Ollama 拉「模型」框里那个模型"""
        if getattr(self, "_dl_busy", False):
            return
        model = _model_text(self.ed_local_model) or \
            model_setup.RECOMMENDED_LOCAL_MODEL
        url = self.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA

        self._dl_busy = True
        self._dl_stop = False
        self._dl_kind = "model"
        self.btn_dl.setEnabled(False)
        self.btn_cancel_dl.setVisible(True)
        self.bar_dl.setVisible(True)
        self.bar_dl.setValue(0)
        self.lbl_dl.setVisible(True)
        self.lbl_dl.setText("正在从 Ollama 拉取「%s」…（约 2GB）" % model)
        self.lbl_dl.setStyleSheet("color:#475569;")

        def _work():
            try:
                r = ollama_installer.pull_model(
                    url, model,
                    progress=lambda st, g, t, pct, sp:
                        self.pull_prog.emit(st, g, t, pct, sp),
                    should_stop=lambda: self._dl_stop)
                r["模型"] = r.get("模型") or model
                self.pull_done.emit(r)
            except Exception as e:
                self.pull_done.emit({"ok": False,
                                     "错误": "%s: %s" % (type(e).__name__,
                                                         str(e)[:80])})

        threading.Thread(target=_work, daemon=True,
                         name="onboarding-pull").start()

    def _on_pull_progress(self, status, got, total, pct, sp):
        self.bar_dl.setValue(pct)
        if total:
            self.lbl_dl.setText(
                "%s　已下 %.0f / %.0f MB　%.1f MB/s"
                % (status, got, total, sp))
        else:
            self.lbl_dl.setText(status)

    def _on_pull_done(self, r):
        self._dl_busy = False
        self.btn_dl.setEnabled(True)
        self.btn_cancel_dl.setVisible(False)
        if r.get("ok"):
            self.bar_dl.setValue(100)
            self.lbl_dl.setText(
                "✅ 模型「%s」下载完成（%.0f MB，用了 %.0f 秒）—— "
                "点「🔄 重新检测」刷新列表"
                % (r.get("模型", ""), r.get("MB", 0), r.get("耗时秒", 0)))
            self.lbl_dl.setStyleSheet("color:#16a34a;")
            # 下完自动刷一次列表，用户不用再点
            self._refresh_local_status()
        elif r.get("取消"):
            self.bar_dl.setVisible(False)
            self.lbl_dl.setText(
                "已取消。已经下好的部分**不会白费** —— Ollama 留着缓存，"
                "下次拉同一个模型会接着用。")
            self.lbl_dl.setStyleSheet("color:#64748b;")
        else:
            self.bar_dl.setVisible(False)
            self.lbl_dl.setText(
                "❌ 下载失败：%s\n（Ollama 没启动的话先把它打开，"
                "再点「🔄 重新检测」）" % r.get("错误", "")[:90])
            self.lbl_dl.setStyleSheet("color:#dc2626;")

    def _recheck(self):
        self._refresh_local_status()
