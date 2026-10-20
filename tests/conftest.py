# -*- coding: utf-8 -*-
"""测试公共设施

最重要的一条：**造 Trunk 之前一定要屏蔽后台服务**。

`Trunk.__init__` 之后 3 秒，`_start_background` 会在后台线程里：
    · 起 module_server(8899) / 本地工具服务(3742)
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
    "_start_background",     # 定时任务 / 热更新 / 模块服务器 / MCP / 预热
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


# ══════════════════════════════════════════════════════════════
# CI 跳过助手：依赖"本机状态"的测试在干净检出上要 **skip**，不是 fail
# ══════════════════════════════════════════════════════════════
# 为什么需要这组东西（2026-10-14 实测）：
#   把一个干净 checkout 拿去跑，结果是 **41 failed / 817 passed**。
#   那 41 条**几乎全是"依赖本机才有、而 git 里没有的东西"**：
#
#       modules_repo/    不提交（独立 git 仓库），但没有它
#                        module_caps 只认 core_caps 那 19 条能力
#                        （本地是 44 条）→ 一堆能力测试报"不在能力表里"
#       data/            不提交（有隐私），缺 data/_schema.json 就报"登记不完整"
#       optional_libs/   不提交（1 GB），缺了 dist 体积算不出来
#       data/tools/procdump.exe   下载来的二进制，被 .gitignore 排除
#       data/logs/*.log  运行过才有
#
# **正确做法是 skip 而不是 fail**：这些测试要验的是"本机装好了没有"，
# 不是"代码对不对"。在没装这些东西的机器上，它们本来就**没有可验的对象**。
# 硬让它 fail 的话，CI 永远是红的，大家就学会无视 CI 了 —— 那比没有 CI 更糟。
#
# ⚠️ 但要小心别用过头：**跳过的必须是"前置条件不存在"，
#    不能是"这个测试我觉得会失败"**。所以每个 skip 都写明了缺什么、
#    以及怎么补上（这样本机缺了也能一眼看出该装什么）。

def _has(base, *parts):
    return os.path.exists(os.path.join(base, *parts))


def requires_manifest():
    """需要 modules_repo/manifest.json（能力表靠它知道扫哪些模块）

    补法：`py -3 tools/rebuild_modules_repo.py --apply`
         （**不需要签名密钥** —— 它只重建清单，签名是另一步）
    """
    if not _has(BASE, "modules_repo", "manifest.json"):
        pytest.skip("没有 modules_repo/manifest.json —— 跑 "
                    "`py -3 tools/rebuild_modules_repo.py --apply` 生成"
                    "（CI 上要先跑这一步）")


def requires_data(*names):
    """需要 data/ 下的某些文件（有隐私，不提交）

    例：`requires_data("_schema.json")`
    """
    for n in names:
        if not _has(BASE, "data", n):
            pytest.skip("没有 data/%s —— 数据文件不提交（含隐私），"
                        "本机跑过一次程序就会有" % n)


def requires_manifest_and_data(*names):
    """形状快照**同时**依赖 modules_repo/manifest.json 和 data/ 下的文件

    快照里既有 manifest.count / manifest.keys，也有
    data.{config.json,memory.json,graph.json,chats.db,vectors.db} 的形状 ——
    两边缺一个都会让 test_no_shape_drift_from_snapshot 误报漂移。
    """
    requires_manifest()
    requires_data(*names)


def requires_optional_libs():
    """需要 optional_libs/（1 GB，不提交）

    补法：`scripts\\install_optional.bat`
    """
    if not os.path.isdir(os.path.join(BASE, "optional_libs")):
        pytest.skip("没有 optional_libs/ —— 跑 scripts\\install_optional.bat 装"
                    "（CI 上不装，跳过）")


def requires_local_tool(*names):
    """需要下载来的本地工具（被 .gitignore 排除）

    例：`requires_local_tool("procdump.exe")`
    """
    for n in names:
        if not _has(BASE, "data", "tools", n):
            pytest.skip("没有 data/tools/%s —— 跑 "
                        "`py -3 tools/setup_crash_dumps.py --procdump` 下载" % n)


def requires_logs(*names):
    """需要运行过才有日志文件

    ⚠️ 目前**没有 consumer**（2026-10-14 起）：
       test_crash_guard 里的日志用例都用 tmp_path 自建日志，
       不读真实 data/logs/。留着给将来"真的要读真实日志"的测试用。
    """
    for n in names:
        p = os.path.join(BASE, "data", "logs", n)
        if not (os.path.exists(p) and os.path.getsize(p) > 0):
            pytest.skip("没有 data/logs/%s —— 跑过一次程序才会有" % n)


# ══════════════════════════════════════════════════════════════
# 集中式的跳过规则表
# ══════════════════════════════════════════════════════════════
# ⚠️ 为什么用"一张表 + 一个 hook"，而不是在每个测试函数里插一句
#    `requires_xxx()`：
#    我先试过后一种 —— 写脚本往 7 个测试文件里插调用，
#    结果脚本的 docstring 跳过逻辑有 bug，**把几个函数的 docstring
#    开头行删掉了**（`"""⚠️ 默认不能用 ...`），直接语法错。
#    测试文件是"人写的文档 + 代码"，**不该用正则去动它**。
#    集中到这一个表里，改的是数据不是别人文件的结构，
#    出问题也只在这一个地方。
#
# 规则格式：(文件名, 测试名包含的子串 或 None=整个文件, 检查函数)
_SKIP_RULES = [
    # modules_repo 不在 git 里 —— CI 上必须先跑 rebuild_modules_repo.py
    ("test_capabilities.py", None, requires_manifest),
    ("test_shapes.py", "manifest", requires_manifest),
    # ⚠️ 名字里没有 "manifest"，但它**同时**依赖 manifest 和 data/：
    #    快照里含 manifest.count 和 data/{config,memory,graph,chats,vectors}
    #    的形状 —— 没 data/ 就漂移。
    #    （2026-10-14 修：原来只查 requires_manifest，干净检出上 5 个
    #      data.* 键全变 {"kind":"absent"} → 该测试仍然红。）
    ("test_shapes.py", "no_shape_drift", lambda: requires_manifest_and_data(
        "config.json", "memory.json", "graph.json", "chats.db", "vectors.db")),
    ("test_module_map.py", "registry_driven", requires_manifest),
    # data/ 有隐私不提交
    ("test_data_schema.py", "real_project", lambda: requires_data(
        "_schema.json")),
    # optional_libs 1 GB 不提交
    ("test_optional_deps.py", "distribution_hint",
     requires_optional_libs),
    # procdump 是下载来的，被 .gitignore 排除
    ("test_crash_dumps.py", None, lambda: requires_local_tool(
        "procdump.exe")),
    # ⚠️ 2026-10-14 删了一条 ("test_crash_guard.py", "recent_crashes", ...)：
    #    它匹配到的 test_recent_crashes_reads_tail / _missing_file_is_empty
    #    全都**自建日志**（tmp_path / 不存在的路径），不读真实
    #    data/logs/faulthandler.log；而 conftest 自己会 enable() 先把日志
    #    建出来，所以那条规则实际从不触发 —— 属于埋雷：crash_guard 装不上时
    #    会误 skip 这两条自包含用例（其中一条是 2026-10-14 刚修的）。
]


def pytest_collection_modifyitems(config, items):
    """按上面的表，给"前置条件不存在"的用例打上 skip

    ⚠️ 只跳"前置条件不存在"，**不跳"我觉得会失败"** ——
    后者是掩盖问题，比不跳更糟。
    """
    for item in items:
        fname = os.path.basename(str(getattr(item, "fspath", "")))
        for rule_file, needle, check in _SKIP_RULES:
            if fname != rule_file:
                continue
            if needle and needle not in item.name:
                continue
            try:
                check()
            except pytest.skip.Exception as e:
                item.add_marker(pytest.mark.skip(reason=str(e)))
            break


# 
# 测试里不要弹「用户协议 / 隐私政策」模态框
# 
# 为什么：JarvisWindow.__init__ 里如果 Agreement.need_show() 为真，
# 会 exec_() 一个模态框等你点「同意」。测试环境里没人点，
# 于是 __init__ 提前 return，**后面的控件和 Ctrl+K 快捷键全都不初始化** 
# 表现出来就是 test_main_window_assembles 报「Ctrl+K 快捷键没装上」。
# 协议版本一升级（3.0 -> 3.1）这个坑就会复现一次。
#  必须是 session 级：模块级的 fixture（比如 test_ui_responsiveness 的 win）
# 会在**函数级** autouse 之前构造主窗口  函数级桩来不及生效，
# 主窗口就会真弹协议框并 exec_() 卡死（实测 pytest 停在 collected 不动）。
@pytest.fixture(autouse=True, scope="session")
def _no_agreement_dialog():
    mp = pytest.MonkeyPatch()
    try:
        from core.agreement import Agreement
        mp.setattr(Agreement, "need_show", lambda self: False)
    except ImportError:
        pass
    yield
    mp.undo()
