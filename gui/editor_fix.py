# -*- coding: utf-8 -*-
"""「让 AI 修这一行」（第 8 批 B5 + 深度⑩）。

为什么是"修一行"
----------------
问题页/波浪线报的是**某一行**；让模型整文件重写既慢又容易丢改动。
这里只把"文件 + 行号 + 这一行的代码 + 报错描述 + 最近的运行输出"
交给模型，要求它只返回这一行的新写法，再走 diff 预览确认后落盘。

入口位置（不新增按钮）
--------------------
* 编辑器右键菜单「🛠 让 AI 修这一行」
* 问题页条目右键同一个动作（``gui/ide_editor_shell.py`` 的 ``fixRequested``）

真正调模型的代码在 ``gui/code_editor_ai.py::fix_line_with_ai`` —— widget
本身没有 LLM，它只负责"找到宿主窗口 + 带上定位信息"。找不到宿主时退回
``askAssistantRequested``（把整理好的提示发进聊天框，用户仍能问）。
"""
from __future__ import annotations

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MAX_LINE_CHARS = 160


class FixLineMixin:
    """给 ``CodeEditWidget`` 提供"当前行的问题 + 一键修复"入口。"""

    # ---------------------------------------------------------- 定位
    def problem_on_line(self, line):
        """返回第 ``line`` 行的第一条问题 ``(行, 列, 规则码, 描述)``。"""
        try:
            line = int(line or 0)
        except (TypeError, ValueError):
            return None
        for row in list(self.problems() or []):
            try:
                if int(row[0]) == line:
                    return tuple(row)
            except (IndexError, TypeError, ValueError):
                continue
        return None

    def problem_at_cursor(self):
        """光标所在行的问题（没有就返回 None）。"""
        try:
            line = self.textCursor().blockNumber() + 1
        except Exception as e:
            # 静默是故意的 - 取不到光标位置时按"没定位"处理
            _x6_swallowed(__name__, e, "cursor line for fix")
            return None
        return self.problem_on_line(line)

    # ---------------------------------------------------------- 修复
    def fix_line_request(self, line=None):
        """让 AI 修第 ``line`` 行（默认光标行）；返回是否发出了请求。"""
        line = self._fix_target_line(line)
        problem = self.problem_on_line(line)
        if problem is None:
            self._fix_say("第 %d 行没发现问题；先保存或运行一次再看问题页" % line)
            return False
        node = self.parent()
        while node is not None:
            handler = getattr(node, "fix_line_with_ai", None)
            if callable(handler):
                try:
                    return bool(handler(self, line, problem))
                # 静默是故意的 - 宿主里修复失败要退回聊天框那条路径
                except Exception as e:
                    _x6_swallowed(__name__, e, "host fix line")
                    break
            node = node.parent()
        self.askAssistantRequested.emit(self.fix_prompt(line, problem))
        return True

    def _fix_target_line(self, line):
        try:
            value = int(line or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
        try:
            return self.textCursor().blockNumber() + 1
        # 静默是故意的 - 光标不可用时默认第 1 行
        except Exception as e:
            _x6_swallowed(__name__, e, "fallback fix line")
            return 1

    def fix_prompt(self, line, problem):
        """整理成一段带定位的提问（找不到宿主时直接发给聊天框）。"""
        problem = tuple(problem or ())
        code = str(problem[2] or "") if len(problem) >= 3 else ""
        desc = str(problem[3] or "") if len(problem) >= 4 else ""
        return ("请只修好 %s 第 %d 行的这一处问题（%s %s），"
                "其余代码不要动。这一行现在是：\n%s"
                % (getattr(self, "filepath", "") or "(未保存的文件)", int(line),
                   code, desc, self.line_text(line)[:MAX_LINE_CHARS]))

    def line_text(self, line):
        """第 ``line`` 行原文（越界返回空串）。"""
        try:
            block = self.document().findBlockByNumber(max(0, int(line) - 1))
        # 静默是故意的 - 行号非法时按空行处理
        except Exception as e:
            _x6_swallowed(__name__, e, "fix line text")
            return ""
        return block.text() if block.isValid() else ""

    def _fix_say(self, message):
        """提示走状态栏（复用语言服务那套降级）。"""
        say = getattr(self, "_lsp_say", None)
        if callable(say):
            try:
                say(message)
                return
            # 静默是故意的 - 状态栏不可用就不提示了，不影响编辑
            except Exception as e:
                _x6_swallowed(__name__, e, "fix line status")
        return None

    # ---------------------------------------------------------- 开关
    def _fix_enabled(self):
        """``编辑.一键修复`` 开关（关掉只是没有右键入口，能力仍在）。"""
        trunk = getattr(self, "trunk", None)
        if trunk is not None:
            try:
                return bool(trunk.rule("编辑.一键修复", True))
            # 静默是故意的 - 读不到规则就按默认开处理
            except Exception as e:
                _x6_swallowed(__name__, e, "read fix rule")
        return True

    # ---------------------------------------------------------- 菜单
    def _fix_add_menu(self, menu):
        """往右键菜单里加"让 AI 修这一行"（不建按钮，只加菜单项）。"""
        if not self._fix_enabled():
            return
        try:
            line = self._fix_target_line(0)
            problem = self.problem_on_line(line)
            label = "🛠 让 AI 修这一行（第 %d 行）" % line
            if problem is None:
                label = "🛠 让 AI 修这一行（本行无问题）"
            action = menu.addAction(label)
            action.setToolTip("把这一行和报错交给 AI，改动先过 diff 预览")
            action.triggered.connect(lambda _c=False: self.fix_line_request(line))
        # 静默是故意的 - 菜单项加不上不影响其它右键动作
        except Exception as e:
            _x6_swallowed(__name__, e, "extend context menu with fix line")
