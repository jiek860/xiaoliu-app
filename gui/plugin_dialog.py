# -*- coding: utf-8 -*-
"""插件市场窗口 - 网格卡片/安装/卸载/热加载"""
import os, sys, importlib
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame,
                             QGridLayout, QMessageBox, QFileDialog,
                             QProgressDialog)


def show_plugin_dialog(parent, dlg, trunk, open_mcp, show_components):
    """插件市场窗口

    open_mcp: 打开 MCP 总面板的回调（就是主窗口的 mcp_dialog）。
              以前这里传的是另一个只显示 JSON 的窗口。
    """
    d, l = dlg("🧩 插件市场", w=880, h=700)
    pm = trunk._load_lazy("plugin_market")
    if not pm:
        QMessageBox.information(d, "插件市场", "插件市场模块加载失败")
        return

    head = QHBoxLayout()
    status = QLabel("🧩 正在扫描模块...")
    status.setStyleSheet("font-weight:bold;color:#1e40af;font-size:13px;")
    head.addWidget(status, stretch=1)
    refresh_btn = QPushButton("🔄 刷新")
    refresh_btn.setStyleSheet("padding:6px 14px;")
    head.addWidget(refresh_btn)
    file_btn = QPushButton("📥 安装 .py 文件")
    file_btn.setStyleSheet("padding:6px 14px;")
    head.addWidget(file_btn)
    mcp_btn = QPushButton("🔌 MCP")
    mcp_btn.setToolTip("打开 MCP 总面板（服务器管理 / 预置服务器 / 配置参考）")
    mcp_btn.setStyleSheet("padding:6px 14px;")
    mcp_btn.clicked.connect(open_mcp)
    head.addWidget(mcp_btn)
    opt_btn = QPushButton("🧩 可选组件")
    opt_btn.setToolTip("安装语音识别/浏览器自动化等重功能")
    opt_btn.setStyleSheet("padding:6px 14px;")
    opt_btn.clicked.connect(show_components)
    head.addWidget(opt_btn)
    l.addLayout(head)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    card_host = QWidget()
    grid = QGridLayout(card_host)
    grid.setSpacing(10)
    grid.setContentsMargins(8, 8, 8, 8)
    scroll.setWidget(card_host)
    l.addWidget(scroll, stretch=1)

    msg = QLabel("")
    msg.setWordWrap(True)
    msg.setStyleSheet("color:#475569;")
    l.addWidget(msg)

    def _clear_grid():
        while grid.count():
            it = grid.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()

    def _card(m):
        card = QFrame()
        card.setObjectName("pmcard")
        if m["installed"]:
            card.setStyleSheet("#pmcard { background:#f0fdf4; border:2px solid #22c55e; border-radius:12px; }"
                               "#pmcard:hover { border:2px solid #16a34a; }")
        else:
            card.setStyleSheet("#pmcard { background:#fefce8; border:1px dashed #ca8a04; border-radius:12px; }"
                               "#pmcard:hover { border:1px solid #eab308; }")
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(6)
        top = QHBoxLayout()
        icon = QLabel(m.get("icon", "🧩"))
        icon.setStyleSheet("font-size:26px;")
        top.addWidget(icon)
        top.addStretch(1)
        st = QLabel("✅" if m["installed"] else "⬜")
        st.setStyleSheet("font-size:15px;")
        top.addWidget(st)
        v.addLayout(top)
        nm = QLabel(m.get("file") or m["name"])
        nm.setStyleSheet("font-weight:bold;font-size:13px;color:#0f172a;")
        nm.setWordWrap(True)
        v.addWidget(nm)
        desc = QLabel(m.get("desc", "") or m["file"])
        desc.setStyleSheet("color:#64748b;font-size:11px;")
        desc.setWordWrap(True)
        desc.setMaximumHeight(34)
        v.addWidget(desc)
        meta = QLabel("%s · %dKB" % (m["file"], m.get("size", 0)))
        meta.setStyleSheet("color:#94a3b8;font-size:10px;")
        v.addWidget(meta)
        if m["installed"]:
            b = QPushButton("🗑 卸载")
            b.setStyleSheet("background:#fee2e2;color:#b91c1c;border:none;border-radius:6px;padding:5px;")
            def _make_un(mm):
                def _un():
                    b.setEnabled(False)
                    pg = QProgressDialog("正在卸载 %s ..." % mm.get("file", ""), None, 0, 0, d)
                    pg.setWindowTitle("卸载中")
                    pg.setMinimumDuration(0)
                    pg.setModal(True)
                    pg.show()
                    d.processEvents()
                    try:
                        r = pm.uninstall(mm["name"])
                        msg.setText(("✅ " if r.get("ok") else "❌ ") + str(r.get("msg") or r.get("原因") or r))
                    except Exception as e:
                        msg.setText("❌ " + str(e)[:60])
                    pg.close()
                    _refresh()
                return _un
            b.clicked.connect(_make_un(m))
        else:
            b = QPushButton("⬇ 在线下载")
            b.setStyleSheet("background:#4a9eff;color:#fff;border:none;border-radius:6px;padding:5px;")
            def _make_ins(mm):
                def _ins():
                    b.setEnabled(False)
                    pg = QProgressDialog("正在下载安装 %s ..." % mm.get("file", ""), None, 0, 0, d)
                    pg.setWindowTitle("下载安装中")
                    pg.setMinimumDuration(0)
                    pg.setModal(True)
                    pg.show()
                    d.processEvents()
                    try:
                        r = pm.download(mm["file"], mm)
                        if r.get("ok"):
                            r2 = pm.install(mm["name"])
                            if not r2.get("ok"):
                                r = r2
                        msg.setText(("✅ " if r.get("ok") else "❌ ") + str(r.get("msg") or r.get("原因") or r))
                    except Exception as e:
                        msg.setText("❌ " + str(e)[:60])
                    pg.close()
                    _refresh()
                return _ins
            b.clicked.connect(_make_ins(m))
        v.addWidget(b)
        return card

    def _refresh():
        try:
            if "core.lazy_config" in sys.modules:
                importlib.reload(sys.modules["core.lazy_config"])
            mods = []
            try:
                online = pm.list_online()
                local_files = set()
                for fn in os.listdir(pm.installed_dir):
                    if fn.endswith(".py"):
                        local_files.add(fn)
                for o in online:
                    installed = o.get("file", "") in local_files
                    mods.append({"name": o.get("name", "?"), "file": o.get("file", "?"), "cls": "?",
                                 "installed": installed, "active": installed, "desc": o.get("desc", ""),
                                 "size": o.get("size", 0), "icon": "🧩" if not installed else "✅",
                                 # 带上校验信息，下载时用于验签
                                 "sha256": o.get("sha256", ""), "signature": o.get("signature", "")})
                msg.setText("在线 %d 个模块" % len(online))
            except Exception as ee:
                msg.setText("在线拉取失败: " + str(ee)[:80])
            _clear_grid()
            cols = 4
            for idx, m in enumerate(mods):
                grid.addWidget(_card(m), idx // cols, idx % cols)
            grid.setRowStretch((len(mods) - 1) // cols + 1, 1)
            st = pm.stats()
            status.setText("🧩 模块 %d 个 · ✅已装 %d · ⬜可装 %d · %.0f KB" % (
                st["模块总数"], st["已安装"], st["可安装"], st["总大小KB"]))
            msg.setText("点击卡片按钮 安装/卸载 · 安装自动语法校验+加载验证，失败自动回滚")
        except Exception as e:
            status.setText("❌ 扫描失败: " + str(e)[:60])

    def _pick_file():
        path, _ = QFileDialog.getOpenFileName(d, "选择插件 .py", "", "Python 文件 (*.py)")
        if not path:
            return
        try:
            r = pm.install_file(path)
            msg.setText(("✅ " if r.get("ok") else "❌ ") + str(r.get("msg") or r.get("原因") or r))
        except Exception as e:
            msg.setText("❌ " + str(e)[:60])
        _refresh()
    file_btn.clicked.connect(_pick_file)
    refresh_btn.clicked.connect(_refresh)
    _refresh()
    d.exec_()
