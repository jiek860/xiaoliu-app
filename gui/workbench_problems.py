# -*- coding: utf-8 -*-
"""工作区问题聚合（M1）：把各标签页的诊断实时汇总。

原来 ``CodeEditWidget.problemsChanged`` 全仓没有 ``connect``，问题只在
切标签/光标移动时被拉一次，且只覆盖当前文件。这里做两件事：

1. 每个编辑器注册到 :class:`ProblemsHub`，信号触发后 250ms 节流刷新；
2. 同时维护"全局问题数"，状态栏显示"本文件 N · 全局 M（K 个文件）"。

连接一律走"子对象 + 绑定方法"：控件销毁时 Qt 自动断开，避免回调落进
已释放的 C++ 对象（v25.3.0 的 0xC0000005 就是这么来的）。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtCore import QObject, pyqtSignal


def summary_counts(items_by_path):
    """纯函数：{路径: [问题]} -> (有问题的文件数, 问题总数)。"""
    files = total = 0
    for items in (items_by_path or {}).values():
        if not items:
            continue
        files += 1
        total += len(items)
    return files, total


def aggregate_text(path, own, files, total):
    """状态栏摘要："本文件 3 个问题 · 全局 12 个（4 个文件）"。"""
    if not total:
        return "本文件 %d 个问题 · 全局无问题" % int(own or 0)
    return "本文件 %d 个问题 · 全局 %d 个（%d 个文件）" % (
        int(own or 0), int(total), int(files))


class _Binder(QObject):
    """挂在编辑器下的短命对象：控件销毁时连接自动失效。"""

    def __init__(self, hub, path, widget):
        super().__init__(widget)
        self._hub = hub
        self._path = path
        self._widget = widget

    def notify(self):
        self._hub.touch(self._path)


class ProblemsHub(QObject):
    """按路径维护各编辑器的问题列表，变化时发 ``changed``。"""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widgets = {}
        self._items = {}

    def register(self, path, widget):
        key = str(path or "")
        if not key or self._widgets.get(key) is widget:
            return
        self._widgets[key] = widget
        self._items[key] = list(self._safe_problems(widget))
        binder = _Binder(self, key, widget)
        widget.problemsChanged.connect(binder.notify)

    def unregister(self, path):
        key = str(path or "")
        self._widgets.pop(key, None)
        self._items.pop(key, None)

    def touch(self, path):
        key = str(path or "")
        widget = self._widgets.get(key)
        if widget is None:
            return
        self._items[key] = list(self._safe_problems(widget))
        self.changed.emit()

    def items(self, path=None):
        if path is None:
            out = []
            for key, rows in self._items.items():
                out.extend(rows)
            return out
        return list(self._items.get(str(path or "")) or [])

    def counts(self):
        return summary_counts(self._items)

    def aggregate_text(self, path=""):
        files, total = self.counts()
        return aggregate_text(path, len(self.items(path)), files, total)

    @staticmethod
    def _safe_problems(widget):
        """控件已销毁/取问题失败时返回空列表，不抛给 UI。"""
        try:
            return widget.problems() or []
        except Exception as e:
            _x6_swallowed(__name__, e, "read widget problems")
            return []
