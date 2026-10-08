# -*- coding: utf-8 -*-
"""回归测试：模型配置自检（core/model_setup.py）

这是"朋友打开后问它话没反应"的第一道防线，逻辑不能退化。
不依赖 Qt、不依赖密钥库；本地模式的探测一律指向一个必然连不上的端口，保证确定性。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import model_setup  # noqa: E402

DEAD = "http://127.0.0.1:1"          # 必然连不上，且会立刻被拒绝，不会等超时


class FakeTrunk:
    def __init__(self, cfg):
        self.config = cfg
        self.saved = 0

    def save_config(self):
        self.saved += 1
        return True


def test_cloud_mode_without_key_is_not_ready():
    t = FakeTrunk({"model_mode": "云端模型",
                   "cloud_url": "https://example.com/v1/chat",
                   "cloud_key": "",
                   "ollama_url": DEAD})
    r = model_setup.check(t)
    assert r["ready"] is False
    assert any("API Key" in p for p in r["problems"]), r["problems"]
    assert "云端" in r["advice"] or "Key" in r["advice"]


def test_cloud_mode_without_url_is_not_ready():
    t = FakeTrunk({"model_mode": "云端模型", "cloud_url": "",
                   "cloud_key": "x" * 30, "ollama_url": DEAD})
    r = model_setup.check(t)
    assert r["ready"] is False
    assert any("地址" in p for p in r["problems"]), r["problems"]


def test_cloud_mode_complete_is_ready():
    t = FakeTrunk({"model_mode": "云端模型",
                   "cloud_url": "https://example.com/v1/chat",
                   "cloud_key": "x" * 30,
                   "ollama_url": DEAD})
    r = model_setup.check(t)
    assert r["ready"] is True, r["problems"]
    assert r["problems"] == []
    # 纯云端模式不应去探 Ollama
    assert r["ollama"]["reachable"] is False
    assert "未检测" in r["ollama"]["error"]


def test_local_mode_without_ollama_is_not_ready():
    t = FakeTrunk({"model_mode": "本地模型", "local_model": "qwen2.5:3b",
                   "ollama_url": DEAD})
    r = model_setup.check(t)
    assert r["ready"] is False
    assert any("连不上" in p for p in r["problems"]), r["problems"]
    assert model_setup.OLLAMA_DOWNLOAD in r["advice"]


def test_probe_ollama_never_raises():
    info = model_setup.probe_ollama(DEAD, timeout=2)
    assert info["reachable"] is False
    assert isinstance(info["models"], list)
    assert info["error"]


def test_apply_local_writes_config():
    t = FakeTrunk({"model_mode": "云端模型", "local_model": "", "small_model": "",
                   "ollama_url": ""})
    assert model_setup.apply_local(t, url=DEAD, model="qwen2.5:3b") is True
    assert t.config["model_mode"] == "本地模型"
    assert t.config["ollama_url"] == DEAD
    assert t.config["local_model"] == "qwen2.5:3b"
    assert t.config["small_model"] == "qwen2.5:3b"     # 小模型跟着一起改
    assert t.saved == 1


def test_apply_cloud_does_not_clear_existing_key():
    """只改地址时不应当把已填的 Key 清空"""
    t = FakeTrunk({"model_mode": "本地模型", "cloud_key": "old-key",
                   "cloud_url": "", "cloud_model": ""})
    model_setup.apply_cloud(t, url="https://example.com/v1", model="glm-4-flash")
    assert t.config["cloud_key"] == "old-key"
    assert t.config["cloud_url"] == "https://example.com/v1"
    assert t.config["model_mode"] == "云端模型"


def test_apply_cloud_sets_key_when_given():
    t = FakeTrunk({"model_mode": "本地模型", "cloud_key": "",
                   "cloud_url": "", "cloud_model": ""})
    model_setup.apply_cloud(t, key="new-key")
    assert t.config["cloud_key"] == "new-key"
