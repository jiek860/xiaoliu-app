# -*- coding: utf-8 -*-
"""配置管理 v2.0
升级：配置校验、配置导出、配置导入、配置重置
"""
import os
import json
from datetime import datetime

# 当前配置数据结构版本，以后改字段就+1
SCHEMA_VERSION = 2
DEFAULTS = {
    # ===== 模型 =====
    "model_mode": "本地路由",
    "local_model": "xiao6-7b:latest",
    "small_model": "xiao6-7b:latest",
    "cloud_model": "qwen-turbo",
    "ai_name": "Jarvis",
    "ollama_url": "http://localhost:11434",
    "module_server": "http://127.0.0.1:8899",
    # ===== 性能参数 =====
    "search_cache_sec": 300,
    "reflect_every": 5,
    "agent_max_steps": 10,
    "retrieval_top_k": 3,
    "simple_reply_max_len": 15,
    # ===== 超时参数 =====
    "llm_timeout": 60,
    "search_timeout": 10,
    "browser_timeout": 15,
    "code_exec_timeout": 10,
    "http_timeout": 20,
    # ===== 缓存参数 =====
    "vector_cache_size": 1000,
    "memory_max_items": 500,
    "chat_history_limit": 20,
    # ===== 其他 =====
    "max_tokens_reply": 500,
    "log_level": "info",
    # ===== UI参数 =====
    "chat_history_limit_simple": 3,  # 简单聊天只带3条历史
    "memory_unload_idle_sec": 300,  # 模块5分钟没用自动卸载
    "vector_preload": True,  # 启动时预加载向量库
    # ===== 功能开关 =====
    "联网": True,
    "工具调用": True,
    "电脑控制": True,
}


def load_config(path):
    """读配置，字段缺失补默认，类型错了回退默认"""
    cfg = {}
    if os.path.exists(path):
        try:
            cfg = json.load(open(path, encoding="utf-8"))
            if not isinstance(cfg, dict):
                cfg = {}
        except Exception:
            cfg = {}
    changed = False
    for k, v in DEFAULTS.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
        elif not isinstance(cfg[k], type(v)):
            cfg[k] = v
            changed = True
    if changed and os.path.exists(path):
        try:
            save_config(path, cfg)
        except Exception:
            pass
    return cfg


def save_config(path, config):
    """原子写：先写.tmp再os.replace，防止中途崩损坏配置"""
    _tmp = path + ".tmp"
    json.dump(config, open(_tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(_tmp, path)


def load_memory(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except:
            return {}
    return {"last_topic": ""}


def validate_config(cfg):
    """配置校验"""
    errors = []
    # 检查必填字段
    for k in DEFAULTS:
        if k not in cfg:
            errors.append(f"缺少字段: {k}")
    # 检查类型
    for k, v in DEFAULTS.items():
        if k in cfg and not isinstance(cfg[k], type(v)):
            errors.append(f"类型错误: {k} 应为 {type(v).__name__}")
    return {"有效": len(errors) == 0, "错误": errors}


def export_config(cfg, out_path=None):
    """导出配置"""
    if out_path is None:
        out_path = f"config_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return out_path


def import_config(path):
    """导入配置"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


def reset_config(path):
    """重置配置为默认"""
    save_config(path, DEFAULTS.copy())
    return DEFAULTS.copy()


def get_config_diff(cfg):
    """获取与默认配置的差异"""
    diff = {}
    for k, v in DEFAULTS.items():
        if k in cfg and cfg[k] != v:
            diff[k] = {"默认": v, "当前": cfg[k]}
    return diff




