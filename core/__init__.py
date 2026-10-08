# -*- coding: utf-8 -*-
"""core 包初始化 - 核心模块汇总
导入所有核心模块，方便外部统一调用
"""

__version__ = "2.0.0"
__author__ = "小6智能体"

# 核心模块列表（与 core/ 目录实际文件对齐）
# 注意：plugin_market / mcp_client 等已迁到 modules/installed/，不在 core 里
CORE_MODULES = [
    # 躯干与配置
    "trunk",
    "lazy_config",
    "config",
    "logger",
    "safe",
    "crypto",
    "paths",
    "version",
    # 模型与检索
    "llm_client",
    "vector_store",
    "knowledge_graph",
    "graph_db",
    "rules_engine",
    "chat_store",
    # 授权与发布
    "license_core",
    "auth",
    "release_sign",
    "plugin_signer",
    # 服务
    "module_server",
    "backup",
    "perf",
    "cache",
]


def get_core_modules():
    """返回所有核心模块名"""
    return CORE_MODULES.copy()


def get_version():
    """返回版本号"""
    return __version__


def get_module_count():
    """返回核心模块数"""
    return len(CORE_MODULES)


def list_modules():
    """列出所有核心模块"""
    return {name: "核心模块" for name in CORE_MODULES}


def search_module(keyword):
    """搜索核心模块"""
    found = []
    for name in CORE_MODULES:
        if keyword in name:
            found.append(name)
    return found


def is_core_module(name):
    """检查是否是核心模块"""
    return name in CORE_MODULES
