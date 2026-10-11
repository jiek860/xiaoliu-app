# -*- coding: utf-8 -*-
"""设置窗口 v3.0 - 分标签页：模型 / 界面 / 工具 / 扩展 / 记录 / 系统

原来"功能中心"里那批入口已全部并入这里，按用途分类成标签页。
"""
import json, threading, urllib.request
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QMessageBox, QInputDialog, QTabWidget, QWidget
from PyQt5.QtCore import QObject, pyqtSignal


def show_settings_dialog(parent, dlg, trunk, base, ai_name,
                         model_btn, local_light, cloud_light, chat, input_box,
                         commands=None):
    """设置窗口

    commands: {名称: 可调用}，由主窗口传入 —— 就是原来"功能中心"里的那批入口
              （电脑控制 / 系统 / 插件 / 日志 / MCP市场 / 机器人 / 历史记录 /
              首次设置向导）。某个回调没传或不可调用时，对应按钮置灰而不是报错。

    注意：这里原来还有个 title 参数，调用方传的是 getattr(self,"title","小6智能体")
    —— 主窗口根本没有 title 属性，所以永远是那个字符串；而「改名」按钮却对它调
    .setText()，一点就抛 AttributeError。参数已删除，改名改用 parent.setWindowTitle()。
    """
    d, l = dlg("设置", 620, 640)
    CMD = commands or {}

    def _open_btn(icon, name, desc):
        """生成一个"打开某个功能窗口"的按钮。

        行为和原来的功能中心一致：先关掉设置窗口，再打开目标窗口。
        """
        b = QPushButton("%s  %s" % (icon, name))
        b.setToolTip(desc)
        b.setMinimumHeight(34)
        fn = CMD.get(name)
        if not callable(fn):
            b.setEnabled(False)
            b.setToolTip("这个功能在当前版本不可用")
            return b

        def _go(_checked=False, f=fn, n=name):
            try:
                d.close()
            except Exception:
                pass
            try:
                f()
            except Exception as e:
                QMessageBox.warning(None, n, "打开失败: %s" % str(e)[:80])
        b.clicked.connect(_go)
        return b

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

    # Ollama 探测放后台做。
    # 原来是在**构建对话框的过程中**直接发请求（timeout=3），
    # Ollama 不在线时（比如 ollama_url 指向局域网里没开的机器），
    # 每次点「设置」都要先卡满 3 秒窗口才出来。
    ollama_lbl = QLabel("⏳ 正在检测 Ollama…")
    l1.addWidget(ollama_lbl)

    class _Probe(QObject):
        done = pyqtSignal(str)

    # 以对话框为父对象，并把引用挂到 d 上 ——
    # 只写成局部变量的话，函数返回后它可能被 Python 回收，
    # 后台线程 emit 的信号就没人接了（实测标签一直停在"正在检测…"）。
    _probe = _Probe(d)
    d._ollama_probe = _probe
    _probe.done.connect(ollama_lbl.setText)

    def _probe_ollama():
        try:
            url = trunk.config.get("ollama_url", "http://localhost:11434")
            req = urllib.request.Request(url + "/api/tags")
            data = json.loads(urllib.request.urlopen(req, timeout=3).read())
            n = len(data.get("models", []))
            text = "📦 已检测到 %d 个模型" % n
        except Exception:
            text = "⚠️ Ollama 未连接"
        try:
            _probe.done.emit(text)
        except Exception:
            pass

    threading.Thread(target=_probe_ollama, daemon=True,
                     name="settings-ollama-probe").start()

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
    l1.addWidget(_open_btn("📦", "模型管理",
                           "列出 / 下载 / 删除 Ollama 本地模型"))

    l1.addWidget(QLabel("\n🌐 联网"))
    net_chk = QCheckBox("允许联网检索（对话时按需搜索）")
    net_chk.setChecked(trunk.config.get("联网", True))
    l1.addWidget(net_chk)
    tabs.addTab(tab1, "🤖 模型")

    # ===== 标签2: 界面 =====
    tab2 = QWidget()
    l2 = QVBoxLayout(tab2)
    l2.addWidget(QLabel("👤 身份命名"))
    l2.addWidget(QLabel("AI名字:"))
    ne = QLineEdit(ai_name)
    l2.addWidget(ne)

    def _rename():
        """改名：写配置 + 改窗口标题 + 改聊天里显示的名字

        原来这一行是：
            QPushButton("改名", clicked=lambda: (title.setText("✨ " + ne.text())))
        而 title 是调用方传进来的**字符串**（getattr(self,"title","小6智能体")），
        字符串没有 setText —— 点一下必然抛 AttributeError。
        run.py 装了 excepthook，所以程序不会崩，但改名完全不生效，
        而且每次点都往 crashes.log 里写一条，把自检健康分扣掉 20。
        """
        new = (ne.text() or "").strip()
        if not new:
            QMessageBox.information(d, "改名", "名字不能是空的")
            return
        try:
            trunk.config["ai_name"] = new
            trunk.save_config()
        except Exception as e:
            QMessageBox.warning(d, "改名", "保存失败: " + str(e)[:80])
            return
        # 主窗口的标题和聊天里显示的名字一起改掉
        try:
            parent.setWindowTitle("✨ " + new)
        except Exception:
            pass
        try:
            parent.ai_name = new
        except Exception:
            pass
        QMessageBox.information(d, "改名", "现在叫「%s」了" % new)

    l2.addWidget(QPushButton("改名", clicked=_rename))

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
    l2.addWidget(QLabel("\n🐾 桌面"))
    l2.addWidget(_open_btn("🐾", "桌宠", "桌面悬浮窗，再点一次收起"))
    tabs.addTab(tab2, "🎨 界面")

    # ===== 标签3: 工具（原来是功能中心的"帮你干活"一组）=====
    tab3 = QWidget()
    l3 = QVBoxLayout(tab3)
    l3.addWidget(QLabel("🛠️ 工具"))
    l3.addWidget(_open_btn("🖥️", "电脑控制", "操作软件 / 文件 / 窗口 / 系统"))
    l3.addWidget(_open_btn("🤖", "机器人", "企业微信 / 钉钉聊天机器人"))
    l3.addWidget(_open_btn("🎙️", "语音对话",
                           "语音实时对话：静音自动断句、可随时打断、连续多轮"))
    l3.addWidget(_open_btn("📅", "日历待办", "日历 + 待办 + 笔记"))
    l3.addWidget(_open_btn("🧰", "实用工具",
                           "图片识别 / 记忆整理 / 统计报表 / 一键迁移 / 群聊辩论 等"))
    l3.addWidget(_open_btn("🕸️", "模块星图",
                           "全部模块的星型拓扑图（用系统浏览器打开，实时刷新）"))
    l3.addStretch(1)
    tabs.addTab(tab3, "🛠️ 工具")

    # ===== 标签4: 扩展（插件 + MCP）=====
    tab4 = QWidget()
    l4 = QVBoxLayout(tab4)
    l4.addWidget(QLabel("🧩 扩展"))
    l4.addWidget(_open_btn("🧩", "插件", "安装 / 卸载 / 热加载模块"))
    # MCP 的所有东西都在 mcp_dialog 那一页里（服务器管理 / 预置服务器 / 配置参考）。
    # 这里原来还有个"MCP服务器地址 + 保存并重连"，写的是 config["mcp_url"] ——
    # 全项目没有任何代码读那个键，是个死设置；真正生效的是 config["mcp_servers"]。
    l4.addWidget(_open_btn("🔌", "MCP", "服务器管理 / 预置服务器 / 配置参考"))
    l4.addStretch(1)
    tabs.addTab(tab4, "🧩 扩展")

    # ===== 标签5: 记录 =====
    tab5 = QWidget()
    l5 = QVBoxLayout(tab5)
    l5.addWidget(QLabel("📜 记录"))
    l5.addWidget(_open_btn("📜", "历史记录", "分页 / 搜索 / 导出全部聊天记录"))
    l5.addWidget(_open_btn("📋", "日志", "运行日志 / 错误 / 操作记录"))
    l5.addWidget(_open_btn("🔍", "搜索聊天", "全局搜索所有会话里的消息"))
    l5.addWidget(_open_btn("🧠", "记忆可视化", "记忆时间线 / 图谱 / 搜索 / 编辑"))
    l5.addWidget(_open_btn("📊", "数据统计", "用量与数据的统计报表"))
    l5.addStretch(1)
    tabs.addTab(tab5, "📜 记录")

    # ===== 标签6: 系统 =====
    tab6 = QWidget()
    l6 = QVBoxLayout(tab6)
    l6.addWidget(QLabel("⚙️ 系统"))
    l6.addWidget(_open_btn("⚙️", "系统", "深度自检 / 备份 / 训练"))
    l6.addWidget(_open_btn("🧭", "首次设置向导", "模型没配好、它不回话时打开这个"))
    l6.addWidget(_open_btn("📱", "手机远程", "手机连上这台电脑使用"))
    l6.addWidget(_open_btn("🔄", "检查更新", "检查新版本 / 回滚 / 更新历史"))
    l6.addStretch(1)
    tabs.addTab(tab6, "⚙️ 系统")

    # 原来的"🗂 数据"和"⚙️ 高级"两个标签已移除（按需求只保留后台运行）：
    #   · 数据页：只有"记忆管理"(trunk.call vector_store run) 和"电脑控制"两个
    #     按钮，两个功能在对话链路 / 上面「工具」页里都照常可用
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



