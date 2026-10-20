# -*- coding: utf-8 -*-
"""GroupChat：角色配置、路由、记忆、子智能体回复和群聊合并。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.group_chat import GroupChat  # noqa: E402


class _Agent:
    def __init__(self, text):
        self.text = text

    def reply(self, _q):
        return self.text


class _LLM:
    def chat(self, _msgs, **_kw):
        return "LLM补充"


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        os.makedirs(os.path.join(self.base, "data"), exist_ok=True)
        self.config = {"local_model": "qwen2.5:3b", "群聊模式": True}
        self.modules = {
            "agent_coder": _Agent("代码建议"),
            "agent_analyst": _Agent("分析建议"),
            "llm": _LLM(),
        }

    def call(self, module, method, *_a, **_k):
        if module == "auth" and method == "whoami":
            return {"user": "tester"}
        return {}

    def _load_lazy(self, _name):
        return None

    def _log(self, *_a, **_k):
        return None


def test_group_roles_and_memory(tmp_path):
    g = GroupChat(_Trunk(tmp_path))
    assert g.save_roles() is True
    assert g.update_role("小七", duty="新职责") is True
    assert g.roles["小七"]["duty"] == "新职责"
    r = g.rename_role("小七", "小七新")
    assert r["ok"] is True
    assert "小七新" in g.roles
    assert g.rename_role("不存在", "x")["ok"] is False
    assert g.update_role("不存在") is False

    g._append_mem("小七新", "tester", "问题", "回答")
    msgs = g._load_mem("小七新", "tester")
    assert msgs and msgs[0]["content"] == "问题"
    assert g._username() == "tester"
    assert g._mem_path("小七新", "tester").endswith(".jsonl")


def test_group_routing_and_reply(tmp_path):
    g = GroupChat(_Trunk(tmp_path))
    assert set(g.pick_roles("大家一起讨论")) == set(g.roles)
    assert "小七" in g.pick_roles("Python 代码报错")
    assert g._jaccard("abc", "abc") == 1.0
    assert g._jaccard("", "abc") == 0.0
    seg = g._role_reply("小七", "Python 问题", "主回复", "tester")
    assert "代码建议" in seg
    # agent_analyst 存在，小八也走真实子智能体
    assert "分析建议" in g._role_reply("小八", "为什么", "主回复", "tester")


def test_group_start_and_compose(tmp_path, monkeypatch):
    g = GroupChat(_Trunk(tmp_path))
    futs = g.start_roles("Python 代码报错", username="tester")
    assert futs
    text = g.compose("Python 代码报错", "主回复", username="tester", prefetch=futs)
    assert "【小6】" in text
    assert "代码建议" in text
    # 无角色命中时原样返回主回复
    solo = g.compose("随便聊聊", "只有主回复", username="tester")
    assert solo == "【小6】\n只有主回复"
    assert "多智能体" in g.run()["模块"]
    # 关闭群聊模式时 compose 原样返回
    g.trunk.config["群聊模式"] = False
    assert g.compose("Python 代码", "主回复") == "主回复"
    assert g.start_roles("Python 代码") is None