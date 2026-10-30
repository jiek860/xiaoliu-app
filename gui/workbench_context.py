# -*- coding: utf-8 -*-
"""工作台 -> AI 上下文：把当前文件 / 选区送进右侧 AI 输入框。

为什么单独成文件
----------------
`code_editor_dialog.py` 顶到 600 行上限，而这段逻辑同时被「标签页右键菜单」
和快捷键调用，放这里更便于单独测试。

行为：有选区只发选区（带 ``文件:行`` 头），没有选区发整个文件（截断）；
AI 面板隐藏时先展开，再把文本追加到目标框末尾并聚焦。
"""
from __future__ import annotations

from core.chat import workspace_context

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None


def collect(dialog, max_chars=4000):
    """读当前标签的选区 / 全文，返回上下文文本（空串=没有可发内容）。"""
    try:
        w = dialog.tabs.currentWidget()
    except Exception as e:  # 静默是故意的 - 没有标签就发空
        _x6_swallowed(__name__, e, "collect workbench context")
        return ""
    path = str(getattr(w, "filepath", "") or "")
    if not path and not hasattr(w, "textCursor"):
        return ""
    root = str(getattr(dialog, "root", "") or ".")
    selection, line = "", 0
    try:
        cur = w.textCursor()
        selection = cur.selectedText().replace("\u2029", "\n")
        line = cur.blockNumber() + 1
    except Exception as e:
        _x6_swallowed(__name__, e, "read editor selection")
    if selection.strip():
        return workspace_context.selection_block(
            path or None, root, selection, line,
            max_chars=min(2000, max_chars))
    text = ""
    try:
        text = w.toPlainText() if hasattr(w, "toPlainText") else ""
    except Exception as e:
        _x6_swallowed(__name__, e, "read editor text")
    return workspace_context.file_text_block(
        path or None, root, text, max_chars=max_chars)


def _ai_host(obj):
    """向上找带 ``ai_dock`` 的窗口（编辑器可能是工作台的子窗口）。"""
    cur = obj
    for _ in range(4):
        if cur is None:
            return None
        if hasattr(cur, "ai_dock"):
            return cur
        try:
            cur = cur.parent()
        except Exception:
            return None
    return None


def send_to_ai(dialog, prompt=""):
    """把上下文送到 AI 目标框；返回实际发送的文本长度（0=没内容）。"""
    context = collect(dialog)
    if not context:
        dialog._status("当前标签没有可发送的代码", 3000)
        return 0
    host = _ai_host(dialog)
    dock = getattr(host, "ai_dock", None)
    if dock is None or not hasattr(dock, "goal"):
        dialog._status("AI 面板不可用", 3000)
        return 0
    try:
        host_host = getattr(host, "ai_host", None)
        if host_host is not None and host_host.isHidden():
            host_host.show()
        goal = dock.goal.toPlainText().strip()
        dock.goal.setPlainText(workspace_context.prompt_with_context(
            goal or prompt, context))
        dock.goal.setFocus()
        dialog._status("已把当前代码加入 AI 提示", 3000)
        return len(context)
    except Exception as e:  # 静默是故意的 - 失败只影响便利功能
        _x6_swallowed(__name__, e, "send workbench context to ai")
        dialog._status("发送到 AI 失败: " + str(e)[:60], 4000)
        return 0


# 批次 D10：编辑器 AI 浮条的三个快捷动作 (指令, 是否直接开跑)
ACTIONS = {
    "explain": ("解释这段代码在做什么，讲清输入、输出和副作用。", False),
    "refactor": ("重构这段代码，保持对外行为不变，说明改动理由。", True),
    "test": ("为这段代码补 pytest 用例，覆盖正常路径和边界条件。", True),
}


def send_action(dialog, action):
    """选中代码 + 预设指令交给 AI；解释只回填，重构/补测试顺手开跑。

    返回实际发出的上下文字符数（0=没发出去，比如没有选区也没有 AI 面板）。
    """
    meta = ACTIONS.get(str(action))
    if not meta:
        return 0
    prompt, auto_start = meta
    host = _ai_host(dialog)
    dock = getattr(host, "ai_dock", None)
    if dock is None or not hasattr(dock, "goal"):
        dialog._status("AI 面板不可用", 3000)
        return 0
    try:
        current = dock.goal.toPlainText().strip()
        dock.goal.setPlainText((current + "\n" if current else "") + prompt)
    except Exception as e:  # 静默是故意的 - 写不进目标框就当没点到
        _x6_swallowed(__name__, e, "prepare ai action")
        return 0
    sent = send_to_ai(dialog)
    if sent and auto_start and hasattr(dock, "start"):
        try:
            dock.start()
        except Exception as e:
            _x6_swallowed(__name__, e, "start ai action")
    return sent


def install_actions(dialog):
    """在编辑器顶栏挂一条 AI 快捷浮动条（QAction 不占按钮预算）。"""
    editor = getattr(dialog, "_editor", None)
    if editor is None or not hasattr(editor, "addToolBar"):
        return None
    try:
        from PyQt5.QtCore import Qt
        bar = editor.addToolBar("AI 快捷")
        bar.setObjectName("ai_quick_bar")
        editor.addToolBar(Qt.TopToolBarArea, bar)
        for key, label in (("explain", "解释选中"),
                           ("refactor", "重构选中"),
                           ("test", "补测试")):
            act = bar.addAction(label)
            act.setToolTip(ACTIONS[key][0])
            act.triggered.connect(
                lambda _checked=False, k=key: send_action(dialog, k))
        editor.ai_quick_bar = bar
        return bar
    except Exception as e:  # 静默是故意的 - 浮条装不上不影响编辑器
        _x6_swallowed(__name__, e, "install ai quick bar")
        return None


def install(dialog):
    """给工作台装快捷键 Ctrl+Shift+A（等价于右键「发送到 AI」）和 AI 快捷条。"""
    from PyQt5.QtGui import QKeySequence
    from PyQt5.QtWidgets import QShortcut

    sc = QShortcut(QKeySequence("Ctrl+Shift+A"), dialog)
    sc.activated.connect(lambda: send_to_ai(dialog))
    dialog.send_context_shortcut = sc
    dialog.ai_quick_bar = install_actions(dialog)
    return sc
