# -*- coding: utf-8 -*-
"""数据目录的唯一入口：不要再自己拼 ``trunk.base + "data"``。

为什么单独一个文件
------------------
落盘路径散落在各处，很多地方直接拼 ``trunk.base``。而测试/自检把
``Trunk.data_dir`` 改到临时目录时，``base`` 仍指向**真实项目目录** ——
于是跑测试时真实管线把假对话写进了用户的真数据。2026-11-01 实测：

    data/chat_shadow.jsonl    983 行里混着「我的猫叫豆豆」「第 1 轮提问」
    data/errors_runtime.json  64 行「模拟模型故障」
    data/memory.json          userA / userB / checker / 回归 这些测试用户键

真实轮次随后读这些文件（近期话题、记忆卡、失败库建议、反思建议），
回复自然被带偏 —— 22:19 那条「我并没有情感…我是一个AI机器人」就是在这种
上下文里冒出来的。统一走 ``data_dir()``，测试只要重定向一次（要么改
``Trunk.data_dir``，要么让 conftest 调 ``set_data_dir``）就真的断干净，
不用挨个文件去补桩。
"""
import os

# 兜底的环境变量：临时跑批处理/评测时可以把**所有**数据落盘挪走，
# 连没接 `Trunk` 的脚本（工具、离线评测）也一起生效。
ENV_KEY = "X6_DATA_DIR"

# 测试进程内的全局重定向（conftest 每条用例设一次，用例结束清掉）。
# 只给测试用：生产代码没有任何地方会调 ``set_data_dir``。
_OVERRIDE = ""


def set_data_dir(path):
    """把所有"没绑定 Trunk"的数据落盘重定向到 ``path``（测试专用）。

    ⚠️ 死代码审计会把它和 ``clear_data_dir`` / ``plugin_dir`` 列成"零引用"，
    但这是**有意的公共入口**：测试/离线脚本按约定调它们做重定向，
    第三方插件按 ``plugin_dir()`` 约定找自己的持久化目录；不要删。
    """
    global _OVERRIDE
    _OVERRIDE = str(path or "")


def clear_data_dir():
    global _OVERRIDE
    _OVERRIDE = ""


def data_dir(target="."):
    """解析数据目录。

    优先级：``target.data_dir`` > 测试重定向 > 环境变量
    ``X6_DATA_DIR`` > ``target.base/data``。

    ``target`` 可以是 ``Trunk``、任何带 ``base`` 属性的对象，或者一个
    基路径字符串（老代码里 ``base`` 到处传）—— 三条都给同一个答案。
    """
    got = getattr(target, "data_dir", None)
    if isinstance(got, str) and got.strip():
        return got
    if _OVERRIDE:
        return _OVERRIDE
    env = os.environ.get(ENV_KEY, "").strip()
    if env:
        return env
    base = target if isinstance(target, str) else getattr(target, "base", ".")
    return os.path.join(str(base or "."), "data")


def data_path(target=".", *parts):
    """``data_dir(target)`` 下某个文件/子目录的完整路径。"""
    return os.path.join(data_dir(target), *parts)


def plugin_dir(target=".", name=""):
    """插件持久化目录 ``data/plugin_data/<插件名>``（v2.1 约定）。"""
    return os.path.join(data_dir(target), "plugin_data", str(name or ""))
