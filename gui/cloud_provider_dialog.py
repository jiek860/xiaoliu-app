# -*- coding: utf-8 -*-
"""Extracted cloud-provider configuration dialog."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)

from core.llm_providers import provider_names, provider_spec
from core.model_router import capability_report


class CloudProviderDialog(QDialog):
    def __init__(self, parent, trunk):
        super().__init__(parent)
        self.trunk = trunk
        cfg = getattr(trunk, "config", {}) or {}
        self.setWindowTitle("云端模型 / 服务商")
        self.resize(560, 430)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.provider = QComboBox()
        self.provider.addItem("自定义 / OpenAI 兼容", "")
        for name in provider_names():
            self.provider.addItem(provider_spec(name).get("label", name), name)
        idx = self.provider.findData(str(cfg.get("cloud_provider") or ""))
        if idx >= 0:
            self.provider.setCurrentIndex(idx)
        form.addRow("服务商:", self.provider)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems([
            "glm-4-flash", "qwen-turbo", "qwen-plus", "deepseek-chat",
            "gpt-4o-mini", "claude-3-5-sonnet-latest", "gemini-1.5-flash",
            "openai/gpt-4o-mini", "local-model",
        ])
        self.model.setCurrentText(str(cfg.get("cloud_model") or "qwen-turbo"))
        form.addRow("模型 / Azure deployment:", self.model)
        self.url = QLineEdit(str(cfg.get("cloud_url") or ""))
        form.addRow("API 地址:", self.url)
        self.key = QLineEdit(str(cfg.get("cloud_key") or ""))
        self.key.setEchoMode(QLineEdit.Password)
        form.addRow("API Key:", self.key)
        self.api_version = QLineEdit(str(cfg.get("azure_api_version") or "2024-06-01"))
        form.addRow("Azure API version:", self.api_version)
        lay.addLayout(form)
        self.capability = QLabel("")
        self.capability.setWordWrap(True)
        self.capability.setStyleSheet("color:#667085;font-size:11px;")
        lay.addWidget(self.capability)
        save = QPushButton("保存")
        save.clicked.connect(self._save)
        lay.addWidget(save)
        self.provider.currentIndexChanged.connect(lambda _i: self._provider_changed())
        self.model.currentTextChanged.connect(lambda _t: self._refresh_capability())
        self._refresh_capability()

    def _provider_changed(self):
        spec = provider_spec(self.provider.currentData()) if self.provider.currentData() else {}
        if spec:
            if spec.get("base_url"):
                self.url.setText(str(spec["base_url"]))
            if spec.get("default_model"):
                self.model.setCurrentText(str(spec["default_model"]))
            self.key.setPlaceholderText(
                "本地服务通常不需要 Key" if spec.get("local") else "API Key")
        self._refresh_capability()

    def _refresh_capability(self):
        provider = str(self.provider.currentData() or "openai")
        report = capability_report(provider, self.model.currentText().strip())
        self.capability.setText(
            "能力: tools=%s json=%s vision=%s context=%s" % (
                report["tool_calling"], report["json_mode"], report["vision"],
                report["context_window"]))

    def values(self):
        return {
            "cloud_provider": str(self.provider.currentData() or ""),
            "cloud_model": self.model.currentText().strip(),
            "cloud_url": self.url.text().strip(),
            "cloud_key": self.key.text().strip(),
            "azure_api_version": self.api_version.text().strip() or "2024-06-01",
        }

    def _save(self):
        values = self.values()
        self.trunk.config.update(values)
        self.trunk.save_config()
        QMessageBox.information(self, "成功", "云端模型配置已保存")
        self.accept()


def configure_cloud_provider(parent, trunk):
    d = CloudProviderDialog(parent, trunk)
    return d.exec_(), d.values()
