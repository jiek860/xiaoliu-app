# -*- coding: utf-8 -*-
"""首次设置：保存、结果展示和向导结束流程。"""
from __future__ import annotations

import os
import time
from PyQt5.QtWidgets import QMessageBox

from core import model_setup
from gui.onboarding_utils import _model_text, mark_done

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class OnboardingFinalMixin:
    def _save_and_check(self):
        try:
            if self.rb_cloud.isChecked():
                model_setup.apply_cloud(
                    self.trunk,
                    url=self.ed_cloud_url.text().strip(),
                    model=self.ed_cloud_model.text().strip(),
                    key=self.ed_cloud_key.text().strip())
            else:
                model_setup.apply_local(
                    self.trunk,
                    url=self.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA,
                    model=_model_text(self.ed_local_model)
                    or model_setup.RECOMMENDED_LOCAL_MODEL)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e)[:120])
            return
        self._reload_llm_config()
        self._refresh_local_status()
        self._show_result()

    def _reload_llm_config(self):
        """保存后热加载。

        不重载的话，启动时创建的 LLMClient 还拿着**旧配置**：用户刚在向导里
        填好 Key，第一次聊天仍然报错，看起来像"向导没生效"，只能重启程序。
        设置页保存时已经这么做了（dialog_mixin），向导这边原来漏了。
        """
        try:
            llm = (getattr(self.trunk, "modules", None) or {}).get("llm")
            if llm is not None and hasattr(llm, "reload_config"):
                llm.reload_config()
        except Exception as e:
            _x6_swallowed(__name__, e, "reload llm config after onboarding")

    def _pending_config(self):
        """用户在向导里填了、但还没点「保存并检测」的配置。

        返回 "cloud" / "local" / ""。
        为什么需要：很多人填完模型名直接点「完成」，配置没落盘，
        下次启动还是"没配好" —— 填了就等于要用，不该要求先点保存。
        """
        cfg = getattr(self.trunk, "config", None) or {}
        if self.rb_cloud.isChecked():
            url = self.ed_cloud_url.text().strip()
            model = self.ed_cloud_model.text().strip()
            key = self.ed_cloud_key.text().strip()
            if not (url and model and key):
                return ""
            if (str(cfg.get("model_mode", "")) != "云端模型"
                    or str(cfg.get("cloud_url", "") or "") != url
                    or str(cfg.get("cloud_model", "") or "") != model
                    or not str(cfg.get("cloud_key", "") or "")):
                return "cloud"
            return ""
        url = self.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA
        model = _model_text(self.ed_local_model)
        if not model:
            return ""
        if (str(cfg.get("model_mode", "")) != "本地模型"
                or str(cfg.get("ollama_url", "") or "") != url
                or str(cfg.get("local_model", "") or "") != model):
            return "local"
        return ""

    def _show_result(self):
        try:
            r = model_setup.check(self.trunk)
        except Exception as e:
            self.lbl_result.setText("检测出错：" + str(e)[:100])
            return
        if r["ready"]:
            self.lbl_result.setText("✅ 配置完成，可以正常聊天了。")
            self.lbl_result.setStyleSheet(
                "padding:6px;border-radius:4px;background:#dcfce7;color:#166534;")
        else:
            self.lbl_result.setText(
                "⚠️ 还差一点：\n· " + "\n· ".join(r["problems"])
                + "\n\n" + r["advice"])
            self.lbl_result.setStyleSheet(
                "padding:6px;border-radius:4px;background:#fef3c7;color:#92400e;")

    def _on_page_changed(self, pid):
        if pid == 0:
            if not self.ed_ollama.text():
                self._prefill()
        elif pid == 1:
            self._refresh_local_status()
            self._show_result()
        elif pid == 2:
            self._fill_final()

    def _fill_final(self):
        try:
            r = model_setup.check(self.trunk, probe=False)
        except Exception:
            r = {"ready": False, "problems": ["检测失败"], "advice": "稍后可以在设置里再配。"}
        if r["ready"]:
            self.lbl_final.setText(
                "<h2>🎉 配好了</h2>"
                "点「完成」就能开始聊天了。<br><br>"
                "想换个模型、调语气、开关联网，随时去「设置」里改。")
        else:
            self.lbl_final.setText(
                "<h2>暂时还不能聊天</h2>"
                "缺的是：<br>· " + "<br>· ".join(r["problems"]) +
                "<br><br>" + r["advice"].replace("\n", "<br>") +
                "<br><br>点「完成」不会丢东西，你随时可以从"
                "「设置 → 系统 → 首次设置向导」重新打开这一页。")

    def accept(self):
        self._save_and_note()
        super().accept()

    def reject(self):
        # 用户点了取消/关闭，也算引导过了，别每次启动都弹
        self._save_and_note()
        super().reject()

    def _save_and_note(self):
        """收尾：填了但没保存的配置先落盘，再写「已引导」标记。"""
        try:
            if self._pending_config():
                self._save_and_check()
        except Exception as e:
            _x6_swallowed(__name__, e, "apply pending onboarding config")
        mark_done(self.trunk)
