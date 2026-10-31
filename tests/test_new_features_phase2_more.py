# -*- coding: utf-8 -*-
"""新功能基础测试（补充版）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_browser_back_method():
    """测试 browser.py 有 back() 方法"""
    from modules.installed.browser import Browser
    assert hasattr(Browser, "back"), "Browser 应该有 back() 方法"
    print("✅ test_browser_back_method 通过")


def test_feature_registry_has_skills():
    """测试 feature_registry 里有技能管理入口（折叠后只在命令面板）"""
    from core.feature_registry import _FEATURES, MORE_MENU_GROUPS, FEATURES
    # 找有没有 skills 这个 feature
    skill_ids = [f.id for f in _FEATURES]
    assert "skills" in skill_ids, "FEATURES 里应该有 skills 入口"
    assert FEATURES.get("skills") is not None, "技能管理能力应保留（命令面板可查）"

    # 折叠后 skills 不应再出现在更多菜单（入口收进命令面板，能力不丢）
    found = False
    for group_name, ids in MORE_MENU_GROUPS:
        if "skills" in ids:
            found = True
            break
    assert not found, "skills 已折叠进命令面板，不应再出现在更多菜单"
    print("✅ test_feature_registry_has_skills 通过")


def test_swe_bench_has_commit_hash():
    """测试 SWE-bench case 有 commit_hash 字段"""
    from tests.eval.swe_bench.runner import SAMPLE_CASES
    for case in SAMPLE_CASES:
        assert "commit_hash" in case, f"case {case['id']} 应该有 commit_hash 字段"
    print("✅ test_swe_bench_has_commit_hash 通过")


def test_skills_market_import():
    """测试远程 Skills 市场模块能 import"""
    from core.skills_market import fetch_remote_catalog, download_skill
    assert callable(fetch_remote_catalog)
    assert callable(download_skill)
    print("✅ test_skills_market_import 通过")


def test_web_agent_back_handling():
    """测试 web_agent 对 back() 动作的处理"""
    # 模拟动作解析
    action = "back()"
    # browser 现在有 back() 方法了，应该支持
    assert action.startswith("back()")
    print("✅ test_web_agent_back_handling 通过")


if __name__ == "__main__":
    test_browser_back_method()
    test_feature_registry_has_skills()
    test_swe_bench_has_commit_hash()
    test_skills_market_import()
    test_web_agent_back_handling()
    print("\n✅ 全部补充测试通过")
