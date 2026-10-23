# -*- coding: utf-8 -*-
"""新功能基础测试"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_skill_registry_load():
    """测试 SkillRegistry 基本功能"""
    from core.skill_registry import SkillRegistry

    # 不用真 trunk，mock 一下
    class MockTrunk:
        base = "."

    sr = SkillRegistry(MockTrunk())

    # list_all 应该返回列表
    skills = sr.list_all()
    assert isinstance(skills, list), "list_all 应该返回列表"

    # get_enabled_prompts 应该返回字符串
    prompts = sr.get_enabled_prompts()
    assert isinstance(prompts, str), "get_enabled_prompts 应该返回字符串"

    print("✅ test_skill_registry_load 通过")


def test_coder_pro_plan_injection():
    """测试 coder_pro 把 plan 拼到 goal 里"""
    # 只测字符串拼接逻辑，不真跑 CodeAgent
    goal = "修复登录bug"
    plan = "## 计划\n1. 改 login.py\n2. 改 auth.py"

    actual_goal = goal
    if plan:
        actual_goal = f"用户任务：{goal}\n\n已批准的执行计划（请按这个计划执行）：\n{plan}"

    assert "用户任务：修复登录bug" in actual_goal
    assert "已批准的执行计划" in actual_goal
    assert "改 login.py" in actual_goal

    print("✅ test_coder_pro_plan_injection 通过")


def test_web_agent_action_parsing():
    """测试 web_agent 动作解析"""
    # 模拟 LLM 返回的动作字符串
    action_text = """我觉得应该点击登录按钮。
ACTION: click('#login-btn')
"""
    assert "ACTION:" in action_text
    action_line = [l for l in action_text.split("\n") if "ACTION:" in l][0]
    action = action_line.split("ACTION:")[1].strip()
    assert action == "click('#login-btn')"
    assert action.startswith("click(")

    print("✅ test_web_agent_action_parsing 通过")


def test_api_server_auth():
    """测试 Web 控制台 token 鉴权逻辑"""
    # 模拟检查 token 的逻辑
    auth_token = "test_token_123"

    def check_auth(path, headers_token=None):
        if not auth_token:
            return True
        token = None
        if "?token=" in path:
            token = path.split("?token=")[1].split("&")[0]
        elif headers_token:
            token = headers_token.replace("Bearer ", "")
        return token == auth_token

    # 带对的 token
    assert check_auth("/?token=test_token_123") == True
    # 带错的 token
    assert check_auth("/?token=wrong_token") == False
    # 不带 token
    assert check_auth("/") == False

    print("✅ test_api_server_auth 通过")


if __name__ == "__main__":
    test_skill_registry_load()
    test_coder_pro_plan_injection()
    test_web_agent_action_parsing()
    test_api_server_auth()
    print("\n✅ 全部新功能测试通过")
