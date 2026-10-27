# -*- coding: utf-8 -*-
"""首次设置：provider 预填、切换和页面尺寸。"""
from __future__ import annotations

import threading

from PyQt5.QtWidgets import QMessageBox

from core import model_setup
from gui.onboarding_utils import _set_model_text, _model_text

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class OnboardingProviderMixin:
    def _prefill(self):
        cfg = self.trunk.config or {}
        self.ed_ollama.setText(str(cfg.get("ollama_url", "") or ""))
        _set_model_text(self.ed_local_model,
                        str(cfg.get("local_model", "") or ""))
        cloud_url = str(cfg.get("cloud_url", "") or "")
        self.ed_cloud_url.setText(cloud_url)
        self.ed_cloud_model.setText(str(cfg.get("cloud_model", "") or ""))
        if str(cfg.get("model_mode", "")).find("云端") >= 0:
            self.rb_cloud.setChecked(True)
            self.rb_local.setChecked(False)      # 两个单选不互斥，显式关掉另一个
        else:
            self.rb_local.setChecked(True)
            self.rb_cloud.setChecked(False)

        # ⚠️ 把「服务商」下拉框同步成**已保存地址对应的那一家**。
        #    不这么做的话，下拉框会停在默认的第一项（智谱 GLM），
        #    而下面的地址可能是别家的 —— 界面自相矛盾，用户会以为
        #    "我明明选的是智谱，怎么地址不对"。
        #    反查不到就落到「自定义」，并把已填内容原样留着。
        #    （踩过的坑：setCurrentText 选**同一个值**不会触发信号，
        #      所以不能指望 _apply_provider 帮忙同步。）
        match = "自定义（自己填）"
        for p in model_setup.CLOUD_PROVIDERS:
            if cloud_url and p["地址"] == cloud_url:
                match = p["名字"]
                break
        self.cb_provider.blockSignals(True)
        self.cb_provider.setCurrentText(match)
        self.cb_provider.blockSignals(False)
        self._apply_provider(match, fill=False)

        self._refresh_local_status()

    def fit_to_content(self, grow=False):
        """按各页**实际需要的尺寸**定窗口大小

        ⚠️ 关键是高度要用 heightForWidth(需要的宽度) 算，不能直接用 sizeHint()
        ------------------------------------------------------------------
        sizeHint() 给的是"在**当前**宽度下的高度"。而这里要设的是**最小宽度** ——
        窗口缩到那个宽度后，文字换行会更多、需要的高度比 sizeHint 报的更大。

        实测踩到的：宽 580 时那段"没装 Ollama"的四步说明需要 280px 高，
        而按 sizeHint 算出来的最小尺寸只给了 80px —— 差 200px，
        说明文字被裁掉（而这几行正是全部指引）。

        正确做法：
            宽度 = 各页 sizeHint 的首选宽（在那个宽度下不用额外换行）
            高度 = heightForWidth(那个宽度)（**在那个宽度下**真正需要的高度）

        grow=True 时，如果算出来比当前尺寸还大就跟着长大
        （状态文字从一句变成四步说明时，页面会明显变高）。

        **只增不减**：用户自己拉大过窗口的话，不该因为一次
        文字更新就被缩回去。
        """
        try:
            self.ensurePolished()
            need_w = need_h = 0
            for i in range(self.pageIds().__len__()):
                page = self.page(i)
                sh = page.sizeHint()
                w = max(sh.width(), page.minimumSizeHint().width())
                # 在那个宽度下真正需要的高度
                h = page.heightForWidth(w) if w > 0 else 0
                if h <= 0:
                    h = sh.height()          # 不支持 heightForWidth 就退回 sizeHint
                need_w = max(need_w, w)
                need_h = max(need_h, h)
            if need_w <= 0 or need_h <= 0:
                return
            min_w = need_w + self.CHROME_W
            min_h = need_h + self.CHROME_H
            self.setMinimumSize(min_w, min_h)
            if grow:
                # 初始给一点富余，别卡在"刚好装下"
                self.resize(max(self.width(), min_w + 70),
                            max(self.height(), min_h + 10))
        # 静默是故意的：尺寸算不出来不该拦住用户配模型 ——
        # 退化成 Qt 的默认尺寸，向导照样能用
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _apply_provider(self, name, fill=True):
        """选服务商 -> 自动填地址和模型名

        fill=False 时**只更新提示文字，不动已经填好的输入框** ——
        `_prefill()` 同步下拉框时会用到：那一步的目的只是让
        "下拉框显示的那家"和"已保存的地址"对上，不该把用户
        自己改过的地址/模型名覆盖掉。
        """
        p = model_setup.find_provider(name)
        if not p:
            # 「自定义（自己填）」：不动用户已经填好的内容
            self.lbl_provider_tip.setText(
                "自己填的话：地址用服务商文档里的 <b>chat/completions</b> 完整地址，"
                "模型名一个字符都不能错。")
            self.lbl_provider_tip.setStyleSheet("color:#64748b;")
            return
        if fill:
            self.ed_cloud_url.setText(p["地址"])
            self.ed_cloud_model.setText(p["模型"])
        self.lbl_provider_tip.setText(
            "%s · %s —— Key 去 <a href='%s'>%s</a> 申请"
            % (p["名字"], p["备注"], p["申请"], p["申请"]))
        self.lbl_provider_tip.setStyleSheet("color:#16a34a;")

    # ── 云端连通性测试 ──
    def _sync_mode_radios(self, *_args):
        """让「本地 / 云端」两个单选真正互斥。

        它们分别在各自的分组框里，Qt 的 autoExclusive 只在同一父控件内生效，
        所以用户能同时勾上两个；而保存逻辑是「云端优先」，于是会出现
        「我选的是本地，怎么存成了云端」。后点的那个赢，且不允许两个都不选。
        """
        local, cloud = self.rb_local.isChecked(), self.rb_cloud.isChecked()
        if local and cloud:
            if self.sender() is self.rb_cloud:
                self.rb_local.setChecked(False)
            else:
                self.rb_cloud.setChecked(False)
        elif not local and not cloud:
            self.rb_local.setChecked(True)

    def _update_cloud_test_visible(self, *_args):
        """只有选了「云端 API」才显示测试入口，本地模式不添乱。"""
        cloud = self.rb_cloud.isChecked()
        self.lnk_cloud_test.setVisible(cloud)
        if not cloud:
            self.lbl_cloud_test.setVisible(False)

    def _test_cloud(self):
        """真的向云端发一个最小请求。

        为什么要让用户多点这一下：`check(probe=False)` 只看配置齐不齐，
        Key 少一位照样显示 ready；真正的 401/404 要到第一次聊天才暴露，
        而那时用户只看到一句"出了点问题"。这里当场把原因说清楚。

        请求放后台线程：断网/超时最多 8 秒，不能冻住向导。
        线程里只发信号，不碰控件（线程守卫）。
        """
        self.lbl_cloud_test.setVisible(True)
        self.lbl_cloud_test.setText("⏳ 正在向云端发一个最小请求…")
        self.lbl_cloud_test.setStyleSheet("color:#64748b;")
        url = self.ed_cloud_url.text().strip()
        model = self.ed_cloud_model.text().strip()
        key = self.ed_cloud_key.text().strip()

        def _work():
            try:
                r = model_setup.test_cloud(url, model, key)
            except Exception as e:
                r = {"ok": False, "code": "exc",
                     "message": "%s: %s" % (type(e).__name__, str(e)[:80])}
            try:
                self.cloud_test_done.emit(r)
            except Exception as e:
                _x6_swallowed(__name__, e)

        threading.Thread(target=_work, daemon=True,
                         name="onboarding-cloud-test").start()

    def _apply_cloud_test(self, r):
        """回到主线程再改界面；成功绿、失败红，一句话给唯一修法。"""
        ok = bool((r or {}).get("ok"))
        msg = str((r or {}).get("message") or "")
        self.lbl_cloud_test.setVisible(True)
        self.lbl_cloud_test.setText(("✅ " if ok else "❌ ") + msg)
        self.lbl_cloud_test.setStyleSheet(
            "color:#16a34a;" if ok else "color:#dc2626;")
        try:
            self.fit_to_content(grow=True)
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")
