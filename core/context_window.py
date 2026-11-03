# -*- coding: utf-8 -*-
"""上下文窗口与采样参数（第 2 批：聊天参数层）。

为什么单独一个模块
------------------
原来 ``num_ctx=4096`` 和 ``temperature=0.3/0.7`` 是硬编码在
``llm_local.py`` / ``llm_client.py`` 里的：换个模型窗口还是 4096（长对话
直接丢前文），想调温度只能改代码。这里把"取多少窗口 / 用哪档参数"
收成纯函数，本地与云端共用同一份口径，也方便离线单测。

三条规则
--------
1. **窗口 = min(用户配置, 模型能力, 显存估算)**：宁可小，不让 Ollama
   静默截断（用户看到的是"模型失忆"，日志里什么都没有）；
2. **参数 = 场景默认 ← 模型推荐 ← 用户覆盖**：代码 0.3 更准、闲聊 0.7
   更自然；用户在 ``llm_sampling`` 里写的永远最高优先级；
3. **seed 只在用户显式配了非 0 值时才透传**：默认不固定，避免所有回答
   一模一样（评测需要复现时才打开）。
"""
from __future__ import annotations

DEFAULT_WINDOW = 8192
MIN_WINDOW = 2048
MAX_WINDOW = 131072

# 每 GB 显存大约能撑的上下文 token 数（保守值，留给 KV cache 与权重）
TOKENS_PER_VRAM_GB = 2048

# 场景默认采样参数
DEFAULT_SAMPLING = {
    "chat": {"temperature": 0.7, "top_p": 0.95,
             "frequency_penalty": 0.0, "presence_penalty": 0.0},
    "code": {"temperature": 0.3, "top_p": 0.9,
             "frequency_penalty": 0.0, "presence_penalty": 0.0},
    "research": {"temperature": 0.5, "top_p": 0.9,
                 "frequency_penalty": 0.0, "presence_penalty": 0.0},
}

CODE_WORDS = ("代码", "bug", "报错", "函数", "python", "编程", "脚本",
              "程序", "错误", "修复", "补丁", "重构")
RESEARCH_WORDS = ("研究", "调研", "对比分析", "论文", "综述", "深度分析",
                  "竞品", "市场分析")

_PARAM_KEYS = ("temperature", "top_p", "frequency_penalty", "presence_penalty")

# 服务端认识的参数名（不支持的直接丢掉，避免请求被 400 拒绝）
_PROVIDER_PARAMS = {
    "openai": {"temperature": "temperature", "top_p": "top_p",
               "frequency_penalty": "frequency_penalty",
               "presence_penalty": "presence_penalty", "seed": "seed"},
    "azure": {"temperature": "temperature", "top_p": "top_p",
              "frequency_penalty": "frequency_penalty",
              "presence_penalty": "presence_penalty", "seed": "seed"},
    "anthropic": {"temperature": "temperature", "top_p": "top_p"},
    "gemini": {"temperature": "temperature", "top_p": "topP"},
}


def _to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp_window(value):
    return max(MIN_WINDOW, min(MAX_WINDOW, int(value)))


def configured_window(config, default=DEFAULT_WINDOW):
    """用户配置的窗口大小（支持中英文键名）。"""
    config = config or {}
    for key in ("llm_context_window", "上下文窗口", "num_ctx"):
        raw = config.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        got = _to_int(raw, 0)
        if got > 0:
            return _clamp_window(got)
    return _clamp_window(default)


def model_spec(model, catalog=None):
    """按模型名找注册表条目（精确 → 量化tag → 去 tag → 包含）。"""
    try:
        from core.model_registry import _spec_for
        return _spec_for(model, catalog)
    except Exception:  # 静默是故意的 - 注册表不可用时按"没有能力信息"处理
        return {}


def hardware_window_cap(spec):
    """按显存估算窗口上限；没有显存信息（云端模型）返回 0 = 不限。"""
    vram = spec.get("vram_gb")
    try:
        vram = float(vram or 0)
    except (TypeError, ValueError):
        return 0
    if vram <= 0:
        return 0
    return _clamp_window(int(vram * TOKENS_PER_VRAM_GB))


def effective_window(config, model="", catalog=None):
    """最终 num_ctx：min(配置, 模型能力, 显存估算)。"""
    want = configured_window(config)
    spec = model_spec(model, catalog)
    capacity = _to_int(spec.get("context"), 0)
    if capacity > 0:
        want = min(want, _clamp_window(capacity))
    hw = hardware_window_cap(spec)
    if hw > 0:
        want = min(want, hw)
    return _clamp_window(want)


def scene_of(text="", scene=""):
    """从用户原话判断场景；显式 scene 最高优先。"""
    if scene and scene in DEFAULT_SAMPLING:
        return scene
    low = str(text or "").lower()
    if any(k in low for k in CODE_WORDS):
        return "code"
    if any(k in low or k in str(text or "") for k in RESEARCH_WORDS):
        return "research"
    return "chat"


def sampling_for(config, text="", scene="", model="", catalog=None):
    """场景默认 ← 模型推荐 ← 用户覆盖，返回 4 个参数 + 可选 seed。"""
    config = config or {}
    use_scene = scene_of(text, scene)
    params = dict(DEFAULT_SAMPLING.get(use_scene) or DEFAULT_SAMPLING["chat"])
    # 模型推荐（只作兜底，不覆盖场景默认）
    try:
        from core.model_registry import recommended_params
        rec = recommended_params(model, use_scene, catalog=catalog)
    except Exception:  # 静默是故意的 - 注册表缺失时用场景默认
        rec = {}
    if isinstance(rec, dict):
        params.update({k: rec[k] for k in _PARAM_KEYS if k in rec})
    # 用户覆盖：llm_sampling[场景] / llm_sampling[default] / 顶层单键
    overrides = config.get("llm_sampling")
    if isinstance(overrides, dict):
        for bucket in (overrides.get(use_scene), overrides.get("default")):
            if isinstance(bucket, dict):
                params.update({k: bucket[k] for k in _PARAM_KEYS
                               if k in bucket})
    for key in _PARAM_KEYS:
        if key in config and config.get(key) is not None:
            params[key] = config[key]
    out = {}
    for key in _PARAM_KEYS:
        try:
            out[key] = round(float(params.get(key)), 4)
        except (TypeError, ValueError):
            out[key] = DEFAULT_SAMPLING["chat"][key]
    seed = _to_int(config.get("llm_seed"), 0)
    if seed:
        out["seed"] = seed
    return out


def ollama_options(params, window):
    """Ollama /api/chat 的 options 字段。"""
    out = {"num_ctx": _clamp_window(window)}
    for key in _PARAM_KEYS:
        if key in (params or {}):
            out[key] = params[key]
    if (params or {}).get("seed"):
        out["seed"] = params["seed"]
    return out


def cloud_options(params, provider=""):
    """云端请求体里的采样参数（按服务商做参数名映射 / 丢弃不支持项）。"""
    from core.llm_providers import normalize_provider
    key = normalize_provider(provider or "openai") if provider else "openai"
    allowed = _PROVIDER_PARAMS.get(key, _PROVIDER_PARAMS["openai"])
    out = {}
    for src, dst in allowed.items():
        value = (params or {}).get(src)
        if value is None:
            continue
        out[dst] = value
    return out
