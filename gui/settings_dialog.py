# -*- coding: utf-8 -*-
"""设置窗口 v2.1 - 分标签页：模型 / 界面"""
import os, json, urllib.request
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QComboBox, QCheckBox,
                             QMessageBox, QInputDialog,
                             QTabWidget, QWidget, QFormLayout)


def show_settings_dialog(parent, dlg, trunk, base, ai_name, title,
                         model_btn, local_light, cloud_light, chat, input_box):
    """设置窗口 - 分标签页"""
    d, l = dlg("设置", 550, 600)

    # 标签页
    tabs = QTabWidget()

    # ===== 标签1: 模型 =====
    tab1 = QWidget()
    l1 = QVBoxLayout(tab1)
    l1.addWidget(QLabel("🤖 模型配置"))
    l1.addWidget(QLabel("模型模式:"))
    m = QComboBox()
    m.addItems(["本地路由", "云端模型"])
    _cur_mode = trunk.config.get("model_mode", "本地路由")
    m.setCurrentText("云端模型" if "云端" in str(_cur_mode) else "本地路由")
    l1.addWidget(m)

    def check_local():
        try:
            ollama_url = trunk.config.get("ollama_url", "http://localhost:11434")
            req = urllib.request.Request(ollama_url + "/api/tags")
            data = json.loads(urllib.request.urlopen(req, timeout=3).read())
            models = [mm["name"] for mm in data.get("models", [])]
            d2 = QDialog(d)
            d2.setWindowTitle("选择本地模型")
            d2.setFixedSize(350, 300)
            l2 = QVBoxLayout(d2)
            l2.addWidget(QLabel("检测到 %d 个模型：" % len(models)))
            def _pick_local(x):
                trunk.config["local_model"] = x
                trunk.save_config()
                d2.accept()
                QMessageBox.information(d, "成功", "已选择: " + x)
            for mm in models:
                l2.addWidget(QPushButton(mm, clicked=lambda checked, x=mm: _pick_local(x)))
            d2.exec_()
        except:
            QMessageBox.warning(d, "错误", "Ollama未启动\n请先打开Ollama")
    l1.addWidget(QPushButton("检测本地模型", clicked=check_local))

    try:
        ollama_url = trunk.config.get("ollama_url", "http://localhost:11434")
        req = urllib.request.Request(ollama_url + "/api/tags")
        data = json.loads(urllib.request.urlopen(req, timeout=3).read())
        models = [mm["name"] for mm in data.get("models", [])]
        l1.addWidget(QLabel("📦 已检测到 %d 个模型" % len(models)))
    except:
        l1.addWidget(QLabel("⚠️ Ollama未连接"))

    def cloud_set():
        d2 = QDialog(d); d2.setWindowTitle("云端模型"); l2 = QVBoxLayout(d2)
        l2.addWidget(QLabel("云端模型:"))
        cc = QComboBox(); cc.setEditable(True)
        cc.addItems([
            "glm-4-flash", "glm-4", "glm-4v-flash",
            "qwen-turbo", "qwen-plus", "qwen-max", "qwen-vl-plus",
            "deepseek-chat", "deepseek-reasoner",
            "ernie-3.5-8k", "ernie-4.0-8k",
            "hunyuan-lite", "hunyuan-pro",
            "yi-lightning", "yi-large",
            "moonshot-v1-8k",
            "gpt-4o", "gpt-4", "claude-3-5-sonnet"
        ])
        cc.setCurrentText(trunk.config.get("cloud_model", "qwen-turbo"))
        l2.addWidget(cc)
        l2.addWidget(QLabel("API地址:"))
        uu = QLineEdit("https://open.bigmodel.cn/api/paas/v4/chat/completions")
        l2.addWidget(uu)
        l2.addWidget(QLabel("API密钥:"))
        kk = QLineEdit(); kk.setEchoMode(QLineEdit.Password)
        kk.setText(trunk.config.get("cloud_key", ""))
        l2.addWidget(kk)
        def save_c():
            setattr(trunk, 'config', {**trunk.config, "cloud_model": cc.currentText(),
                                      "cloud_url": uu.text(), "cloud_key": kk.text(),
                                      "model_mode": "云端模型"})
            trunk.save_config()
            try: trunk.modules["llm"].reload_config()
            except: pass
            model_btn.setText("🔄 模型:云端")
            local_light.setStyleSheet("color:#666;")
            cloud_light.setStyleSheet("color:#0f0;")
            d2.accept(); QMessageBox.information(d, "成功", "云端已设置")
        l2.addWidget(QPushButton("确认", clicked=save_c))
        d2.exec_()
    l1.addWidget(QPushButton("云端模型设置", clicked=cloud_set))

    l1.addWidget(QLabel("\n🔌 MCP服务器"))
    l1.addWidget(QLabel("MCP服务器地址:"))
    mcp_url = QLineEdit(trunk.config.get("mcp_url", "http://localhost:3742"))
    l1.addWidget(mcp_url)
    l1.addWidget(QPushButton("保存并重连", clicked=lambda: (
        trunk.config.update({"mcp_url": mcp_url.text()}),
        trunk.save_config(),
        QMessageBox.information(d, "成功", "MCP地址已保存，重启生效")
    )))
    tabs.addTab(tab1, "🤖 模型")

    # ===== 标签2: 界面 =====
    tab2 = QWidget()
    l2 = QVBoxLayout(tab2)
    l2.addWidget(QLabel("👤 身份命名"))
    l2.addWidget(QLabel("AI名字:"))
    ne = QLineEdit(ai_name)
    l2.addWidget(ne)
    l2.addWidget(QPushButton("改名", clicked=lambda: (title.setText("✨ " + ne.text()))))

    l2.addWidget(QLabel("\n🎨 外观"))
    l2.addWidget(QLabel("字体大小:"))
    fs = QComboBox()
    fs.addItems(["12px", "14px", "16px", "18px"])
    l2.addWidget(fs)

    l2.addWidget(QLabel("\n🌐 网络"))
    net_chk = QCheckBox("联网开关")
    net_chk.setChecked(trunk.config.get("联网", True))
    l2.addWidget(net_chk)

    def _edit_persona():
        cur = trunk.config.get("ai_persona", "你是小6，住在用户电脑里的AI朋友。说话口语化，简短直接。")
        txt, ok = QInputDialog.getMultiLineText(d, "AI人格", "描述小6的性格/说话风格：", cur)
        if ok and txt.strip():
            trunk.config["ai_persona"] = txt.strip()
            trunk.save_config()
            QMessageBox.information(d, "已保存", "AI人格已更新")
    l2.addWidget(QLabel("\n🧠 AI人格"))
    l2.addWidget(QPushButton("编辑AI人格", clicked=_edit_persona))
    tabs.addTab(tab2, "🎨 界面")

    # 原来的"🗂 数据"和"⚙️ 高级"两个标签已移除（按需求只保留后台运行）：
    #   · 数据页：只有"记忆管理"(trunk.call vector_store run) 和"电脑控制"两个
    #     按钮，两个功能在对话链路 / 功能中心里都照常可用
    #   · 高级页：只有一个 QTextBrowser 日志框，而且**从来没有被写入过**，
    #     是个空摆设
    # 后台的 vector_store / knowledge_graph 等模块不受影响，照常随 trunk 加载。

    l.addWidget(tabs)

    # 保存按钮
    def do_save():
        trunk.config["model_mode"] = m.currentText()
        try: trunk.modules["llm"].reload_config()
        except: pass
        if "云端" in m.currentText():
            model_btn.setText("🔄 模型:云端")
            local_light.setStyleSheet("color:#666;")
            cloud_light.setStyleSheet("color:#0f0;")
        else:
            model_btn.setText("🔄 模型:本地路由")
            local_light.setStyleSheet("color:#0f0;")
            cloud_light.setStyleSheet("color:#0f0;")
        trunk.config["ai_name"] = ne.text()
        trunk.config["font_size"] = fs.currentText()
        try:
            sz = int(fs.currentText().replace("px", ""))
            chat.setStyleSheet("font-size:%dpx;" % sz)
            input_box.setStyleSheet("font-size:%dpx; border:none; background:transparent;" % sz)
        except: pass
        trunk.config["联网"] = net_chk.isChecked()
        trunk.save_config()
        QMessageBox.information(d, "成功", "已保存")
    l.addWidget(QPushButton("保存", clicked=do_save))
    d.exec_()



