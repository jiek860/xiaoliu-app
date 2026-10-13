# -*- coding: utf-8 -*-
"""🧰 实用工具（旧按钮面板）—— 已由命令面板取代，这里只留兼容壳

为什么撤掉
----------
这个面板原来把 24 条能力做成 24 个常驻按钮（手写的 ACTIONS 表）。
但实测下来那 24 条里 **23 条"说一句"就能用**，做成按钮有三个代价：
    · 占地方：一个人贡献了 GUI 里 24/114 处控件
    · 要手工维护：模块改了方法名，表不会自动跟着改
    · 只有人能点到：模型够不着，所以坏了也没人发现
      （`memory_organizer.check_conflicts` 就因为只能手点，
       文件对象切片那个 TypeError 藏了很久）

现在改成 `gui/command_palette.py` 的**命令面板（Ctrl+K）**：
    · 数据来自 core/module_caps 能力注册表，模块声明 TOOLS 就自动出现
    · 按需搜索，不常驻占屏
    · 和聊天共用同一套执行路径（tool_caller._dispatch），安全分级只有一处实现

回滚
----
要退回按钮面板：`git revert` 撤掉这次提交即可（旧实现完整保留在 git 历史里）。
ACTIONS 那 24 条数据也没有丢 —— 它们已经全部变成注册表里的能力声明
（core/core_caps.py 与各模块的 TOOLS）。
"""
from PyQt5.QtWidgets import QMessageBox


class ModuleToolsDialog:
    """兼容壳：老代码 `ModuleToolsDialog(trunk, parent).exec_()` 仍能用

    行为：打开命令面板。不再创建那 24 个按钮。
    """

    def __init__(self, trunk, parent=None):
        self.trunk = trunk
        self.parent = parent

    def exec_(self):
        try:
            from gui.command_palette import show_command_palette
            cmds = None
            p = self.parent
            if p is not None and hasattr(p, "_panel_commands"):
                cmds = p._panel_commands()
            return show_command_palette(self.trunk, cmds, p)
        except Exception as e:
            try:
                QMessageBox.warning(self.parent, "实用工具",
                                    "打不开命令面板：" + str(e)[:150])
            except Exception:
                pass
            return None

    def show(self):
        return self.exec_()


def show_module_tools(trunk, parent=None):
    return ModuleToolsDialog(trunk, parent).exec_()
