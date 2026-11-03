# -*- coding: utf-8 -*-
"""配置管理 v2.0

职责边界（三套"配置读写"的分工，见 docs/30「加解密与配置读写的职责边界」）
--------------------------------------------------------------------------
* **本文件**：配置读写主入口 —— `load_config` / `save_config` / `validate_config`
  （敏感字段由 `core/secret_store` 加密，默认凭据由 `core/default_secrets` 解出）。
* `core/config_healer.py`：启动时修复**损坏/缺字段**的配置（healer = 修，不读业务值）。
* `core/data_migrations.py`：数据文件 schema 的版本迁移（migrate = 改格式，不碰配置语义）。

历史：这里曾有 export/import/reset/diff 四个"配置管理"helper，全项目无人调用，
统一配置管理走 `gui` 的导入导出（`Migration.import_zip` / 系统设置），2026-11-02 删除。
"""
import os
import json

from core.secret_store import decrypt_config, encrypt_config
from core.default_secrets import (
    decrypt_tree, get_default_feishu_secret, get_default_feishu_webhook)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



# 当前配置数据结构版本，以后改字段就+1
SCHEMA_VERSION = 2
DEFAULTS = {
    # ===== 模型 =====
    "model_mode": "本地路由",
    "local_model": "xiao6-7b:latest",
    "small_model": "xiao6-7b:latest",
    "cloud_model": "qwen-turbo",
    "cloud_provider": "",
    "ai_name": "Jarvis",
    "ollama_url": "http://localhost:11434",
    "module_server": "http://127.0.0.1:8899",
    # ===== 性能参数 =====
    "search_cache_sec": 300,
    "reflect_every": 5,
    "agent_max_steps": 10,
    "retrieval_top_k": 3,
    "simple_reply_max_len": 15,
    # ===== 聊天参数（第 2 批：可配置上下文窗口与采样）=====
    # 上下文窗口：实际生效值 = min(本项, 模型能力, 显存估算)，见 core/context_window.py
    "llm_context_window": 8192,
    # 上下文裁剪预算（token）与分渠道配额（system/persona/history/rag/tools）
    "context_token_budget": 6000,
    "llm_channel_shares": {},
    # 采样参数覆盖：{"chat": {"temperature": 0.7}, "code": {...}, "default": {...}}
    "llm_sampling": {},
    # 固定随机种子（0 = 不固定；评测复现时设成非 0）
    "llm_seed": 0,
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
    # ===== UI 模式 =====
    "ui_mode": "simple",
    "ui_mode_ever_switched": False,
    "show_advanced_entries": False,
    "shortcut_command_palette": "Ctrl+K",
    # 工作台"AI 写到哪个文件夹"：空 = 程序目录（gui.workbench_workspace 读写）
    "workbench_root": "",
    # ===== 功能开关 =====
    "联网": True,
    "工具调用": True,
    "电脑控制": True,
    "mcp_allow_dangerous_tools": False,
    "bot_allow_tools": False,
    "plugin_remote_install": False,
    "plugin_repo_allowlist": ["gitee.com", "raw.githubusercontent.com"],
    "plugin_repo_urls": [
        "https://gitee.com/cloud-drift/liuyun/raw/master",
        "https://raw.githubusercontent.com/jiek860/xiaoliu-app/main/plugin_repo",
    ],
    "security": {"network_mode": "standard", "permission_mode": "standard",
                 "lockdown": False, "allow_domains": [],
                 "audit_keep_days": 7, "trace_keep_days": 7},
    "task": {"max_steps": 8, "max_seconds": 300, "max_tokens": 20000},
    "task_auto_mode": "auto",
    "task_auto_wait_sec": 45,
    # ===== 通知通道（反馈/告警）=====
    "notify_channel": "feishu",
    # 默认通知凭据在源码中只保存 AES-GCM 密文；运行时才还原到内存。
    "feishu_webhook": get_default_feishu_webhook(),
    "feishu_secret": get_default_feishu_secret(),
    "wecom_webhook": "",
    "dingtalk_webhook": "",
    "dingtalk_secret": "",
    # 崩溃/闪退自动上报（默认开；关了就只写本地日志）
    "auto_report_crash": True,
    # 闪退看门狗子进程（默认开；关了就没有"闪退当场补发"）
    "crash_watchdog": True,
    # ===== 语音 =====
    # 自动朗读回复（+ 菜单里的开关）与朗读音色（edge-tts 的 ShortName，
    # 朗读 / 实时对话共用同一项；改了立刻生效）
    "auto_tts": False,
    "tts_voice": "zh-CN-XiaoxiaoNeural",
}


def load_config(path):
    """读配置，字段缺失补默认，类型错了回退默认"""
    cfg = {}
    if os.path.exists(path):
        try:
            raw = json.load(open(path, encoding="utf-8"))
            if isinstance(raw, dict):
                # 敏感字段（cloud_key / webhook / secret ）在这里解密
                cfg = decrypt_tree(decrypt_config(raw))
        except Exception:
            cfg = {}
    # Central team policy overrides local/user config keys.
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        central = os.path.join(base, "data", "team", "central_config.json")
        if os.path.isfile(central):
            extra = json.load(open(central, encoding="utf-8-sig"))
            if isinstance(extra, dict):
                cfg.update(extra)
    except Exception:  # 静默是故意的
        pass
    changed = False
    for k, v in DEFAULTS.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
        elif not isinstance(cfg[k], type(v)):
            cfg[k] = v
            changed = True
    # 敏感字段还是明文 -> 触发一次回写，把它换成 dpapi:v1:...
    _, _n_enc = encrypt_config(cfg)
    if _n_enc:
        changed = True
    if changed and os.path.exists(path):
        try:
            save_config(path, cfg)
        # 这里**该报**，不是静默（2026-10-13 按"用户路径"审计时改）。
        # 配置迁移补了默认值却写不回去，下次启动又是旧的 —— 用户看到的现象是
        # "改了设置、重启就没了"，而日志里什么都没有，根本查不出原因。
        except Exception as e:
            try:
                from core.logger import get_logger
                get_logger().warn("配置迁移后回写失败（本次仍用内存里的值，"
                                  "下次启动会退回旧配置）: %s: %s"
                                  % (type(e).__name__, str(e)[:70]))
            # 静默是故意的：连日志都写不进去时无处可报
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")
    return cfg


def save_config(path, config):
    """原子写：先写.tmp再os.replace。敏感字段在这里加密。"""
    enc, _n = encrypt_config(config)
    _tmp = path + ".tmp"
    json.dump(enc, open(_tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(_tmp, path)


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




