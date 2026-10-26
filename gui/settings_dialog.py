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

from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QMessageBox, QInputDialog, QTabWidget, QWidget,
    QScrollArea,
)
from gui.settings_model_page import build_model_page
from gui.settings_widgets import (
    make_category_nav, make_hint, make_open_link, make_scroll_tab, make_tab,
)
from gui.feedback_states import make_action_links


def show_settings_dialog(parent, dlg, trunk, base, ai_name,
                         model_btn, local_light, cloud_light, chat, input_box,
                         commands=None):
    """设置窗口。

    commands: {名称: 可调用}，由主窗口传入；缺入口时按钮置灰并说明。
    """
    d, l = dlg("设置", 680, 700)
    if parent is not None:
        # 让主窗口的 set_dialog() 能复用正在打开的设置窗口
        parent._settings_dialog = d
    CMD = commands or {}
    simple = True
    try:
        from gui.ui_mode import get_ui_mode
        simple = get_ui_mode(base, getattr(trunk, "config", {})) == "simple"
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass

    def _open_link(icon, name, desc, key=None):
        return make_open_link(d, CMD, icon, name, desc, key)

    def _hint(text):
        return make_hint(text)

    def _tab(title):
        return make_tab(title)

    def _scroll_tab(title, build):
        return make_scroll_tab(title, build)

    # ================= 通用：模型配置 =================
    def build_model(lay):
        # 具体控件在 gui/settings_model_page.py（本文件接近 600 行上限）
        return build_model_page(d, trunk, parent, lay, _hint)
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

        lay.addWidget(make_action_links([("改名", _rename)]))

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
        lay.addWidget(make_action_links([("编辑 AI 人格", _edit_persona)]))

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
            lay.addWidget(_open_link("", "桌宠", "桌面悬浮窗，再点一次收起"))
        return ne, fs, net_chk, mode_box_holder

    mode_box_holder = {"widget": None}

    # ================= 各功能页 =================
    def build_usage(lay):
        ne, fs, net_chk, _ = build_interface(lay, include_advanced_tools=False)
        d._settings_name_edit = ne
        d._settings_font = fs
        d._settings_net = net_chk
        lay.addWidget(QLabel("\n 资料"))
        lay.addWidget(_open_link("", "知识库", "导入和管理资料",
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
        lay.addWidget(_open_link("", "检查更新",
                                "检查新版本 / 回滚 / 更新历史"))

    def build_help(lay):
        lay.addWidget(QLabel(" 帮助与安全"))
        lay.addWidget(_open_link("", "新手教程",
                                "3 分钟上手 + 兼容性 / 数据迁移 / 插件 API 速查"))
        lay.addWidget(_open_link("", "安全中心",
                                "权限、网络事件和审计记录",
                                key="安全中心"))
        lay.addWidget(_open_link("", "意见反馈", "给开发者留言"))
        lay.addWidget(_open_link("", "首次设置向导",
                                "模型没配好时重新配置"))

    def build_tools(lay):
        lay.addWidget(QLabel(" 工具"))
        lay.addWidget(_open_link("", "电脑控制",
                                "操作软件 / 文件 / 窗口 / 系统"))
        lay.addWidget(_open_link("", "机器人",
                                "企业微信 / 钉钉聊天机器人"))
        lay.addWidget(_open_link("", "语音对话",
                                "实时语音对话：静音断句、可随时打断"))
        lay.addWidget(_open_link("", "日历待办", "日历 + 待办 + 笔记"))

    def build_extensions(lay):
        lay.addWidget(QLabel(" 扩展"))
        lay.addWidget(_open_link("", "插件", "安装 / 卸载 / 热加载模块",
                                key="插件市场"))
        lay.addWidget(_open_link("", "MCP",
                                "服务器管理 / 预置服务器 / 配置参考",
                                key="MCP市场"))
        lay.addWidget(_open_link("", "可选组件",
                                "语音识别 / 看图 / 浏览器自动化 / 一键安装"))

    def build_records(lay):
        lay.addWidget(QLabel(" 记录"))
        lay.addWidget(_open_link("", "历史记录",
                                "分页 / 搜索 / 导出全部聊天记录"))
        lay.addWidget(_open_link("", "日志", "运行日志 / 错误 / 操作记录",
                                key="日志中心"))
        lay.addWidget(_open_link("", "搜索聊天", "全局搜索所有会话"))
        lay.addWidget(_open_link("", "记忆可视化",
                                "记忆时间线 / 图谱 / 搜索 / 编辑"))
        lay.addWidget(_open_link("", "数据统计", "用量与数据统计报表"))

    def build_system(lay):
        lay.addWidget(QLabel(" 系统"))
        lay.addWidget(_open_link("", "系统", "深度自检 / 备份 / 训练",
                                key="系统自检"))
        lay.addWidget(_open_link("", "首次设置向导",
                                "模型没配好、它不回话时打开这个"))
        lay.addWidget(_open_link("", "新手教程",
                                "激活 / 配模型 / 聊天 / 兼容性与迁移速查"))
        lay.addWidget(_open_link("", "意见反馈", "给开发者留言"))

    def build_developer(lay):
        lay.addWidget(QLabel(" 开发者"))
        lay.addWidget(_open_link("", "命令面板 (Ctrl+K)",
                                "搜索所有能力和面板"))
        lay.addWidget(_open_link("", "模块星图", "模块拓扑图"))

    tabs = QTabWidget()
    # 左侧分类 + 右侧内容：QTabWidget 继续当页面容器（搜索和测试都依赖
    # tabText/currentIndex），只隐藏自带标签条，用旁边的列表承担导航。
    tabs.setDocumentMode(True)
    tabs.tabBar().setVisible(False)

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
        tabs.addTab(_scroll_tab("开发者", build_developer), " 开发者")

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
    # 左侧分类导航：条目直接取 tabText，搜索框切页时这里同步高亮。
    category = make_category_nav(tabs)
    body_row = QHBoxLayout()
    body_row.setSpacing(10)
    body_row.addWidget(category)
    body_row.addWidget(tabs, 1)
    l.addLayout(body_row, 1)

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
