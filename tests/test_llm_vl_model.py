# -*- coding: utf-8 -*-
"""带图请求必须走配置里的视觉模型（vl_model）

为什么单独一个文件
------------------
2026-10-27 排查发现：`LLMLocalMixin._vl_model()` 读的是 `local_model`，
配置里那个 `vl_model: qwen3-vl:8b` **从来没被用过**。
用户以为"设置了视觉模型"，实际带图请求发给的是纯文本主力模型 ——
模型要么报错、要么胡编，而错误信息里根本看不出是路由错了。

这条测试钉住三件事：
    ① vl_model 配了就一定用 vl_model
    ② 没配 / 配成空串时才退回 local_model
    ③ 带图消息在 _pick_model 里真的被路由到视觉模型
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))

from core.llm_local import LLMLocalMixin          # noqa: E402


def _obj(config):
    """造一个只带 config 的 mixin 实例（不连网、不建 Trunk）"""
    o = LLMLocalMixin()
    o.config = config
    return o


def test_vl_model_uses_configured_vl_model():
    o = _obj({"local_model": "xiao6-qwen3.5-4b:latest",
              "vl_model": "qwen3-vl:8b"})
    assert o._vl_model() == "qwen3-vl:8b"


def test_vl_model_falls_back_to_local_model():
    assert _obj({"local_model": "main:latest"})._vl_model() == "main:latest"
    # 空串/空白也算"没配"
    assert _obj({"local_model": "main:latest",
                 "vl_model": "   "})._vl_model() == "main:latest"


def test_vl_model_has_default_when_nothing_configured():
    assert _obj({})._vl_model() == "xiao6-qwen3.5-4b:latest"


def test_pick_model_routes_image_to_vl_model():
    """带图必须选视觉模型，而不是主力/小模型"""
    o = _obj({"local_model": "main:latest",
              "vl_model": "qwen3-vl:8b"})
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "这张图里是什么"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]}]
    assert o._has_image(msgs) is True
    assert o._pick_model(msgs) == "qwen3-vl:8b"
    # 不带图时不受影响：短消息走小模型
    assert o._pick_model("你好").endswith(":latest")


def _image_msg():
    return [{"role": "user", "content": [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]}]


def test_image_failure_goes_cloud_instead_of_text_model():
    """本地视觉模型不可用时，带图请求不能拿纯文本主力模型凑答案"""
    o = _obj({"local_model": "main:latest", "vl_model": "qwen3-vl:8b"})
    o.trunk = None
    tried = []

    def fake_local(msg, inject_persona=True):
        tried.append(o.config["local_model"])
        return "本地模型错误: model 'qwen3-vl:8b' not found"

    o._try_local = fake_local
    o._try_cloud = lambda msg: "云端看到的是一只猫"
    assert o._chat_local_route(_image_msg()) == "云端看到的是一只猫"
    assert tried == ["qwen3-vl:8b"], \
        "带图请求拿主力模型又试了一次（主力看不到图）：%s" % tried
    # 路由结束后要恢复原来的 local_model
    assert o.config["local_model"] == "main:latest"


def test_text_failure_still_falls_back_to_main_model():
    """不带图时保持原行为：路由模型挂了回退主力"""
    o = _obj({"local_model": "main:latest", "vl_model": "qwen3-vl:8b"})
    o.trunk = None
    tried = []

    def fake_local(msg, inject_persona=True):
        tried.append(o.config["local_model"])
        if len(tried) == 1:
            return "本地模型错误: 小模型没装"
        return "主力回答"

    o._try_local = fake_local
    o._try_cloud = lambda msg: "不该走云端"
    # 指定一个和主力不同的路由模型 → 失败后应回退主力，而不是直接上云
    assert o._chat_local_route("你好", force_model="small:latest") == "主力回答"
    assert tried == ["small:latest", "main:latest"], tried
    assert o.config["local_model"] == "main:latest"
