# -*- coding: utf-8 -*-
"""核心链路测试：trunk.reply() 能真的把话回出来

这是整个程序最核心的功能，之前只手工验证过一次，没有自动化。
这里用一个假的 LLM 替换掉真实模型，于是：
  · 不联网、不需要 Ollama 或 API Key，离线可跑
  · 不写用户的 data/（落盘路径改到临时目录）
  · 不起后台服务（否则会占 8899/8765 端口并触发学习/备份线程）
但 reply() 本身走的是真实代码路径：意图 → 上下文 → Prompt 组装 → 调度 → 后处理。

真实模型的端到端验证另有一份（需要 Ollama），见 tools/ 下的手工脚本。
"""
import os
import shutil
import sys
import tempfile
import unittest.mock as mock

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


class FakeLLM:
    """假模型：记录收到的 messages，返回固定答案"""

    def __init__(self, answer="这是测试回复。", boom=False):
        self.answer = answer
        self.boom = boom
        self.calls = []          # 每次调用收到的 messages

    def chat(self, messages, **kw):
        self.calls.append(messages)
        if self.boom:
            raise RuntimeError("模拟模型故障")
        return self.answer

    def stream_chat(self, messages, on_token=None, **kw):
        self.calls.append(messages)
        if self.boom:
            raise RuntimeError("模拟模型故障")
        if on_token:
            try:
                on_token(self.answer)
            except Exception:
                pass
        return self.answer

    def switch_model(self, name):
        return {"ok": True, "msg": "切到 " + name, "model": name}


@pytest.fixture
def trunk():
    """每个用例一个全新 Trunk（构建只要 0.26s），落盘全部改到临时目录。

    为什么必须每例一个：Trunk 里有跨调用累积的状态。最典型的是
    _reply_inner 里的 _use_pipeline —— pipeline 抛过一次异常就会被永久置为
    False 并降级到旧流程（见 test_pipeline_disabled_after_error 的说明），
    用模块级共享实例会让后续用例悄悄跑到另一条代码路径上。

    另外要屏蔽 DiskCache：它按用户输入做持久化缓存，会把上一次测试的
    结果带到这一次，导致"模型一次都没被调用"这种假象。
    """
    from core.trunk import Trunk

    tmp = tempfile.mkdtemp(prefix="reply_test_")
    with mock.patch.object(Trunk, "_start_background", lambda self: None), \
         mock.patch.object(Trunk, "_auto_backup", lambda self: None), \
         mock.patch.object(Trunk, "_warmup", lambda self: None), \
         mock.patch.object(Trunk, "_auto_unload_loop", lambda self: None), \
         mock.patch.object(Trunk, "_warmup_ollama", lambda self: None):
        t = Trunk()

    # 绝不碰用户真实数据
    t.data_dir = tmp
    t.memory_path = os.path.join(tmp, "memory.json")
    t.log_path = os.path.join(tmp, "trunk.log")
    t.config_path = os.path.join(tmp, "config.json")
    t.memory = {}
    t.current_user = "tester"
    # 后台闭环会写盘 / 联网 / 起线程，测试里关掉
    t._bg = lambda *a, **k: None
    # 关掉磁盘缓存（跨用例、跨次运行都会污染）
    _orig_load = t._load_lazy

    def _load_no_cache(name):
        if name == "cache":
            return None
        return _orig_load(name)
    t._load_lazy = _load_no_cache
    # 电脑控制快速通道会真的解析意图并可能操作本机，测试里绕过
    if getattr(t, "_pipeline", None):
        t._pipeline._try_computer_control = lambda ui: None

    yield t
    shutil.rmtree(tmp, ignore_errors=True)


def _install_fake(t, fake):
    t.modules["llm"] = fake
    return fake


# ---------------------------------------------------------------- 正常路径

def test_reply_returns_answer(trunk):
    """最基本的一条：能回出一句话"""
    fake = _install_fake(trunk, FakeLLM("你好呀，我是小6。"))
    r = trunk.reply("你好")
    assert isinstance(r, str)
    assert r.strip(), "reply() 不应该返回空"
    assert fake.calls, "LLM 应当被调用"


def test_prompt_contains_user_input(trunk):
    """用户说的话必须进了 Prompt，否则模型根本不知道问什么"""
    fake = _install_fake(trunk, FakeLLM("收到"))
    trunk.reply("请记住暗号是菠萝")
    blob = str(fake.calls[-1])
    assert "菠萝" in blob, "用户输入没有出现在发给模型的 messages 里"


def test_prompt_has_system_role(trunk):
    """组装出来的 Prompt 应当带 system 角色（人格设定）"""
    fake = _install_fake(trunk, FakeLLM("好"))
    trunk.reply("测试一下人格")
    msgs = fake.calls[-1]
    assert isinstance(msgs, list)
    roles = [m.get("role") for m in msgs if isinstance(m, dict)]
    assert "system" in roles, "没有 system 消息，人格注入没生效"
    assert "user" in roles, "没有 user 消息"


