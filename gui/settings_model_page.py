# -*- coding: utf-8 -*-
"""设置窗口的「模型配置」页。

从 gui/settings_dialog.py 原样搬出（该文件接近 600 行上限）。
只搬代码不改行为：内部逻辑与原来逐行一致，唯一变化是把闭包变量
(d / trunk / parent / lay / hint) 改成显式参数。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import threading
import urllib.request

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QListWidget, QMessageBox,
)
from core.safe_http import open_url as safe_open_url
from gui.feedback_states import make_action_links


def build_model_page(d, trunk, parent, lay, hint):
    """在 lay 里构建模型配置控件，返回模型模式下拉框。"""
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
    lay.addWidget(hint(
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
        pl.addWidget(QLabel(
            "检测到 %d 个模型（双击或回车选中，Esc 取消）：" % len(models)))
        # 不再给每个模型造一个按钮：模型多的时候那是一屏按钮。
        lst = QListWidget()
        lst.addItems([str(m) for m in models])
        pl.addWidget(lst)

        def _pick(item=None):
            cur = item if item is not None else lst.currentItem()
            mm = cur.text() if cur is not None else ""
            if not mm:
                return
            trunk.config["local_model"] = mm
            trunk.save_config()
            ollama_lbl.setText(" 已选择本地模型：%s" % mm)
            pick.accept()

        lst.itemDoubleClicked.connect(_pick)
        lst.itemActivated.connect(_pick)      # 回车
        if models:
            lst.setCurrentRow(0)
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

        实现在 core/lan_trust.py。
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

    def cloud_set():
        from gui.cloud_provider_dialog import configure_cloud_provider
        configure_cloud_provider(d, trunk)

    lay.addWidget(make_action_links([("配置云端模型", cloud_set)]))
    lay.addWidget(QLabel(
        "本地：先安装 Ollama；云端：填 API 地址和 Key。"))
    return mode_box
