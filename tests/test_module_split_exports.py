# -*- coding: utf-8 -*-
"""大文件拆分后的对外导出契约。

拆分原则是"只搬代码不改行为"，所以旧导入路径必须继续可用。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def test_old_paths_are_under_500_lines():
    files = [
        "modules/installed/plugin_market.py",
        "gui/settings_dialog.py",
        "modules/installed/tool_caller.py",
        "gui/mcp_dialog.py",
        "gui/workbench_dialog.py",
        "gui/mixins/dialog_mixin.py",
    ]
    for rel in files:
        with open(os.path.join(BASE, rel), encoding="utf-8") as f:
            n = sum(1 for _ in f)
        assert n <= 500, "%s 还有 %d 行（拆分目标 ≤500）" % (rel, n)


def test_plugin_market_keeps_online_methods():
    from modules.installed.plugin_market import PluginMarket
    assert hasattr(PluginMarket, "list_online")
    assert hasattr(PluginMarket, "download")
    assert hasattr(PluginMarket, "check_updates")


def test_tool_catalog_matches_runtime_catalog():
    from modules.installed.tool_caller import ToolCaller
    from modules.installed.tool_catalog import BUILTIN_TOOLS
    # 运行时会再合并 MCP 工具，所以只要求内置清单是子集且一项不少
    assert set(BUILTIN_TOOLS) <= set(ToolCaller(None).tools)
    assert len(BUILTIN_TOOLS) >= 10


def test_mcp_dialog_keeps_presets_and_tabs():
    import gui.mcp_dialog as dlg
    from gui.mcp_catalog import DEFAULT_PRESETS, REFERENCE
    assert len(dlg.PRESETS) >= 10
    assert len(REFERENCE) == 3
    assert len(DEFAULT_PRESETS) == len(dlg.PRESETS)


def test_workbench_reexports_agent_dock():
    from gui.workbench_dialog import AgentDock
    from gui.workbench_ai_dock import AgentDock as Impl
    assert AgentDock is Impl


def test_dialog_mixin_keeps_background_methods():
    from gui.mixins.dialog_mixin import DialogMixin
    from gui.mixins.background_tasks_mixin import BackgroundTaskMixin
    assert issubclass(DialogMixin, BackgroundTaskMixin)
    for name in ("_bg_call", "_run_task_goal", "_run_learn_one",
                 "_export_backup_ui", "_run_auto_update_ui",
                 "_module_button_clicked", "_install_component"):
        assert hasattr(DialogMixin, name), name


def test_settings_model_page_exported():
    from gui.settings_model_page import build_model_page
    assert callable(build_model_page)