def test_reply_records_memory(trunk):
    """一轮对话后应当进记忆"""
    trunk.memory = {}
    _install_fake(trunk, FakeLLM("记住了"))
    trunk.reply("我的猫叫豆豆")
    mem = trunk.memory.get("tester") or []
    assert mem, "对话没有被记入记忆"
    assert any("豆豆" in str(x.get("u", "")) for x in mem), mem


def test_on_token_callback_receives_text(trunk):
    """流式回调应当被喂到内容"""
    _install_fake(trunk, FakeLLM("流式内容"))
    got = []
    trunk.reply("说点什么", on_token=lambda s: got.append(s))
    assert got, "on_token 一次都没被调用"
    assert any("流式内容" in str(x) for x in got)


# ---------------------------------------------------------------- 异常路径

def test_reply_survives_llm_exception(trunk):
    """模型抛异常时 reply() 不能把异常抛给界面"""
    _install_fake(trunk, FakeLLM(boom=True))
    try:
        r = trunk.reply("模型会炸")
    except Exception as e:                      # noqa: BLE001
        pytest.fail("reply() 把模型异常抛出来了: %s: %s" % (type(e).__name__, e))
    assert isinstance(r, str), "异常时也应返回字符串"


def test_reply_survives_empty_answer(trunk):
    """模型返回空串也不能崩"""
    _install_fake(trunk, FakeLLM(""))
    try:
        r = trunk.reply("空回复")
    except Exception as e:                      # noqa: BLE001
        pytest.fail("空回复导致异常: %s" % e)
    assert isinstance(r, str)


def test_reply_without_llm_module(trunk):
    """LLM 没装时应当给出可读提示，而不是崩"""
    trunk.modules.pop("llm", None)
    try:
        r = trunk.reply("没有模型")
    except Exception as e:                      # noqa: BLE001
        pytest.fail("缺 LLM 时抛异常: %s" % e)
    assert isinstance(r, str)
    # 还原，避免影响后面的用例
    _install_fake(trunk, FakeLLM("恢复"))


# ---------------------------------------------------------------- 指令拦截

def test_model_switch_command_intercepted(trunk):
    """/model 指令应当在进模型之前被拦截"""
    fake = _install_fake(trunk, FakeLLM("普通回复"))
    r = trunk.reply("/model qwen2.5:3b")
    assert isinstance(r, str)
    assert "qwen2.5:3b" in r, "切换指令没有被处理: %r" % r
    assert not fake.calls, "/model 指令不该发给模型"


# ---------------------------------------------------------------- 二次调用

def test_multiple_rounds_keep_working(trunk):
    """连续多轮不能因为状态残留而坏掉"""
    fake = _install_fake(trunk, FakeLLM("第 N 轮"))
    for i in range(3):
        r = trunk.reply("第 %d 轮提问" % (i + 1))
        assert isinstance(r, str) and r.strip(), "第 %d 轮返回空" % (i + 1)
    assert len(fake.calls) >= 3


# ---------------------------------------------------------------- 已知限制

def test_pipeline_disabled_after_error(trunk):
    """把当前行为钉住：pipeline 抛一次异常就永久降级到旧流程

    这是**实际行为**而非期望行为。core/trunk.py 的 _reply_inner 里：
        except Exception:
            self._use_pipeline = False     # 没有恢复机制
    后果是一次网络抖动 / 模型临时抽风，程序就永久走旧流程，直到重启。
    这里显式记录，改动时能立刻察觉。
    """
    assert trunk._use_pipeline is True
    _install_fake(trunk, FakeLLM(boom=True))
    trunk.reply("让它炸一次")
    assert trunk._use_pipeline is False, "当前实现应当已降级"

    # 降级之后仍然能正常回话（走旧流程），只是不再用 pipeline
    fake = _install_fake(trunk, FakeLLM("我恢复了"))
    r = trunk.reply("再试一次")
    assert isinstance(r, str) and r.strip()
    assert fake.calls, "旧流程也应当调用模型"


@pytest.mark.xfail(strict=False,
                   reason="期望 pipeline 能自动恢复；当前是永久降级（已知限制，见上一条）")
def test_pipeline_should_recover_after_error(trunk):
    """期望行为：模型恢复正常后，pipeline 应当重新启用而不是永久降级"""
    _install_fake(trunk, FakeLLM(boom=True))
    trunk.reply("炸一次")
    _install_fake(trunk, FakeLLM("好了"))
    trunk.reply("再试一次")
    assert trunk._use_pipeline is True
