# -*- coding: utf-8 -*-
"""测试公共设施

最重要的一条：**造 Trunk 之前一定要屏蔽后台服务**。

`Trunk.__init__` 之后 3 秒，`_start_background` 会在后台线程里：
    · 起 module_server(8899) / mobile_remote(8765) / 本地工具服务(3742)
    · 真去连 config.json 里配置的 MCP 服务器 —— 会拉起 npx / uvx 子进程
    · 跑 ollama 预热（发网络请求）和自动备份（写盘）

测试里既不该占端口、不该拉起外部进程、也不该连网络，否则：
    · 慢，而且行为依赖本机装了什么（比如有没有配 MCP 服务器）
    · 后台连接会在任意时刻冒出来，让"活连接数"之类的断言变得不可靠
      （实际踩到过：一条断言 live_count() 的用例被后台拉起的 MCP 连接搞挂）
所以统一用下面的 fixture 造 Trunk。
"""
import os
import sys
import unittest.mock as mock

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# ── 崩溃现场捕获（对整个测试会话生效）──
# 为什么装在测试里：2026-10-13 那次 access violation **就是跑全量测试时出的**
# （退出码 3221225477），之后怎么跑都不复现。没有现场就永远定不了位。
#
# pytest 自己的报告抓不到 C 层崩溃 —— 进程直接死，连 teardown 都跑不到。
# faulthandler 能在死之前把所有线程的 Python 栈写进：
#     data/logs/faulthandler.log
# 下次再崩，第一件事就是去看那个文件的末尾。
try:
    from core.crash_guard import enable as _enable_crash_guard
    _enable_crash_guard()
except Exception:
    pass

# 需要屏蔽掉的后台入口（Trunk.__init__ 里是用 Thread 起它们的）
_BACKGROUND = (
    "_start_background",     # 定时任务 / 热更新 / 模块服务器 / 手机远程 / MCP / 预热
    "_warmup",               # 模型预热
    "_warmup_ollama",        # 会去请求 Ollama
    "_auto_unload_loop",     # 常驻卸载循环
)


def make_trunk():
    """造一个屏蔽了后台服务的 Trunk（模块注册、配置、pipeline 都是真的）"""
    from core.trunk import Trunk
    patchers = [mock.patch.object(Trunk, name, lambda self: None)
                for name in _BACKGROUND]
    for p in patchers:
        p.start()
    try:
        return Trunk()
    finally:
        for p in patchers:
            p.stop()


@pytest.fixture
def quiet_trunk():
    """测试用：屏蔽后台服务的 Trunk 工厂"""
    return make_trunk
