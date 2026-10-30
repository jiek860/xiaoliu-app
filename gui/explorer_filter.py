# -*- coding: utf-8 -*-
"""资源管理器筛选：输入关键字，只显示文件名匹配的文件。

为什么用 QFileSystemModel.setNameFilters
---------------------------------------
套 QSortFilterProxyModel 需要把所有 ``tree.index`` 调用的地方改成
``mapToSource``（双击打开、定位、刷新 git 标记都会受影响），风险大。
``setNameFilters(["*关键字*"])`` 是模型自带能力，目录仍然可见、
文件按通配符过滤，改动面最小，也符合 IDE 里"输入即筛"的直觉。

约束：不创建按钮，只有一个 QLineEdit。
"""
from __future__ import annotations

import re

from PyQt5.QtWidgets import QLineEdit

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None

_MAX_TERMS = 3


def patterns(text):
    """关键字 -> QFileSystemModel 的通配符列表（空串=不过滤）。

    多个空格分隔的词按 AND 处理（Qt 只支持单串通配符，这里取最后一个词
    作为文件名过滤，其余词交给用户自己缩小范围）。
    """
    terms = [t for t in re.split(r"[^\w\u4e00-\u9fff]+", str(text or "")) if t]
    terms = terms[-_MAX_TERMS:]
    if not terms:
        return []
    return ["*%s*" % term for term in terms[-1:]]


def apply_filter(model, text):
    """把筛选词应用到模型；返回实际生效的通配符列表。"""
    if model is None:
        return []
    pats = patterns(text)
    try:
        model.setNameFilters(pats)
        model.setNameFilterDisables(False)   # 不匹配的文件隐藏，而不是变灰
    except Exception as e:  # 静默是故意的 - 筛选失败就显示全部
        _x6_swallowed(__name__, e, "apply explorer filter")
        return []
    return pats


def install(dialog, layout, tree=None, model=None):
    """在资源管理器顶部插入筛选框，返回 QLineEdit（同时挂到 dialog 上）。"""
    box = QLineEdit()
    box.setPlaceholderText("筛选文件…（留空显示全部）")
    box.setFixedHeight(24)
    box.setStyleSheet(
        "QLineEdit{border:1px solid #d0d7de;border-radius:5px;"
        "padding:2px 6px;font-size:11px;background:#ffffff;}"
        "QLineEdit:focus{border-color:#84adff;}")
    tree = tree or getattr(dialog, "tree", None)
    model = model or getattr(dialog, "fs_model", None)
    if model is None and tree is not None:
        model = tree.model()
    state = {"model": model, "tree": tree}

    def _changed(text):
        apply_filter(state["model"], text)
        tree_widget = state["tree"]
        if tree_widget is not None and str(text or "").strip():
            try:
                tree_widget.expandAll()
            except Exception as e:  # 静默是故意的 - 展开失败不影响筛选
                _x6_swallowed(__name__, e, "expand filtered tree")

    box.textChanged.connect(_changed)
    layout.addWidget(box)
    dialog.explorer_filter = box
    dialog._explorer_filter_state = state
    return box
