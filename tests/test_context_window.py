# -*- coding: utf-8 -*-
"""上下文窗口与采样参数（第 2 批 A1 + A3 + 深度①③④⑤）的离线测试。

覆盖三条规则：
1. 窗口 = min(用户配置, 模型能力, 显存估算)；
2. 采样 = 场景默认 ← 模型推荐 ← 用户覆盖；
3. 服务商参数名映射（不支持的项要丢掉，否则请求会被 400）。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.context_window import (  # noqa: E402
    DEFAULT_WINDOW, MAX_WINDOW, MIN_WINDOW, cloud_options, configured_window,
    effective_window, hardware_window_cap, model_spec, ollama_options,
    sampling_for, scene_of)


def test_configured_window_reads_aliases_and_clamps():
    assert configured_window({}) == DEFAULT_WINDOW
    assert configured_window({"llm_context_window": 32768}) == 32768
    assert configured_window({"上下文窗口": 16384}) == 16384
    assert configured_window({"num_ctx": 4096}) == 4096
    # 太小/太大都要夹住：太小模型答不全，太大直接把显存打爆
    assert configured_window({"llm_context_window": 100}) == MIN_WINDOW
    assert configured_window({"llm_context_window": 999999}) == MAX_WINDOW
    # 脏数据（空串/非法值）不应该被当成 0 窗口
    assert configured_window({"llm_context_window": ""}) == DEFAULT_WINDOW
    assert configured_window({"llm_context_window": "abc"}) == DEFAULT_WINDOW


def test_model_spec_matches_exact_tag_and_partial():
    assert model_spec("qwen2.5:7b")["context"] == 32768
    assert model_spec("qwen2.5:7b-q4_K_M")["name"] == "qwen2.5:7b"
    assert model_spec("Qwen2.5-Coder:7B")["name"] == "qwen2.5-coder:7b"
    assert model_spec("完全未知的模型") == {}


def test_hardware_window_cap_uses_vram_and_ignores_cloud():
    assert hardware_window_cap({"vram_gb": 6}) == 6 * 2048
    # 云端模型没有显存信息 = 不设上限
    assert hardware_window_cap({"vram_gb": 0}) == 0
    assert hardware_window_cap({}) == 0


def test_effective_window_takes_minimum_not_maximum():
    # 用户想要 32768，模型支持 32768，但这台机器只有 6G 显存 → 12288
    assert effective_window({"llm_context_window": 32768}, "qwen2.5:7b") == 12288
    # 云端模型（vram 0）不受显存限制，用户配置说了算
    assert effective_window({"llm_context_window": 32768}, "glm-4-flash") == 32768
    # 用户配置比模型能力小 → 听用户的
    assert effective_window({"llm_context_window": 4096}, "glm-4-flash") == 4096


def test_scene_of_detects_code_and_research():
    assert scene_of("帮我修复这个 bug") == "code"
    assert scene_of("写个 python 脚本") == "code"
    assert scene_of("做一份竞品对比分析") == "research"
    assert scene_of("今天好累") == "chat"
    # 显式场景最高优先
    assert scene_of("帮我修 bug", scene="chat") == "chat"


def test_sampling_for_layers_scene_model_and_user():
    # 1) 代码场景默认更保守
    assert sampling_for({}, "帮我修复这个 bug")["temperature"] == 0.3
    # 2) 模型推荐覆盖场景默认（coder 模型代码场景 0.2）
    got = sampling_for({}, "帮我修复这个 bug", model="qwen2.5-coder:7b")
    assert got["temperature"] == 0.2
    # 3) 用户覆盖永远最高优先级
    cfg = {"llm_sampling": {"code": {"temperature": 0.9}}}
    assert sampling_for(cfg, "帮我修复这个 bug")["temperature"] == 0.9
    cfg2 = {"llm_sampling": {"default": {"top_p": 0.6}}}
    assert sampling_for(cfg2, "今天好累")["top_p"] == 0.6


def test_sampling_seed_only_when_configured():
    assert "seed" not in sampling_for({}, "你好")
    assert sampling_for({"llm_seed": 42}, "你好")["seed"] == 42
    # 0 = 不固定，不能把写死的 0 发出去（否则所有回答一模一样）
    assert "seed" not in sampling_for({"llm_seed": 0}, "你好")


def test_sampling_never_emits_non_numeric_values():
    cfg = {"llm_sampling": {"chat": {"temperature": "热一点"}}}
    got = sampling_for(cfg, "你好")
    assert isinstance(got["temperature"], float)


def test_ollama_options_carry_window_and_params():
    params = sampling_for({}, "帮我修复这个 bug")
    opts = ollama_options(params, 12288)
    assert opts["num_ctx"] == 12288
    assert opts["temperature"] == 0.3
    assert "top_p" in opts


def test_cloud_options_map_per_provider():
    params = {"temperature": 0.4, "top_p": 0.9,
              "frequency_penalty": 0.1, "presence_penalty": 0.1, "seed": 7}
    openai = cloud_options(params, "openai")
    assert openai["frequency_penalty"] == 0.1 and openai["seed"] == 7
    # anthropic 不认 penalty 和 seed，发过去直接 400
    anth = cloud_options(params, "anthropic")
    assert set(anth) == {"temperature", "top_p"}
    # gemini 的参数名是 topP
    gem = cloud_options(params, "gemini")
    assert "topP" in gem and "top_p" not in gem
    # 没配 provider 时按 OpenAI 兼容端处理
    assert cloud_options(params, "")["seed"] == 7
