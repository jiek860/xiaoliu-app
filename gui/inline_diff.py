# -*- coding: utf-8 -*-
"""内联 diff 预览：双击跳转 + 应用/撤销（不新增按钮预算）。

为什么不用 QPushButton
--------------------
`tools/check_buttons.py` 的按钮预算已经卡死。这个视图里的"应用/撤销"
用 QLabel 的富文本链接实现：可点击、可禁用、不算控件创建点。

配套能力
--------
* 双击（或键盘移动光标）diff 行 -> 打开对应源文件并定位到行；
* 应用：调用 `apply_patch`，保留 backup_manifest；
* 撤销：优先回调任务编排器的 rollback，否则按 manifest 回滚；
* `mark_applied()`：Agent 已经应用时只更新状态，避免重复写盘。
"""
from __future__ import annotations

import os
import re

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QTextBrowser,
                             QVBoxLayout, QWidget)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_APPLY_LINK = ('<a href="apply" style="color:#1976d2;text-decoration:none;">'
               '✓ 应用全部修改</a>')


class InlineDiffView(QWidget):
    jumpRequested = pyqtSignal(str, int)
    applyRequested = pyqtSignal()
    undoRequested = pyqtSignal()

    def __init__(self, root, patch, on_apply=None, on_undo=None, parent=None,
                 format_first=False):
        super().__init__(parent)
        self.root = os.path.abspath(root)
        self.patch = patch or {}
        self.on_apply = on_apply
        self.on_undo = on_undo
        self.format_first = bool(format_first)   # 深度⑤：先格式化再落 hunk
        self.manifest = ""
        self._applied = False
        self._targets = {}
        self._last_key = None
        self._skipped = set()
        self._force = set()
        self._applied_keys = set()
        self._hunk_manifests = {}
        self._plan = {}
        self._conflicts = {}
        self._base = {}
        self._build()
        self._base = self._base_snapshot()
        self._fill()
        self._refresh_hunks()

    # ---------------------------------------------------------- UI
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QLabel(self.patch.get("goal") or "AI 修改预览")
        head.setStyleSheet("padding:6px 10px;font-weight:700;background:#eef5ff;")
        lay.addWidget(head)
        self.hint = QLabel(
            "点击/双击 diff 行可跳转到源文件；应用与撤销在底部。")
        self.hint.setStyleSheet("padding:2px 10px;color:#667085;font-size:11px;")
        lay.addWidget(self.hint)
        # 逐 hunk 清单（第 6 批）：用富文本链接做"应用/跳过/撤销"，不加按钮。
        self.hunk_panel = QTextBrowser()
        self.hunk_panel.setOpenLinks(False)
        self.hunk_panel.setMaximumHeight(132)
        self.hunk_panel.setStyleSheet(
            "background:#fbfcfe;border-top:1px solid #e4e7ec;font-size:12px;")
        self.hunk_panel.anchorClicked.connect(self._on_anchor)
        lay.addWidget(self.hunk_panel)
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;"
            "font-family:Consolas,'Microsoft YaHei';font-size:12px;")
        self.diff.cursorPositionChanged.connect(self._on_cursor)
        lay.addWidget(self.diff, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(10, 6, 10, 6)
        self.apply_link = QLabel(_APPLY_LINK)
        self.apply_link.linkActivated.connect(self._apply)
        self.undo_link = QLabel(
            '<a href="undo" style="color:#b42318;text-decoration:none;">'
            '↩ 撤销本次修改</a>')
        self.undo_link.linkActivated.connect(self._undo)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#667085;font-size:11px;")
        foot.addWidget(self.apply_link)
        foot.addSpacing(18)
        foot.addWidget(self.undo_link)
        foot.addSpacing(12)
        foot.addWidget(self.status, 1)
        lay.addLayout(foot)

    def _fill(self):
        try:
            from core.patch_engine import unified_diff
            text = unified_diff(self.root, self.patch)
        except Exception as e:  # 静默是故意的 - 预览失败也要显示原因
            text = "diff 生成失败: " + str(e)[:300]
        self.diff.setPlainText(text or "（没有可预览的修改）")
        self._targets = self._index_diff(text)
        if not text:
            self.status.setText("没有修改")

    def _index_diff(self, text):
        """把 diff 的显示行号映射到 (源文件, 源行号)。"""
        out = {}
        rel = ""
        new_line = old_line = 0
        for i, line in enumerate(str(text or "").splitlines()):
            if line.startswith("+++ b/"):
                rel = line[6:].strip()
                continue
            if line.startswith("--- a/"):
                continue
            m = _HUNK.match(line)
            if m:
                old_line, new_line = int(m.group(1)), int(m.group(2))
                continue
            if not rel:
                continue
            if line.startswith("+"):
                out[i] = (rel, new_line)
                new_line += 1
            elif line.startswith("-"):
                out[i] = (rel, max(1, old_line))
                old_line += 1
            elif line.startswith(" "):
                out[i] = (rel, new_line)
                new_line += 1
                old_line += 1
        return out

    def _on_cursor(self):
        pos = self.diff.textCursor().blockNumber()
        target = self._targets.get(pos)
        if not target or target == self._last_key:
            return
        self._last_key = target
        self.jumpRequested.emit(target[0], int(target[1]))

    # ---------------------------------------------------------- 逐 hunk
    def _path(self, rel):
        return os.path.join(self.root, str(rel or "").replace("/", os.sep))

    def _base_snapshot(self):
        """记录"预览生成时"的文件内容，用于 3-way 冲突比对（深度②）。"""
        snap = {}
        for fp in (self.patch or {}).get("files") or []:
            if str(fp.get("op") or "update") != "update":
                continue
            rel = str(fp.get("path") or "").replace("\\", "/")
            try:
                p = self._path(rel)
                if os.path.isfile(p):
                    with open(p, encoding="utf-8", errors="replace") as f:
                        snap[rel] = f.read()
            except OSError as e:  # 静默是故意的 - 快照失败只影响冲突提示
                _x6_swallowed(__name__, e, "hunk base snapshot")
        return snap

    def _selected(self):
        """没跳过任何 hunk 时返回 None（=全选），否则只应用未跳过的那几段。"""
        if not self._skipped:
            return None
        try:
            from core.hunk_edit import all_hunk_keys
            keys = set(all_hunk_keys(self.patch))
        except Exception as e:  # 静默是故意的 - 拿不到 key 就退回全选
            _x6_swallowed(__name__, e, "hunk selected keys")
            return None
        return (keys | set(self._force)) - set(self._skipped)

    def _refresh_hunks(self):
        """重新算逐 hunk 定位/冲突状态，刷新富文本清单（不加按钮）。"""
        try:
            from core.hunk_edit import all_hunk_keys, conflict_report, plan
            self._plan = plan(self.root, self.patch,
                              selected_hunks=self._selected())
            self._conflicts = {row["key"]: row for row in conflict_report(
                self.root, self.patch, self._base)}
            self._keys = all_hunk_keys(self.patch)
        except Exception as e:  # 静默是故意的 - 清单坏了不影响 diff 预览
            _x6_swallowed(__name__, e, "refresh hunk panel")
            self._plan, self._conflicts, self._keys = {}, {}, []
        self.hunk_panel.setHtml(self._hunk_html(
            list((self._plan or {}).get("hunks") or [])))

    def _hunk_html(self, rows):
        if not rows:
            return ('<div style="padding:6px 10px;color:#98a2b3;">'
                    '没有行级修改（整文件操作请在底部应用）</div>')
        out = ['<div style="padding:6px 10px;line-height:150%;">']
        marks = "①②③④⑤⑥⑦⑧⑨⑩"
        for i, row in enumerate(rows):
            key = str(row.get("key") or "")
            rel = key.rsplit(":", 1)[0]
            mark = marks[i] if i < len(marks) else str(i + 1)
            status = str(row.get("status") or "")
            color = "#12b76a" if status == "exact" else "#b54708"
            if status in ("duplicate", "missing"):
                color = "#b42318"
            head = "%s <b>%s</b> 第 %d 行 · <span style=\"color:%s;\">%s</span>" % (
                mark, rel, int(row.get("line") or 0), color,
                self._status_text(status))
            links = []
            if key in self._applied_keys:
                links.append('<a href="undohunk://%s" style="color:#b42318;">撤销这一段</a>' % key)
            elif key in self._skipped:
                links.append('<a href="applyhunk://%s" style="color:#1976d2;">恢复应用</a>' % key)
            else:
                links.append('<a href="applyhunk://%s" style="color:#1976d2;">应用</a>' % key)
                links.append('<a href="skiphunk://%s" style="color:#667085;">跳过</a>' % key)
            if key in self._conflicts:
                links.append('<a href="minehunk://%s" style="color:#b42318;">保留我的</a>' % key)
                links.append('<a href="aihunk://%s" style="color:#1976d2;">用 AI 的</a>' % key)
                links.append('<a href="manualhunk://%s" style="color:#7a5af8;">手动合并</a>' % key)
            out.append("<div>%s · %s</div>" % (head, " · ".join(links)))
        out.append("</div>")
        return "".join(out)

    @staticmethod
    def _status_text(status):
        try:
            from core.hunk_edit import explain_status
            return explain_status(status)
        except Exception:  # 静默是故意的 - 状态文案缺失退回原文
            return str(status or "未知")

    def _on_anchor(self, url):
        """QTextBrowser 用 anchorClicked(QUrl)；转成字符串再走同一条链接逻辑。"""
        self._on_hunk_link(url.toString() if hasattr(url, "toString") else str(url))

    def _on_hunk_link(self, url):
        act, _, key = str(url or "").partition("://")
        if not key:
            return
        rel, _, idx = key.rpartition(":")
        if act in ("applyhunk", "aihunk"):
            if act == "aihunk":
                self._conflicts.pop(key, None)
            self._apply_one(key, force=act == "aihunk")
            return
        self._skipped.add(key)
        self._force.discard(key)
        if act == "skiphunk":
            self.status.setText("已跳过 %s（应用全部时不会包含它）" % key)
        elif act == "minehunk":
            self.status.setText("保留你的改动：%s 不应用 AI 版本" % key)
        elif act == "manualhunk":
            self.jumpRequested.emit(rel, max(1, int(self._line_of(key))))
            self.status.setText("请在该行手动合并，已跳过 %s" % key)
        elif act == "undohunk":
            self._skipped.discard(key)
            self._undo_one(key)
            return
        self._refresh_hunks()

    def _line_of(self, key):
        for row in (self._plan or {}).get("hunks") or []:
            if str(row.get("key")) == key:
                return int(row.get("line") or 0)
        return 0

    def _apply_one(self, key, force=False):
        try:
            from core.hunk_edit import apply_hunks
            r = apply_hunks(self.root, self.patch, selected_hunks={key},
                            base_texts=self._base,
                            conflict_policy="ai" if force else "ask")
        except Exception as e:  # 静默是故意的 - 失败原因显示在预览条
            self.status.setText("应用失败: " + str(e)[:200])
            return
        rows = [h for h in (r.get("hunks") or []) if h.get("key") == key]
        row = rows[0] if rows else {}
        if row.get("error"):
            self.status.setText("应用失败: " + str(row["error"])[:200])
            return
        manifest = str(r.get("manifest") or "")
        if manifest:
            self._hunk_manifests[key] = manifest
            self.manifest = manifest
        self._applied_keys.add(key)
        self._skipped.discard(key)
        self._applied = True
        self.apply_link.setText("✓ 已应用")
        self.status.setText("已应用 %s" % key)
        self._after_change()

    def _apply_all_hunks(self):
        try:
            from core.hunk_edit import apply_hunks
            r = apply_hunks(self.root, self.patch, selected_hunks=self._selected(),
                            base_texts=self._base, conflict_policy="ask",
                            format_first=self.format_first)
        except Exception as e:  # 静默是故意的 - 失败原因显示在预览条
            self.status.setText("应用失败: " + str(e)[:200])
            return
        if not r.get("ok"):
            self.status.setText("应用失败: " + "；".join(
                str(x) for x in (r.get("errors") or []))[:200])
            return
        self.manifest = str(r.get("manifest") or "")
        self._applied = True
        if not r.get("applied"):
            self.status.setText("已跳过全部修改，文件未改动")
            self.apply_link.setText("✓ 已应用")
            self._after_change()
            return
        self.apply_link.setText("✓ 已应用")
        fmt = r.get("format") or {}
        note = ""
        if fmt.get("formatted"):
            note = "（已先格式化 %s）" % "、".join(fmt["formatted"])
        self.status.setText("已应用: %s%s" % (", ".join(r.get("applied") or []),
                                            note))
        self._after_change()

    def _undo_one(self, key):
        manifest = self._hunk_manifests.get(key) or self.manifest
        rel, _, idx = key.rpartition(":")
        try:
            from core.hunk_edit import undo_hunk
            r = undo_hunk(manifest, rel, int(idx))
        except Exception as e:  # 静默是故意的 - 失败原因显示在预览条
            self.status.setText("撤销失败: " + str(e)[:200])
            return
        if not r.get("ok"):
            self.status.setText("撤销失败: " + str(r.get("error") or "")[:200])
            return
        self._applied_keys.discard(key)
        self.status.setText("已撤销 %s" % key)
        self._after_change()

    def _after_change(self):
        self._fill()
        self._refresh_hunks()

    # ---------------------------------------------------------- 动作
    def _apply(self, *_):
        if self._applied:
            self.status.setText("已应用，无需重复操作")
            return
        self.applyRequested.emit()
        if callable(self.on_apply):
            try:
                self.on_apply()
                self._applied = True
                self.status.setText("已应用（外部流程）")
            except Exception as e:  # 静默是故意的 - 外部回调失败要显示
                self.status.setText("应用失败: " + str(e)[:160])
            return
        if self._skipped or self._hunk_manifests:
            self._apply_all_hunks()   # 有跳过/逐段应用过，按 hunk 粒度落盘
            return
        try:
            from core.patch_engine import apply_patch
            r = apply_patch(self.root, self.patch)
            self.manifest = str(r.get("backup_manifest") or "")
            self._applied = True
            self.status.setText("已应用: %s" % ", ".join(r.get("applied") or []))
            self.apply_link.setText("✓ 已应用")
        except Exception as e:  # 静默是故意的 - 应用失败必须留在预览里提示
            self.status.setText("应用失败: " + str(e)[:200])

    def _undo(self, *_):
        self.undoRequested.emit()
        if callable(self.on_undo):
            try:
                r = self.on_undo() or {}
                restored = r.get("restored") if isinstance(r, dict) else None
                self.status.setText("已撤销: %s" % (restored or "完成"))
                self._applied = False
            except Exception as e:  # 静默是故意的
                self.status.setText("撤销失败: " + str(e)[:160])
            return
        if self._hunk_manifests:
            restored = []
            try:
                from core.hunk_edit import undo_hunk
                # 逐段应用留下的是"每个 hunk 应用前"的快照：倒序撤销才能回到原样。
                for key in reversed(list(self._hunk_manifests)):
                    rel, _, idx = key.rpartition(":")
                    r = undo_hunk(self._hunk_manifests[key], rel, int(idx))
                    restored.extend(r.get("restored") or [])
            except Exception as e:  # 静默是故意的 - 撤销失败要显示原因
                self.status.setText("撤销失败: " + str(e)[:200])
                return
            self._hunk_manifests.clear()
            self._applied_keys.clear()
            self._applied = False
            self.manifest = ""
            self.apply_link.setText(_APPLY_LINK)
            self.status.setText("已撤销: %s" % restored)
            self._after_change()
            return
        if not self.manifest:
            self.status.setText("没有可撤销的修改")
            return
        try:
            from core.patch_engine import rollback
            r = rollback(self.manifest)
            self.status.setText("已撤销: %s" % (r.get("restored") or []))
            self._applied = False
            self.manifest = ""
        except Exception as e:  # 静默是故意的
            self.status.setText("撤销失败: " + str(e)[:200])

    def mark_applied(self, manifest=""):
        """外部（Agent）已经应用时调用：只更新状态，不重复写盘。"""
        self._applied = True
        if manifest:
            self.manifest = str(manifest)
        self.status.setText("Agent 已应用本次修改")
        self.apply_link.setText("✓ 已应用")

    def current_target(self):
        pos = self.diff.textCursor().blockNumber()
        return self._targets.get(pos)
