# -*- coding: utf-8 -*-
"""插件市场窗口 - 网格卡片/安装/卸载/热加载"""
import os, sys, importlib, threading
from core.plugin_capabilities import plugin_manifest_info
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget, QFrame, QGridLayout, QMessageBox, QFileDialog, QProgressDialog, QApplication
from PyQt5.QtCore import QObject, pyqtSignal

from gui.feedback_states import make_action_links

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


class _OnlineSignals(QObject):
    """把后台取在线清单的结果送回主线程（Qt 控件只能主线程碰）"""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


def merge_mods(local_mods, online):
    """本地清单 + 在线清单取并集。

    以前在线清单一回来就整块替换网格：本地装了但不在在线清单里的模块
    会从界面上消失（用户既看不到也卸不掉）。现在两边合并，本地那份为准。
    """
    by_file = {}
    for m in local_mods or []:
        item = dict(m)
        item["online"] = bool(item.get("online"))
        by_file[item.get("file") or item.get("name") or "?"] = item
    for o in online or []:
        f = o.get("file") or o.get("name") or "?"
        try:
            meta = plugin_manifest_info(o) or {}
        except Exception as e:
            # 静默是故意的：在线清单里的条目没有清单文件属于正常情况，
            # 缺元信息只是少显示几行，不该让整个合并失败。
            _x6_swallowed(__name__, e, "plugin manifest info")
            meta = {}
        cur = by_file.get(f)
        if cur is not None:
            # 在线清单负责补充校验/版本/描述信息；installed/active 以本地为准。
            for k in ("desc", "sha256", "signature"):
                if o.get(k):
                    cur[k] = o[k]
            if o.get("size"):
                cur["size"] = o["size"]
            for k, v in meta.items():
                if v not in (None, "", [], {}):
                    cur[k] = v
            cur["online"] = True
            continue
        item = {"name": o.get("name", "?"), "file": f, "cls": "?",
                "installed": False, "active": False,
                "desc": o.get("desc", ""), "size": o.get("size", 0),
                "icon": "🧩", "sha256": o.get("sha256", ""),
                "signature": o.get("signature", ""), "online": True}
        item.update(meta)
        by_file[f] = item
    return list(by_file.values())


def show_plugin_dialog(parent, dlg, trunk, open_mcp=None, show_components=None):
    """插件市场窗口

    open_mcp / show_components 保留成可选参数，只为兼容旧调用与构造测试。
    这两个按钮已按需求从这里移除：
        MCP      -> 设置 -> 扩展 -> MCP
        可选组件 -> 设置 -> 系统 -> 可选组件
    """
    d, l = dlg("🧩 插件市场", w=880, h=700)

    # 加载 plugin_market 会扫描模块目录 + 读清单，实测慢。
    # 这里先不重复加载：主窗口启动时已经加载过就在 modules 里，
    # 没有才去加载（只有第一次打开才会走这条路）。
    pm = getattr(trunk, "modules", {}).get("plugin_market")
    if pm is None:
        pm = trunk._load_lazy("plugin_market")
    if not pm:
        QMessageBox.information(d, "插件市场", "插件市场模块加载失败")
        return

    _build_market(d, l, trunk, pm, dlg, open_mcp, show_components)


