# -*- coding: utf-8 -*-
"""设置窗口 v4.0  简单模式 3 页，高级模式完整分级。

简单模式：
    开始：模型配置、本地/云端
    使用：界面、知识库、通知、更新、模式切换
    帮助：新手教程、安全中心、反馈

高级模式：
    模型 / 界面 / 工具 / 扩展 / 记录 / 系统 / 开发者

原则：功能不删，只分级。所有旧入口在高级模式仍然一键可达。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None
from core.safe_http import open_url as safe_open_url
import json
import threading
import urllib.request

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QMessageBox, QInputDialog, QTabWidget, QWidget,
    QScrollArea,
)
from gui.settings_widgets import (
    make_hint, make_open_button, make_scroll_tab, make_tab,
)


def show_settings_dialog(parent, dlg, trunk, base, ai_name,
                         model_btn, local_light, cloud_light, chat, input_box,
                         commands=None):
    """设置窗口。

    commands: {名称: 可调用}，由主窗口传入；缺入口时按钮置灰并说明。
    """
    d, l = dlg("设置", 680, 700)
    CMD = commands or {}
    simple = True
    try:
        from gui.ui_mode import get_ui_mode
        simple = get_ui_mode(base, getattr(trunk, "config", {})) == "simple"
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass

    def _open_btn(icon, name, desc, key=None):
        return make_open_button(d, CMD, icon, name, desc, key)

    def _hint(text):
        return make_hint(text)

    def _tab(title):
        return make_tab(title)

    def _scroll_tab(title, build):
        return make_scroll_tab(title, build)

    # ================= 通用：模型配置 =================
    def build_model(lay):
        lay.addWidget(QLabel(" 模型配置"))
        lay.addWidget(QLabel("模型模式:"))
        mode_box = QComboBox()
        mode_box.addItems(["本地路由", "云端模型"])
        mode_box.setToolTip(
            "本地路由：隐私好、免费，但依赖 Ollama；云端模型：效果通常更好，按量计费")
        cur_mode = trunk.config.get("model_mode", "本地路由")
        mode_box.setCurrentText(
            "云端模型" if "云端" in str(cur_mode) else "本地路由")
        lay.addWidget(mode_box)
        lay.addWidget(_hint(
            "影响：本地路由需要 Ollama 在线；云端模式需要有效的 API 地址和 Key。"))

        class _ModelsReady(QObject):
            done = pyqtSignal(object, str)

        mr = _ModelsReady(d)
        d._model_probe = mr
        check_btn = QPushButton("检测本地模型")
        lay.addWidget(check_btn)

        def on_models(models, err):
            check_btn.setEnabled(True)
            check_btn.setText("检测本地模型")
            if err:
                QMessageBox.warning(d, "错误", "Ollama 未启动\n请先打开 Ollama")
                return
            pick = QDialog(d)
            pick.setWindowTitle("选择本地模型")
            pick.resize(360, 320)
            pl = QVBoxLayout(pick)
            pl.addWidget(QLabel("检测到 %d 个模型：" % len(models)))
            for mm in models:
                def _pick(_checked=False, x=mm):
                    trunk.config["local_model"] = x
                    trunk.save_config()
                    pick.accept()
                    QMessageBox.information(d, "成功", "已选择: " + x)
                pl.addWidget(QPushButton(mm, clicked=_pick))
            pick.exec_()

        mr.done.connect(on_models)

        def check_local():
            check_btn.setEnabled(False)
            check_btn.setText("检测中")

            def work():
                try:
                    url = trunk.config.get(
                        "ollama_url", "http://localhost:11434").rstrip("/")
                    probe_url = url + "/api/tags"
                    # ⚠️ 必须走网络守卫：否则"虚拟机连物理机"这种
                    #    局域网地址会被这里绕过策略直接请求，行为和真实
                    #    聊天请求（走守卫）不一致 —— 本机显示未连接但聊天能用，
                    #    或者本机显示已连接但聊天被拦。
                    from core.net_guard import get_net_guard
                    _d = get_net_guard(trunk).check(
                        probe_url, module="settings", purpose="local_model")
                    if not _d.get("allow"):
                        raise PermissionError(
                            "网络策略拒绝: %s（可在设置里把该主机加入信任）"
                            % _d.get("reason"))
                    req = urllib.request.Request(probe_url)
                    data = json.loads(
                        safe_open_url(req, timeout=3).read())
                    models = [m["name"] for m in data.get("models", [])]
                    err = ""
                except Exception as e:
                    models, err = [], str(e)[:60]
                try:
                    mr.done.emit(models, err)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            threading.Thread(target=work, daemon=True,
                             name="settings-model-probe").start()

        check_btn.clicked.connect(check_local)

        def trust_current_host():
            """把当前 ollama_url 的主机加入局域网信任白名单。

            实现在 core/lan_trust.py（本文件有 600 行上限）。
            """
            from PyQt5.QtWidgets import QMessageBox
            from core.lan_trust import trust_host
            ok, msg = trust_host(trunk)
            if ok:
                QMessageBox.information(d, "已信任", msg)
            else:
                QMessageBox.warning(d, "失败", msg)

        # 不新增按钮（按钮预算限制）。"信任当前主机"放在检测按钮的右键菜单里：
        # 这是一个低频配置项，且和"检测本地模型"是同一个心智模型。
        check_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        check_btn.setToolTip(
            "检测本地模型（右键可把当前主机加入局域网信任）")

        def _show_trust_menu(pos):
            from PyQt5.QtWidgets import QMenu
            menu = QMenu(check_btn)
            menu.addAction("信任当前主机（虚拟机连物理机时用）",
                           trust_current_host)
            menu.exec_(check_btn.mapToGlobal(pos))

        check_btn.customContextMenuRequested.connect(_show_trust_menu)
        ollama_lbl = QLabel(" 正在检测 Ollama")
        lay.addWidget(ollama_lbl)

        class _Probe(QObject):
            done = pyqtSignal(str)

        probe = _Probe(d)
        d._ollama_probe = probe
        probe.done.connect(ollama_lbl.setText)

        def probe_ollama():
            try:
                url = trunk.config.get(
                    "ollama_url", "http://localhost:11434").rstrip("/")
                probe_url = url + "/api/tags"
                from core.net_guard import get_net_guard
                _d = get_net_guard(trunk).check(
                    probe_url, module="settings", purpose="local_model")
                if not _d.get("allow"):
                    text = " Ollama 被网络策略拦截（%s）" % str(
                        _d.get("reason"))[:40]
                    try:
                        probe.done.emit(text)
                    except Exception as e:  # 静默是故意的
                        _x6_swallowed(__name__, e)
                    return
                req = urllib.request.Request(probe_url)
                data = json.loads(
                    safe_open_url(req, timeout=3).read())
                text = " 已检测到 %d 个模型" % len(data.get("models", []))
            except Exception:
                text = " Ollama 未连接"
            try:
                probe.done.emit(text)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        threading.Thread(target=probe_ollama, daemon=True,
                         name="settings-ollama-probe").start()

        cloud_btn = QPushButton("配置云端模型")
        lay.addWidget(cloud_btn)

        def cloud_set():
            from gui.cloud_provider_dialog import configure_cloud_provider
            configure_cloud_provider(d, trunk)

        cloud_btn.clicked.connect(cloud_set)
        lay.addWidget(QLabel(
            "本地：先安装 Ollama；云端：填 API 地址和 Key。"))
        return mode_box
    # ================= 界面 / 使用 =================
    def build_interface(lay, include_advanced_tools=True):
        lay.addWidget(QLabel(" 身份命名"))
        lay.addWidget(QLabel("AI 名字:"))
        ne = QLineEdit(ai_name)
        lay.addWidget(ne)

        def _rename():
            new = (ne.text() or "").strip()
            if not new:
                QMessageBox.information(d, "改名", "名字不能是空的")
                return
            try:
                trunk.config["ai_name"] = new
                trunk.save_config()
                parent.setWindowTitle(" " + new)
                parent.ai_name = new
            except Exception as e:
                QMessageBox.warning(d, "改名", "保存失败: " + str(e)[:80])
                return
            QMessageBox.information(d, "改名", "现在叫「%s」了" % new)

        lay.addWidget(QPushButton("改名", clicked=_rename))

        lay.addWidget(QLabel("\n 外观"))
        lay.addWidget(QLabel("字体大小:"))
        fs = QComboBox()
        fs.addItems(["12px", "14px", "16px", "18px"])
        fs.setCurrentText(trunk.config.get("font_size", "14px"))
        fs.setToolTip("立即影响聊天和输入框文字大小")
        lay.addWidget(fs)

        from gui.theme_manager import THEME_LABELS, DENSITY_LABELS, ThemeManager
        appearance = ThemeManager(base).appearance
        lay.addWidget(QLabel("主题:"))
        theme_box = QComboBox()
        theme_box.addItems(list(THEME_LABELS.values()))
        theme_box.setCurrentText(THEME_LABELS.get(
            appearance.get("theme", "system"), "跟随系统"))
        theme_box.setToolTip("切换后立即预览，保存后持久化")
        lay.addWidget(theme_box)
        lay.addWidget(QLabel("界面密度:"))
        density_box = QComboBox()
        density_box.addItems(list(DENSITY_LABELS.values()))
        density_box.setCurrentText(DENSITY_LABELS.get(
            appearance.get("density", "comfortable"), "舒适"))
        density_box.setToolTip("影响按钮内边距和列表疏密")
        lay.addWidget(density_box)
        lay.addWidget(_hint(
            "主题和密度修改会立即预览；窗口位置/大小在退出时自动记住。"))
        d._settings_theme = theme_box
        d._settings_density = density_box

        def _preview_appearance():
            try:
                from gui.theme_manager import (
                    THEME_LABELS, DENSITY_LABELS, ThemeManager)
                inv_theme = {v: k for k, v in THEME_LABELS.items()}
                inv_density = {v: k for k, v in DENSITY_LABELS.items()}
                tm = ThemeManager(base)
                tm.set_options(
                    theme=inv_theme.get(theme_box.currentText(), "system"),
                    density=inv_density.get(density_box.currentText(), "comfortable"),
                    font_size=int(fs.currentText().replace("px", "")))
                if parent is not None and hasattr(parent, "theme_manager"):
                    parent.theme_manager = tm
                    tm.apply_to(parent)
            except Exception:  # 静默是故意的
                pass
        theme_box.currentIndexChanged.connect(lambda _i: _preview_appearance())
        density_box.currentIndexChanged.connect(lambda _i: _preview_appearance())
        fs.currentIndexChanged.connect(lambda _i: _preview_appearance())

        lay.addWidget(QLabel("\n 网络"))
        net_chk = QCheckBox("联网开关")
        net_chk.setChecked(trunk.config.get("联网", True))
        net_chk.setToolTip("关闭后模型和工具的网络请求会被阻止，本地模型仍可用")
        lay.addWidget(net_chk)
        lay.addWidget(_hint("影响：搜索、云端模型、插件市场和更新检查。"))

        lay.addWidget(QLabel("\n AI 人格"))
        persona_btn = QPushButton("编辑 AI 人格")
        lay.addWidget(persona_btn)

        def _edit_persona():
            cur = trunk.config.get(
                "ai_persona",
                "你是小6，住在用户电脑里的AI朋友。说话口语化，简短直接。")
            txt, ok = QInputDialog.getMultiLineText(
                d, "AI人格", "描述小6的性格/说话风格：", cur)
            if ok and txt.strip():
                trunk.config["ai_persona"] = txt.strip()
                trunk.save_config()
                QMessageBox.information(d, "已保存", "AI 人格已更新")
        persona_btn.clicked.connect(_edit_persona)

        lay.addWidget(QLabel("\n 快捷键"))
        shortcut_edit = QLineEdit(
            trunk.config.get("shortcut_command_palette", "Ctrl+K"))
        shortcut_edit.setPlaceholderText("Ctrl+K")
        shortcut_edit.setToolTip("命令面板全局快捷键，保存后立即生效")
        lay.addWidget(shortcut_edit)
        d._settings_shortcut = shortcut_edit

        lay.addWidget(QLabel("\n 模式"))
        mode_switch = QComboBox()
        mode_switch.addItems(["简单模式", "高级模式"])
        mode_switch.setCurrentText("简单模式" if simple else "高级模式")
        lay.addWidget(mode_switch)

        def _switch_mode():
            target = "advanced" if mode_switch.currentText() == "高级模式" else "simple"
            try:
                from gui.ui_mode import set_ui_mode
                set_ui_mode(base, target, trunk.config, trunk.save_config)
                if parent is not None and hasattr(parent, "_set_ui_mode"):
                    parent._set_ui_mode(target)
                QMessageBox.information(
                    d, "模式已切换",
                    "已切换到%s模式。重新打开设置即可看到对应分级。" %
                    ("高级" if target == "advanced" else "简单"))
                d.close()
            except Exception as e:
                QMessageBox.warning(d, "切换失败", str(e)[:100])
        mode_switch.currentIndexChanged.connect(lambda _i: _switch_mode())

        if include_advanced_tools:
            lay.addWidget(QLabel("\n 桌面"))
            lay.addWidget(_open_btn("", "桌宠", "桌面悬浮窗，再点一次收起"))
        return ne, fs, net_chk, mode_box_holder

    mode_box_holder = {"widget": None}

    # ================= 各功能页 =================
    def build_usage(lay):
        ne, fs, net_chk, _ = build_interface(lay, include_advanced_tools=False)
        d._settings_name_edit = ne
        d._settings_font = fs
        d._settings_net = net_chk
        lay.addWidget(QLabel("\n 资料"))
        lay.addWidget(_open_btn("", "知识库", "导入和管理资料",
                                key="知识库"))
        lay.addWidget(QLabel("\n 通知"))
        notify_box = QComboBox()
        notify_box.addItems(["飞书", "企业微信", "钉钉", "关闭"])
        notify_box.setCurrentText(
            {"feishu": "飞书", "wecom": "企业微信",
             "dingtalk": "钉钉", "off": "关闭"}.get(
                str(trunk.config.get("notify_channel", "feishu")), "飞书"))
        lay.addWidget(notify_box)
        d._settings_notify = notify_box
        lay.addWidget(QLabel("\n 更新"))
        lay.addWidget(_open_btn("", "检查更新",
                                "检查新版本 / 回滚 / 更新历史"))

    def build_help(lay):
        lay.addWidget(QLabel(" 帮助与安全"))
        lay.addWidget(_open_btn("", "新手教程",
                                "3 分钟上手 + 兼容性 / 数据迁移 / 插件 API 速查"))
        lay.addWidget(_open_btn("", "安全中心",
                                "权限、网络事件和审计记录",
                                key="安全中心"))
        lay.addWidget(_open_btn("", "意见反馈", "给开发者留言"))
        lay.addWidget(_open_btn("", "首次设置向导",
                                "模型没配好时重新配置"))

    def build_tools(lay):
        lay.addWidget(QLabel(" 工具"))
        lay.addWidget(_open_btn("", "电脑控制",
                                "操作软件 / 文件 / 窗口 / 系统"))
        lay.addWidget(_open_btn("", "机器人",
                                "企业微信 / 钉钉聊天机器人"))
        lay.addWidget(_open_btn("", "语音对话",
                                "实时语音对话：静音断句、可随时打断"))
        lay.addWidget(_open_btn("", "日历待办", "日历 + 待办 + 笔记"))
        lay.addWidget(_open_btn("", "命令面板 (Ctrl+K)",
                                "一个搜索框找所有能力和面板"))
        lay.addWidget(_open_btn("", "模块星图",
                                "全部模块的星型拓扑图"))

    def build_extensions(lay):
        lay.addWidget(QLabel(" 扩展"))
        lay.addWidget(_open_btn("", "插件", "安装 / 卸载 / 热加载模块",
                                key="插件市场"))
        lay.addWidget(_open_btn("", "MCP",
                                "服务器管理 / 预置服务器 / 配置参考",
                                key="MCP市场"))
        lay.addWidget(_open_btn("", "可选组件",
                                "语音识别 / 看图 / 浏览器自动化 / 一键安装"))

    def build_records(lay):
        lay.addWidget(QLabel(" 记录"))
        lay.addWidget(_open_btn("", "历史记录",
                                "分页 / 搜索 / 导出全部聊天记录"))
        lay.addWidget(_open_btn("", "日志", "运行日志 / 错误 / 操作记录",
                                key="日志中心"))
        lay.addWidget(_open_btn("", "搜索聊天", "全局搜索所有会话"))
        lay.addWidget(_open_btn("", "记忆可视化",
                                "记忆时间线 / 图谱 / 搜索 / 编辑"))
        lay.addWidget(_open_btn("", "数据统计", "用量与数据统计报表"))

    def build_system(lay):
        lay.addWidget(QLabel(" 系统"))
        lay.addWidget(_open_btn("", "系统", "深度自检 / 备份 / 训练",
                                key="系统自检"))
        lay.addWidget(_open_btn("", "首次设置向导",
                                "模型没配好、它不回话时打开这个"))
        lay.addWidget(_open_btn("", "新手教程",
                                "激活 / 配模型 / 聊天 / 兼容性与迁移速查"))
        lay.addWidget(_open_btn("", "检查更新",
                                "检查新版本 / 回滚 / 更新历史"))
        lay.addWidget(_open_btn("", "意见反馈", "给开发者留言"))
        lay.addWidget(QLabel("\n 开发者"))
        lay.addWidget(_open_btn("", "命令面板 (Ctrl+K)",
                                "搜索所有能力和面板"))
        lay.addWidget(_open_btn("", "模块星图", "模块拓扑图"))
        lay.addWidget(_open_btn("", "日志", "运行日志与错误",
                                key="日志中心"))

    tabs = QTabWidget()

    def build_start(lay):
        mb = build_model(lay)
        mode_box_holder["widget"] = mb

    if simple:
        tabs.addTab(_scroll_tab("开始", build_start), " 开始")
        tabs.addTab(_scroll_tab("使用", build_usage), " 使用")
        tabs.addTab(_scroll_tab("帮助", build_help), " 帮助")
    else:
        tabs.addTab(_scroll_tab("模型", lambda lay: build_model(lay)), " 模型")
        tabs.addTab(_scroll_tab("界面", build_usage), " 界面")
        tabs.addTab(_scroll_tab("工具", build_tools), " 工具")
        tabs.addTab(_scroll_tab("扩展", build_extensions), " 扩展")
        tabs.addTab(_scroll_tab("记录", build_records), " 记录")
        tabs.addTab(_scroll_tab("系统", build_system), " 系统")
        tabs.addTab(_scroll_tab("开发者", build_system), " 开发者")

    # 设置搜索：按标签页内可见文字查找，命中后切到对应页并聚焦控件。
    search_row = QHBoxLayout()
    search_box = QLineEdit()
    search_box.setPlaceholderText("搜索设置：主题、模型、日志、快捷键")
    search_box.setClearButtonEnabled(True)
    search_result = QLabel("")
    search_result.setStyleSheet("color:#667085;font-size:12px;")
    search_row.addWidget(search_box, 1)
    search_row.addWidget(search_result)
    l.addLayout(search_row)
    l.addWidget(tabs)

    def _search_settings():
        q = search_box.text().strip().lower()
        if not q:
            search_result.setText("")
            return
        for i in range(tabs.count()):
            page = tabs.widget(i)
            tab_text = tabs.tabText(i)
            if q in tab_text.lower():
                tabs.setCurrentIndex(i)
                search_result.setText("已定位标签页：" + tab_text)
                return
            for child in page.findChildren(QWidget):
                text = ""
                try:
                    text = str(child.text())
                except Exception:  # 静默是故意的
                    try:
                        text = str(child.currentText())
                    except Exception:  # 静默是故意的
                        text = ""
                if text and q in text.lower():
                    tabs.setCurrentIndex(i)
                    try:
                        child.setFocus()
                    except Exception:  # 静默是故意的
                        pass
                    search_result.setText("已定位：" + text[:40])
                    return
        search_result.setText("没有找到匹配的设置项")

    search_box.returnPressed.connect(_search_settings)
    search_box.textChanged.connect(
        lambda t: _search_settings() if len(t.strip()) >= 2 else None)

    # ================= 保存 =================
    def _safe_set_model_ui(mode_text):
        # 之前这里**无条件**把云端灯设成绿色，导致选本地时云端也亮。
        # 现在统一交给 gui.status_lights.paint 处理。
        try:
            from gui.status_lights import paint
            paint(mode_text, local_light, cloud_light, model_btn, parent.model_status_label)
        except Exception as e:
            _x6_swallowed(__name__, e)

    def do_save():
        try:
            mb = mode_box_holder.get("widget")
            if mb is not None:
                trunk.config["model_mode"] = mb.currentText()
            if getattr(d, "_settings_name_edit", None) is not None:
                trunk.config["ai_name"] = d._settings_name_edit.text()
            if getattr(d, "_settings_font", None) is not None:
                trunk.config["font_size"] = d._settings_font.currentText()
                try:
                    size = int(d._settings_font.currentText().replace("px", ""))
                    if chat is not None:
                        chat.setStyleSheet("font-size:%dpx;" % size)
                    if input_box is not None:
                        input_box.setStyleSheet(
                            "font-size:%dpx;border:none;background:transparent;"
                            % size)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            if getattr(d, "_settings_theme", None) is not None:
                from gui.theme_manager import (
                    THEME_LABELS, DENSITY_LABELS, ThemeManager)
                inv_theme = {v: k for k, v in THEME_LABELS.items()}
                inv_density = {v: k for k, v in DENSITY_LABELS.items()}
                tm = ThemeManager(base)
                tm.set_options(
                    theme=inv_theme.get(d._settings_theme.currentText(), "system"),
                    density=inv_density.get(
                        d._settings_density.currentText(), "comfortable"),
                    font_size=int(d._settings_font.currentText().replace("px", ""))
                    if getattr(d, "_settings_font", None) is not None else 14)
                if parent is not None and hasattr(parent, "theme_manager"):
                    parent.theme_manager = tm
                    tm.apply_to(parent)
            if getattr(d, "_settings_shortcut", None) is not None:
                sc_text = d._settings_shortcut.text().strip() or "Ctrl+K"
                trunk.config["shortcut_command_palette"] = sc_text
                if parent is not None and hasattr(
                        parent, "_set_command_palette_shortcut"):
                    parent._set_command_palette_shortcut(sc_text)
            if getattr(d, "_settings_net", None) is not None:
                trunk.config["联网"] = d._settings_net.isChecked()
            if getattr(d, "_settings_notify", None) is not None:
                trunk.config["notify_channel"] = {
                    "飞书": "feishu", "企业微信": "wecom",
                    "钉钉": "dingtalk", "关闭": "off"}.get(
                        d._settings_notify.currentText(), "feishu")
            trunk.save_config()
            try:
                trunk.modules["llm"].reload_config()
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            _safe_set_model_ui(trunk.config.get("model_mode", "本地路由"))
            try:
                parent.model_status_label.setText(
                    "模型：%s" % trunk.config.get("model_mode", "本地路由"))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            QMessageBox.information(d, "成功", "已保存")
        except Exception as e:
            QMessageBox.warning(d, "保存失败", str(e)[:120])

    l.addWidget(QPushButton("保存", clicked=do_save))
    d.exec_()
    return d
