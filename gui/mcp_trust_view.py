# -*- coding: utf-8 -*-
"""MCP 信任管理面板（从 mcp_dialog.py 拆出，避免单文件超 600 行）。

职责：展示哪些 MCP 启动命令已被永久信任，支持一键全部信任 / 撤销全部。

⚠️ 关键约束：**绝不能**在构造期同步调用 trunk._load_lazy("mcp_client")。
   那会真的去连接 4 个 MCP 服务器，实测卡 120 秒，整个界面冻死。
   所以这里一律走后台线程，加载完再回主线程刷新表格。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None


class MCPTrustPanel(QWidget):
    """信任管理页。构造时不碰 mcp_client，用户点「刷新」才加载。"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self._bg_worker = None
        lay = QVBoxLayout(self)

        tip = QLabel(
            "MCP 服务器每次启动都会请求确认。点过「永久允许」后不再弹窗。\n"
            "⚠️ 如果命令内容变了（例如改了参数或版本），哈希随之改变，会重新询问 —— "
            "这是防止命令被偷偷替换的安全设计。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#667085;font-size:12px;padding:4px;")
        lay.addWidget(tip)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["服务器", "命令", "状态", "哈希"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        lay.addWidget(self.table, stretch=1)

        self.status = QLabel("点「刷新」读取信任状态（首次加载 MCP 客户端需要几秒）")
        self.status.setStyleSheet("color:#667085;font-size:12px;")
        lay.addWidget(self.status)

        row = QHBoxLayout()
        # 「刷新」按钮已去掉：面板显示时自动刷新（见 show 时调用），
        # 且两个操作完成后都会自动刷新。
        row.addWidget(QPushButton("全部永久信任（不再弹窗）",
                                  clicked=self.trust_all))
        row.addWidget(QPushButton("撤销全部信任", clicked=self.revoke_all))
        row.addStretch(1)
        lay.addLayout(row)

    # ------------------------------------------------------------ 客户端获取
    def _client(self):
        """只在已有实例时返回；没有则返回 None（由 refresh 后台加载）。"""
        try:
            return (getattr(self.trunk, "modules", {}) or {}).get("mcp_client")
        except Exception:  # 静默是故意的
            return None

    def _load_client_blocking(self):
        """在后台线程里真正加载 mcp_client（本方法不在 UI 线程执行）。"""
        return self.trunk._load_lazy("mcp_client")

    def _load_in_background(self):
        self.status.setText("正在后台加载 MCP 客户端…")
        try:
            from gui.workers import BgWorker
            worker = BgWorker(self._load_client_blocking)
            worker.done.connect(self._on_loaded)
            self._bg_worker = worker     # 持有引用，避免被 GC
            worker.start()
        except Exception as e:  # 静默是故意的 - 加载失败也要给出可操作提示
            _x6_swallowed(__name__, e, "best-effort fallback")
            self.status.setText("MCP 客户端加载失败；可直接点「全部永久信任」")

    def _on_loaded(self, _result):
        """后台加载完成 → 回主线程刷新表格。"""
        self.refresh()

    # ------------------------------------------------------------ 刷新
    def refresh(self):
        client = self._client()
        if client is None:
            self._load_in_background()
            return
        self.table.setRowCount(0)
        if not hasattr(client, "trust_report"):
            self.status.setText("当前 mcp_client 版本不支持信任管理")
            return
        try:
            rep = client.trust_report()
            rows = rep.get("servers") or []
        except Exception as e:  # 静默是故意的 - 读失败只提示
            _x6_swallowed(__name__, e, "best-effort fallback")
            self.status.setText("读取失败: %s" % str(e)[:80])
            return
        if not rows:
            # mcp_client 尚未连接服务器时 servers 可能为空，
            # 此时直接读配置，保证表格与真实信任状态一致。
            rows = _rows_from_config(self.trunk)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("name") or "")))
            self.table.setItem(i, 1, QTableWidgetItem(str(r.get("command") or "")))
            item = QTableWidgetItem("✅ 已信任" if r.get("trusted")
                                    else "⏳ 每次询问")
            item.setForeground(Qt.darkGreen if r.get("trusted") else Qt.darkYellow)
            self.table.setItem(i, 2, item)
            self.table.setItem(i, 3, QTableWidgetItem(str(r.get("hash") or "")))
        self.table.resizeColumnsToContents()
        self.status.setText("共 %d 个 stdio 服务器，已永久信任 %d 个"
                            % (len(rows), sum(1 for r in rows if r.get("trusted"))))

    # ------------------------------------------------------------ 操作
    def trust_all(self):
        ans = QMessageBox.question(
            self, "全部永久信任",
            "将把当前所有 MCP 启动命令记入信任列表，以后不再询问。\n\n"
            "请确认这些命令都是你自己要用的。确定继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        client = self._client()
        if client is None:
            # 没有实例也能写信任：直接读配置里的命令
            r = _trust_all_from_config(self.trunk)
        else:
            r = client.trust_all_servers()
        if r.get("ok"):
            QMessageBox.information(
                self, "完成",
                "已永久信任 %s 个服务器。\n下次启动不再弹窗。" % r.get("已信任"))
        else:
            QMessageBox.warning(self, "失败", str(r.get("原因") or "未知错误"))
        self.refresh()

    def revoke_all(self):
        ans = QMessageBox.question(
            self, "撤销全部信任",
            "撤销后，下次启动所有 MCP 服务器都会重新询问。继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        client = self._client()
        if client is not None:
            client.revoke_trust(None)
        else:
            from core.mcp_trust import trust_path
            import os
            p = trust_path(getattr(self.trunk, "base", "."))
            if os.path.exists(p):
                os.remove(p)
        self.refresh()


def _rows_from_config(trunk):
    """不依赖 mcp_client 已连接，直接从配置+信任库生成表格行。"""
    from core.mcp_sandbox import startup_manifest
    from core.mcp_trust import load_trusted
    base = getattr(trunk, "base", ".")
    try:
        servers = (getattr(trunk, "config", {}) or {}).get("mcp_servers") or []
    except Exception:  # 静默是故意的
        servers = []
    trusted = load_trusted(base)
    rows = []
    for srv in servers:
        if not srv.get("command"):
            continue
        try:
            m = startup_manifest(dict(srv, cwd=srv.get("cwd")))
        except Exception:  # 静默是故意的
            continue
        h = m["command_sha256"]
        rows.append({"name": srv.get("name"), "command": m["command"],
                     "hash": h, "trusted": h in trusted,
                     "reason": "已永久信任" if h in trusted else "首次启动需确认"})
    return rows


def _trust_all_from_config(trunk):
    """不加载 mcp_client 也能写入信任（避免为了授权反而去连服务器）。"""
    from core.mcp_sandbox import startup_manifest
    from core.mcp_trust import load_trusted, save_trusted
    base = getattr(trunk, "base", ".")
    try:
        servers = (getattr(trunk, "config", {}) or {}).get("mcp_servers") or []
    except Exception:  # 静默是故意的
        servers = []
    hashes = []
    for srv in servers:
        if not srv.get("command"):
            continue
        try:
            hashes.append(startup_manifest(dict(srv, cwd=srv.get("cwd")))
                          ["command_sha256"])
        except Exception:  # 静默是故意的
            continue
    if not hashes:
        return {"ok": False, "原因": "配置里没有 stdio 服务器"}
    ok, err = save_trusted(base, load_trusted(base) | set(hashes))
    if not ok:
        return {"ok": False, "原因": err}
    return {"ok": True, "已信任": len(hashes)}
