# -*- coding: utf-8 -*-
"""按钮去重回归：同页面入口只保留一个。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def test_more_menu_has_no_task_aliases_or_computer_agent():
    from core.feature_registry import MORE_MENU_GROUPS
    ids = [fid for _g, group in MORE_MENU_GROUPS for fid in group]
    for fid in ("start_task", "scheduled_tasks", "computer_agent"):
        assert fid not in ids, "更多菜单仍有重复入口: " + fid
    assert "task_center" in ids
    assert "workbench" in ids


def test_panel_registry_drops_duplicate_page_entries():
    from gui.panel_registry import build_panel_commands

    class Owner:
        def open_task_center(self, *a, **k): return None
        def activity_center_dialog(self): return None
        def open_workbench(self): return None

    cmds = build_panel_commands(Owner())
    for key in ("定时任务", "开始任务", "电脑 Agent", "权限中心"):
        assert key not in cmds, "命令面板仍有重复入口: " + key
    assert cmds["任务中心"] is not None
    assert cmds["电脑控制"] is not None or cmds["电脑控制"] is None  # key exists


def test_computer_agent_routes_to_workbench():
    from gui.mixins.agent_launcher_mixin import AgentLauncherMixin
    sentinel = object()

    class Owner(AgentLauncherMixin):
        def open_workbench(self):
            return sentinel

    assert Owner().computer_agent_dialog() is sentinel


def test_scheduled_tasks_alias_still_points_to_task_center():
    from core.feature_registry import get_feature
    assert get_feature("scheduled_tasks").id == "task_center"
    assert get_feature("computer_agent").id == "workbench"
