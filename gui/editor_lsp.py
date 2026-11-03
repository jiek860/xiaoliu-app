# -*- coding: utf-8 -*-
"""编辑器里的语言服务交互（第 7 批 B3 + 深度①③）。

能力
----
  Ctrl+Click / F12   跳到定义（跨文件也能跳）
  Shift+F12          查找引用
  F2                 重命名符号（跨文件，一次改完）
  Ctrl+Alt+F         格式化（有选区就只格式化选区，深度⑥）
  右键菜单           以上动作 + 「查看符号信息」（hover）

为什么是一个 mixin
------------------
`gui/code_editor_widget.py` 已经 592 行（硬上限 600），塞不进 200 多行交互逻辑。
mixin 让 CodeEditWidget 只多两行（import + 基类），逻辑在这里独立可读、可测。

按钮预算：所有入口都是**快捷键 + 右键菜单项**，不新建 QPushButton/QAction 控件；
没装语言服务时每个入口都退化成一句提示，不报错、不弹窗崩溃。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QInputDialog, QMessageBox, QToolTip

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class LspEditorMixin:
    """给 CodeEditWidget 提供"语言服务"动作；拿不到服务就安静地提示一句。"""

    # ---------------------------------------------------------- 初始化
    def _lsp_init(self):
        """装快捷键 + 初始化缓存（在 CodeEditWidget.__init__ 末尾调用一次）。"""
        self._last_references = []
        self._lsp_cache = {}
        try:
            from PyQt5.QtGui import QKeySequence
            from PyQt5.QtWidgets import QShortcut
            for keys, slot in ((QKeySequence("F12"), self.lsp_goto_definition),
                               (QKeySequence("Shift+F12"),
                                self.lsp_find_references),
                               (QKeySequence("F2"), self.lsp_rename_symbol),
                               (QKeySequence("Ctrl+Alt+F"),
                                self.lsp_format_document)):
                sc = QShortcut(keys, self)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(slot)
        except Exception as e:  # 静默是故意的 - 快捷键装不上不影响编辑
            _x6_swallowed(__name__, e, "install lsp shortcuts")

    # ---------------------------------------------------------- 基础设施
    def _lsp_root(self):
        try:
            from core.code.completion import project_root
            root = project_root(getattr(self, "trunk", None),
                                getattr(self, "filepath", "") or "")
            if root:
                return root
        # 静默是故意的 - 拿不到工程根就退回文件所在目录
        except Exception as e:
            _x6_swallowed(__name__, e, "resolve lsp root")
        path = getattr(self, "filepath", "") or ""
        return os.path.dirname(os.path.abspath(path)) if path else ""

    def _lsp_client(self, autostart=True):
        """当前文件的语言服务客户端；没装/起不来返回 None（不抛异常）。"""
        path = getattr(self, "filepath", "") or ""
        if not path or not os.path.isfile(path):
            return None
        root = self._lsp_root()
        if not root:
            return None
        try:
            from core.lsp_client import client_for
            client = client_for(root, path, autostart=autostart)
        # 静默是故意的 - 服务异常按"不可用"处理，界面退回 jedi
        except Exception as e:
            _x6_swallowed(__name__, e, "acquire lsp client")
            return None
        if client is not None and autostart:
            try:
                client.did_open(self.toPlainText(), path)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "lsp did_open")
        return client

    def _lsp_position(self):
        """光标 → LSP 位置（行列 0 基）与当前文本。"""
        text = self.toPlainText()
        offset = self.textCursor().position()
        from core.lsp_protocol import offset_to_position
        return text, offset_to_position(text, offset)

    def _lsp_say(self, message):
        """把提示送到工作台状态栏（找不到就退化成光标旁的 tooltip）。"""
        msg = str(message or "")
        node = self.parent()
        while node is not None:
            sink = getattr(node, "_status", None)
            if callable(sink):
                try:
                    sink(msg, 4000)
                    return
                # 静默是故意的 - 状态栏不可用就走下面的 tooltip
                except Exception as e:
                    _x6_swallowed(__name__, e, "lsp status message")
                    break
            node = node.parent()
        try:
            QToolTip.showText(
                self.mapToGlobal(self.cursorRect().bottomLeft()), msg, self)
        except Exception as e:  # 静默是故意的 - 连提示都失败就算了
            _x6_swallowed(__name__, e, "lsp tooltip")

    def _lsp_locate(self, loc):
        """打开/定位到某个位置；返回是否成功。"""
        path = str((loc or {}).get("path") or "")
        line = int((loc or {}).get("line") or 1)
        if not path:
            return False
        current = os.path.normpath(os.path.abspath(
            getattr(self, "filepath", "") or ""))
        if os.path.normpath(os.path.abspath(path)) == current:
            block = self.document().findBlockByNumber(max(0, line - 1))
            if block.isValid():
                self.setTextCursor(QTextCursor(block))
                self.centerCursor()
                self.setFocus()
                return True
        node = self.parent()
        while node is not None:
            opener = getattr(node, "open_path_at", None)
            if callable(opener):
                try:
                    opener(path, line)
                    return True
                # 静默是故意的 - 打不开就继续往上找宿主窗口
                except Exception as e:
                    _x6_swallowed(__name__, e, "open lsp location")
            node = node.parent()
        return False

    def _lsp_unavailable(self):
        """没服务时的一句话（带装法），保证是"提示"而不是"报错"。"""
        try:
            from core.lsp_client import install_hint
            hint = install_hint(getattr(self, "filepath", "") or "")
        # 静默是故意的 - 拼不出装法也要把提示说完整
        except Exception as e:
            _x6_swallowed(__name__, e, "lsp install hint")
            hint = ""
        self._lsp_say("未安装该语言的语言服务（跳转/引用/重命名不可用）"
                      + ("；装法：" + hint if hint else ""))
        return None

    # ---------------------------------------------------------- 动作
    def lsp_goto_definition(self, *_):
        """F12 / Ctrl+Click：跳到光标符号的定义处。"""
        client = self._lsp_client()
        if client is None:
            self._lsp_unavailable()
            return False       # 契约：跳转成功与否永远是 bool
        text, pos = self._lsp_position()
        r = client.definition(pos["line"], pos["character"])
        if not r.get("ok") or not r.get("locations"):
            self._lsp_say("没找到定义（%s）" % (r.get("reason") or "符号未知"))
            return False
        ok = self._lsp_locate(r["locations"][0])
        if ok:
            loc = r["locations"][0]
            self._lsp_say("已跳到定义：%s:%d" % (os.path.basename(loc["path"]),
                                              loc["line"]))
        return ok

    def lsp_find_references(self, *_):
        """Shift+F12：列出引用位置（结果同时存进 _last_references 便于测试）。"""
        client = self._lsp_client()
        if client is None:
            self._lsp_unavailable()
            return []          # 契约：引用列表永远是 list，调用方不用判 None
        _text, pos = self._lsp_position()
        r = client.references(pos["line"], pos["character"])
        locations = r.get("locations") or []
        self._last_references = list(locations)
        if not r.get("ok") or not locations:
            self._lsp_say("没找到引用（%s）" % (r.get("reason") or "该符号没被引用"))
            return []
        lines = ["%d. %s:%d" % (i + 1, os.path.basename(x["path"]), x["line"])
                 for i, x in enumerate(locations[:40])]
        self._lsp_say("找到 %d 处引用" % len(locations))
        if self.window() is not None and self.isVisible():
            QMessageBox.information(
                self, "引用位置（共 %d 处）" % len(locations),
                "\n".join(lines) + ("\n…" if len(locations) > 40 else ""))
        return locations

    def lsp_rename_symbol(self, *_):
        """F2：跨文件重命名（语言服务算出全部改动，本地按范围应用）。"""
        client = self._lsp_client()
        if client is None:
            self._lsp_unavailable()
            return False       # 契约：重命名成功与否永远是 bool
        word = ""
        try:
            cur = self.textCursor()
            cur.select(QTextCursor.WordUnderCursor)
            word = cur.selectedText()
        # 静默是故意的 - 取不到词就空着，用户自己填
        except Exception as e:
            _x6_swallowed(__name__, e, "word under cursor")
        new_name, ok = QInputDialog.getText(
            self, "重命名符号", "新名字：", text=word)
        if not ok or not new_name.strip():
            return False
        _text, pos = self._lsp_position()
        r = client.rename(pos["line"], pos["character"], new_name.strip())
        if not r.get("ok"):
            self._lsp_say("重命名失败：%s" % (r.get("reason") or "语言服务没返回"))
            return False
        from core.lsp_protocol import apply_workspace_edit
        applied = apply_workspace_edit(self._lsp_root(), r.get("edit"))
        if not applied.get("ok"):
            self._lsp_say("重命名没落盘：%s" % "；".join(
                applied.get("errors") or [applied.get("reason") or ""])[:180])
            return False
        for path in applied.get("changed") or []:
            node = self.parent()
            while node is not None:
                reloader = getattr(node, "reload_path", None)
                if callable(reloader):
                    try:
                        reloader(path)
                        break
                    # 静默是故意的 - 刷新失败不影响已落盘的改动
                    except Exception as e:
                        _x6_swallowed(__name__, e, "reload renamed file")
                node = node.parent()
        self._lsp_say("已重命名为 %s（改了 %d 个文件）"
                      % (new_name.strip(), len(applied.get("changed") or [])))
        return applied

    def lsp_hover(self, *_):
        """显示光标处符号的信息（签名/文档）。"""
        client = self._lsp_client()
        if client is None:
            self._lsp_unavailable()
            return ""          # 契约：hover 文本永远是 str
        _text, pos = self._lsp_position()
        r = client.hover(pos["line"], pos["character"])
        if not r.get("ok") or not r.get("text"):
            self._lsp_say("这里没有可显示的符号信息")
            return ""
        self._lsp_say(r["text"].splitlines()[0][:160])
        try:
            QToolTip.showText(
                self.mapToGlobal(self.cursorRect().bottomLeft()),
                r["text"][:600], self)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "hover tooltip")
        return r["text"]

    def lsp_format_document(self, *_):
        """Ctrl+Alt+F：格式化当前文件（有选区只格式化选区，深度⑥）。"""
        from core.code_format import format_preferred, format_text, snapshot_file
        path = getattr(self, "filepath", "") or ""
        trunk = getattr(self, "trunk", None)
        preferred = format_preferred(trunk)
        text = self.toPlainText()
        cur = self.textCursor()
        line_range = None
        if cur.hasSelection():
            first = self.document().findBlock(cur.selectionStart())
            last = self.document().findBlock(cur.selectionEnd())
            line_range = (first.blockNumber() + 1, last.blockNumber() + 1)
        res = format_text(text, path or "untitled.py", root=self._lsp_root(),
                          line_range=line_range, preferred=preferred)
        if not res.get("ok"):
            self._lsp_say("格式化不可用：%s" % (res.get("reason") or ""))
            return res
        if not res.get("changed"):
            self._lsp_say("格式已经很规范，无需改动")
            return res
        root = self._lsp_root()
        if root and path:
            snapshot_file(root, path, text)
        self._replace_all(res["text"])
        self._lsp_say("已格式化（%s）%s" % (
            res.get("formatter", ""),
            "，只动选中行" if line_range else ""))
        return res

    def _replace_all(self, text):
        """整篇替换：包在一个编辑块里，一次撤销就能退回去。"""
        cur = QTextCursor(self.document())
        cur.beginEditBlock()
        cur.select(QTextCursor.Document)
        cur.insertText(str(text or ""))
        cur.endEditBlock()

    def _lsp_in_service(self):
        """这个文件类型有没有可用服务（右键菜单据此加/不加动作）。"""
        try:
            from core.lsp_client import available_for
            return bool(available_for(getattr(self, "filepath", "") or ""))
        # 静默是故意的 - 探测失败按"没有"处理
        except Exception as e:
            _x6_swallowed(__name__, e, "probe lsp availability")
            return False

    # ---------------------------------------------------------- 菜单 / 鼠标
    def _lsp_add_menu(self, menu):
        """往右键菜单里加语言服务动作（CodeEditWidget.contextMenuEvent 调一次）。"""
        try:
            first = menu.addAction("➡ 跳到定义（F12）")
            first.triggered.connect(self.lsp_goto_definition)
            menu.insertSeparator(first)
            menu.addAction("🔍 查找引用（Shift+F12）").triggered.connect(
                self.lsp_find_references)
            menu.addAction("✏ 重命名符号（F2）").triggered.connect(
                self.lsp_rename_symbol)
            menu.addAction("💡 符号信息").triggered.connect(self.lsp_hover)
            menu.addAction("🧽 格式化（选区优先，Ctrl+Alt+F）").triggered.connect(
                self.lsp_format_document)
        # 静默是故意的 - 菜单加不上不影响其它右键项
        except Exception as e:
            _x6_swallowed(__name__, e, "extend context menu with lsp")

    def mousePressEvent(self, event):
        """Ctrl+左键 = 跳定义（VS Code / PyCharm 的肌肉记忆）。"""
        try:
            if event.button() == Qt.LeftButton and \
                    event.modifiers() & Qt.ControlModifier:
                if self._lsp_in_service():
                    if self.lsp_goto_definition():
                        return
            super().mousePressEvent(event)
        # 静默是故意的 - 鼠标处理绝不能抛异常（会打断输入焦点）
        except Exception as e:
            _x6_swallowed(__name__, e, "ctrl click go to definition")