def _build_market(d, l, trunk, pm, dlg, open_mcp=None, show_components=None):
    """真正构建插件市场界面（原 show_plugin_dialog 的主体）。"""

    head = QHBoxLayout()
    status = QLabel("🧩 正在扫描模块...")
    status.setStyleSheet("font-weight:bold;color:#1e40af;font-size:13px;")
    head.addWidget(status, stretch=1)
    # 三个低频动作做成链接：卡片本身已经有安装/卸载，头部不需要再堆按钮。
    head.addWidget(make_action_links([
        ("🔄 刷新", lambda: _refresh_all()),
        ("📥 安装 .py 文件", lambda: _pick_file()),
        ("⬆ 检查更新", lambda: _check_updates()),
    ]))
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

    # 后台取在线清单的结果通过信号回到主线程。
    # 以对话框为父对象并留一份引用 —— 只当局部变量的话，
    # 函数返回后可能被回收，后台线程 emit 就没人接了。
    sig = _OnlineSignals(d)
    d._online_sig = sig
    sig.failed.connect(lambda e: msg.setText("在线拉取失败: " + str(e)))

    def _clear_grid():
        while grid.count():
            it = grid.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()

    busy = set()            # 正在安装/卸载的文件名，防重复触发
    state = {"local": []}   # 上次本地扫描结果，在线清单回来时用来合并

    def _render(mods):
        _clear_grid()
        cols = 4
        for idx, m in enumerate(mods):
            grid.addWidget(_card(m), idx // cols, idx % cols)
        grid.setRowStretch((len(mods) - 1) // cols + 1, 1)

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
        cap_text = m.get("capability_summary") or "能力:未知（默认拒绝）"
        cap = QLabel(cap_text)
        cap.setWordWrap(True)
        cap.setStyleSheet("color:#7c3aed;font-size:10px;")
        v.addWidget(cap)
        pub = QLabel("发布者:%s  信任:%s  版本:%s  签名:%s  API:%s" % (
            m.get("publisher", "unknown"),
            m.get("trust_tier", "unknown"),
            m.get("version", "1.0.0"),
            m.get("signature_status", "unknown"),
            m.get("api_version", "legacy")))
        pub.setWordWrap(True)
        pub.setStyleSheet("color:#94a3b8;font-size:9px;")
        v.addWidget(pub)
        if m["installed"]:
            def _make_un(mm):
                def _un():
                    key = mm.get("file", "")
                    if key in busy:
                        return
                    busy.add(key)
                    pg = QProgressDialog("正在卸载 %s ..." % key, None, 0, 0, d)
                    pg.setWindowTitle("卸载中")
                    pg.setMinimumDuration(0)
                    pg.setModal(True)
                    pg.show()
                    # 必须是 QApplication.processEvents()。
                    # 原来写的是 d.processEvents()（d 是 QDialog）——
                    # 这一行必然抛 AttributeError，且它在 try 之外，
                    # 于是 uninstall() 根本不会执行 ——「卸载」点了没反应就是这个原因。
                    QApplication.processEvents()
                    try:
                        r = pm.uninstall(mm["name"])
                        msg.setText(("✅ " if r.get("ok") else "❌ ") + str(r.get("msg") or r.get("原因") or r))
                    except Exception as e:
                        msg.setText("❌ " + str(e)[:60])
                    finally:
                        busy.discard(key)
                    pg.close()
                    _refresh()
                return _un

            def _make_rb(mm):
                def _rb():
                    key = mm.get("file", "")
                    if key in busy:
                        return
                    busy.add(key)
                    try:
                        r = pm.rollback_module(mm["name"])
                        msg.setText(("✅ " if r.get("ok") else "❌ ")
                                    + str(r.get("msg") or r.get("原因") or r))
                    except Exception as e:
                        msg.setText("❌ " + str(e)[:60])
                    finally:
                        busy.discard(key)
                    _refresh()
                return _rb

            rowb = QHBoxLayout()
            rowb.addWidget(make_action_links([
                ("🗑 卸载", _make_un(m)),
                ("↩ 回滚", _make_rb(m)),
            ]))
            rowb.addStretch(1)
            v.addLayout(rowb)
        else:
            def _make_ins(mm):
                def _ins():
                    key = mm.get("file", "")
                    if key in busy:
                        return
                    risk = str(mm.get("risk_level") or "unknown").lower()
                    if risk in ("high", "unknown"):
                        answer = QMessageBox.question(
                            d, "高风险插件确认",
                            "插件: %s\n风险: %s\n%s\n\n是否继续安装？" % (
                                key or "?", risk,
                                mm.get("capability_summary", "能力未知，默认拒绝")),
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                        if answer != QMessageBox.Yes:
                            return
                    busy.add(key)
                    pg = QProgressDialog("正在下载安装 %s ..." % key, None, 0, 0, d)
                    pg.setWindowTitle("下载安装中")
                    pg.setMinimumDuration(0)
                    pg.setModal(True)
                    pg.show()
                    QApplication.processEvents()   # 同上：不是 d.processEvents()
                    try:
                        r = pm.download(mm["file"], mm)
                        if r.get("ok"):
                            r2 = pm.install(mm["name"])
                            if not r2.get("ok"):
                                r = r2
                        msg.setText(("✅ " if r.get("ok") else "❌ ") + str(r.get("msg") or r.get("原因") or r))
                    except Exception as e:
                        msg.setText("❌ " + str(e)[:60])
                    finally:
                        busy.discard(key)
                    pg.close()
                    _refresh()
                return _ins
            v.addWidget(make_action_links([("⬇ 安装", _make_ins(m))]))
        return card

    def _refresh():
        """先瞬时渲染一版，再后台去取在线清单。

        原来 `pm.list_online()` 是在这里同步调的 —— 它要发 HTTP 请求去
        仓库拿 manifest.json，网络不快时点开插件市场要先卡一秒左右窗口才出来。
        现在：本地那份立刻画出来，在线那份后台取，取回来再补上校验信息。
        """
        try:
            if "core.lazy_config" in sys.modules:
                importlib.reload(sys.modules["core.lazy_config"])
            mods = []
            try:
                local = pm.list_all()          # 只读本地文件，不联网
                for m in local:
                    mods.append({
                        "name": m.get("name", "?"), "file": m.get("file", "?"),
                        "cls": m.get("cls", "?"),
                        "installed": bool(m.get("installed")),
                        "active": bool(m.get("active")),
                        "desc": m.get("desc", ""), "size": m.get("size", 0),
                        "icon": m.get("icon", "🧩"),
                        "sha256": "", "signature": "",
                        "capability_summary": m.get("capability_summary"),
                        "risk_level": m.get("risk_level"),
                        "publisher": m.get("publisher"),
                        "signature_status": m.get("signature_status"),
                        "api_version": m.get("api_version"),
                    })
                msg.setText("本地 %d 个模块 · 正在获取在线清单…" % len(mods))
            except Exception as ee:
                msg.setText("本地扫描失败: " + str(ee)[:80])
            state["local"] = mods
            _render(mods)
            st = pm.stats()
            status.setText("🧩 模块 %d 个 · ✅已装 %d · ⬜可装 %d · %.0f KB" % (
                st["模块总数"], st["已安装"], st["可安装"], st["总大小KB"]))
            msg.setText("点击卡片 安装/卸载 · 安装自动语法校验+加载验证，失败自动回滚")
        except Exception as e:
            status.setText("❌ 扫描失败: " + str(e)[:60])

    def _fetch_online_async():
        """后台取在线清单，回来再刷新（不联网也能用，只是少了校验信息）"""
        def _work():
            try:
                online = pm.list_online()
            except Exception as ee:
                sig.failed.emit(str(ee)[:80])
                return
            sig.done.emit(online)

        threading.Thread(target=_work, daemon=True,
                         name="plugin-online-fetch").start()

    def _on_online_done(online):
        try:
            local = state.get("local") or []
            merged = merge_mods(local, online)
            if not local:
                # 本地扫描失败时至少把"已装"标对，否则会诱导重复安装。
                installed = {f for f in os.listdir(pm.installed_dir)
                             if f.endswith(".py")}
                for m in merged:
                    if m.get("file") in installed:
                        m["installed"] = True
                        m["active"] = True
                        m["icon"] = "✅"
            _render(merged)
            local_only = len(merged) - len(online or [])
            msg.setText("在线 %d 个 · 仅本地 %d 个 · 点击卡片 安装/卸载"
                        % (len(online or []), max(local_only, 0)))
        except Exception as e:
            msg.setText("在线列表刷新失败: " + str(e)[:70])

    def _refresh_all():
        _refresh()
        _fetch_online_async()

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
    def _check_updates():
        try:
            r = pm.check_updates()
            updates = r.get("updates") or []
            blocked = r.get("blocked") or []
            if updates:
                summary = "、".join(
                    "%s %s->%s" % (u["file"], u.get("current"),
                                   u["latest"].get("version"))
                    for u in updates[:6])
                answer = QMessageBox.question(
                    d, "插件更新", "发现兼容更新：\n%s\n\n是否全部更新？" % summary,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer == QMessageBox.Yes:
                    from core.plugin_installer import apply_update
                    results = []
                    for u in updates:
                        meta = dict(u.get("latest") or {})
                        meta["file"] = u.get("file")
                        results.append(apply_update(pm, meta))
                    ok = sum(1 for x in results if x.get("ok"))
                    msg.setText("更新完成: %d/%d" % (ok, len(results)))
                    _refresh()
                    return
                msg.setText("可更新: " + summary)
            elif blocked:
                msg.setText("有 %d 个新版本与当前宿主/API 不兼容" % len(blocked))
            else:
                msg.setText("没有可用更新")
        except Exception as e:
            msg.setText("检查更新失败: " + str(e)[:80])
    sig.done.connect(_on_online_done)
    _refresh()                 # 本地那份，瞬时
    _fetch_online_async()      # 在线那份，后台
    d.exec_()