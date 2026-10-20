# -*- coding: utf-8 -*-
"""深度自检（core/self_check.py）

为什么这个文件重要
------------------
用户点「设置 → 系统 → 深度自检」时，期待的是"告诉我哪儿坏了"。
所以它的**准确性**比别处更要紧：

    · 报错了但没问题 → 用户白折腾
    · 没问题但没报 → 用户以为好了，实际坏着
    · **它自己崩掉** → 用户什么都不知道（最糟）

原来这个文件 383 语句 **0% 覆盖** —— 也就是说上面三种情况都没验过。
本文件给它补上：用假 trunk 指向临时小项目，让 26 项检查**真跑**，
再逐个注入问题，验证它真的报出来。
"""
import os
import shutil
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core import self_check                       # noqa: E402

# 一个"基本健康"的最小项目：语法对、模块合规、配置齐
GOOD_MODULE = (
    "from modules.base import BaseModule\n"
    "\n"
    "class M%s(BaseModule):\n"
    "    def run(self):\n"
    "        return {}\n"
    "\n"
    "    def reply(self, *a, **k):\n"
    "        return ''\n"
)


class FakeTrunk:
    """够 deep_check 用的最小 trunk

    ⚠️ 这几个属性是**试出来的**，不是猜的：
       第一版只给了 base/config/modules，跑起来报
       `AttributeError: 'Probe' object has no attribute 'data_dir'`；
       补上之后又发现还要 modules_dir / crash_path。
       所以下面都是"真跑到不报错"为止攒出来的。
    """

    def __init__(self, base, lazy=None):
        self.base = base
        self.data_dir = os.path.join(base, "data")
        self.modules_dir = os.path.join(base, "modules", "installed")
        self.crash_path = os.path.join(base, "data", "logs", "crashes.log")
        self.config = {"local_model": "qwen:test",
                       "ollama_url": "http://127.0.0.1:1"}
        self.modules = {}
        self._lazy = lazy if lazy is not None else {}
        self._process_start = 0

    def call(self, *a, **k):
        return {}

    def _log(self, m):
        pass

    def _disp(self, n):
        return n

    def _check_ollama(self):
        return {"ok": False, "error": "探针：连不上"}

    def _check_cloud(self):
        return {"ok": False, "error": "探针：未配置"}


def make_project(tmp_path, modules=("m1", "m2"), config=None,
                 good=True):
    """造一个最小项目；good=False 时不写那些"合规"文件"""
    b = str(tmp_path)
    for d in ("core", "modules/installed", "modules_repo", "gui",
              "data/logs", "backups", "staging"):
        os.makedirs(os.path.join(b, d), exist_ok=True)
    os.makedirs(os.path.join(b, "core", "realtime"), exist_ok=True)

    # modules/base.py
    open(os.path.join(b, "modules", "base.py"), "w",
         encoding="utf-8").write("class BaseModule:\n    pass\n")
    open(os.path.join(b, "modules", "__init__.py"), "w",
         encoding="utf-8").write("")
    # 核心模块（deep_check 要 core 里有这几个名字）
    for n in ("llm", "vector_store", "knowledge_graph", "auth", "backup",
              "trunk"):
        open(os.path.join(b, "core", n + ".py"), "w",
             encoding="utf-8").write("x = 1\n")
    open(os.path.join(b, "core", "__init__.py"), "w",
         encoding="utf-8").write("")
    # 插件模块
    for m in modules:
        open(os.path.join(b, "modules", "installed", m + ".py"), "w",
             encoding="utf-8").write(GOOD_MODULE % m[-1])
    open(os.path.join(b, "modules", "installed", "__init__.py"), "w",
         encoding="utf-8").write("")
    open(os.path.join(b, "run.py"), "w", encoding="utf-8").write("print(1)\n")

    cfg = {"local_model": "qwen:test", "ollama_url": "http://127.0.0.1:1"}
    if config:
        cfg.update(config)
    import json
    open(os.path.join(b, "config.json"), "w", encoding="utf-8").write(
        json.dumps(cfg))
    open(os.path.join(b, "data", "config.json"), "w",
         encoding="utf-8").write(json.dumps(cfg))
    # 数据文件（deep_check 会检查这几个在不在）
    for f in ("memory.json", "graph.json"):
        open(os.path.join(b, "data", f), "w",
             encoding="utf-8").write("{}")
    return b


@pytest.fixture
def proj(tmp_path):
    b = make_project(tmp_path)
    return b, FakeTrunk(b, lazy={"m1": ("m1", "M1", "模块一"),
                                 "m2": ("m2", "M2", "模块二")})


# ══════════════════════════════════════════════════════════════
# ① 四个小函数
# ══════════════════════════════════════════════════════════════
def test_health_score_all_ok():
    t = FakeTrunk(".", )
    t._check_ollama = lambda: {"ok": True, "models": []}
    t._check_cloud = lambda: {"ok": True}
    assert self_check.health_score(t) == 100


def test_health_score_deducts():
    """扣分规则：Ollama 不可用 -20，云端未配 -10"""
    t = FakeTrunk(".")
    t._check_ollama = lambda: {"ok": False, "error": "x"}
    t._check_cloud = lambda: {"ok": True}
    assert self_check.health_score(t) == 80

    t._check_ollama = lambda: {"ok": True, "models": []}
    t._check_cloud = lambda: {"ok": False, "error": "x"}
    assert self_check.health_score(t) == 90

    t._check_ollama = lambda: {"ok": False, "error": "x"}
    t._check_cloud = lambda: {"ok": False, "error": "x"}
    assert self_check.health_score(t) == 70


def test_health_score_never_crashes_on_empty_dict():
    """⚠️ 返回空 dict 也不能崩（见下面 test_deep_check_survives_* 的说明）"""
    t = FakeTrunk(".")
    t._check_ollama = lambda: {}
    t._check_cloud = lambda: {}
    assert self_check.health_score(t) == 70


def test_check_cloud_reports_not_configured():
    t = FakeTrunk(".")
    t.config = {}
    r = self_check.check_cloud(t)
    assert r["ok"] is False and r["error"] == "未配置"


def test_check_cloud_ok_when_configured():
    t = FakeTrunk(".")
    t.config = {"cloud_url": "https://x", "cloud_key": "k"}
    assert self_check.check_cloud(t)["ok"] is True


def test_check_ollama_unreachable_is_not_an_exception():
    """连不上要**返回错误**，不能抛 —— 它跑在自检里，抛了整份报告就没了"""
    t = FakeTrunk(".")
    t.config = {"ollama_url": "http://127.0.0.1:1"}
    r = self_check.check_ollama(t)
    assert r["ok"] is False
    assert r.get("error"), "没给出原因"


def test_warmup_never_raises():
    t = FakeTrunk(".")
    t.config = {"ollama_url": "http://127.0.0.1:1"}
    assert self_check.warmup_ollama(t) is None      # 失败也要静静返回


# ══════════════════════════════════════════════════════════════
# ② deep_check 基本行为
# ══════════════════════════════════════════════════════════════
def test_deep_check_returns_readable_report(proj):
    b, t = proj
    r = self_check.deep_check(t)
    assert isinstance(r, str) and len(r) > 200, "报告太短：%r" % r[:200]
    # 26 项检查里的关键字（抽查，不写死全部 —— 加检查项不该让这条失败）
    for k in ("深度自检报告", "语法", "Ollama", "云端", "健康分"):
        assert k in r, "报告里没有 %s：%s" % (k, r[:400])


def test_deep_check_never_raises_on_malformed_health(proj):
    """⚠️ **自检自己崩掉**是最糟的情况 —— 必须扛住畸形输入

    实测踩到：`_check_ollama()` 返回 `{"ok": False}`（**没有 error 键**）
    时，原代码写的是 `o["error"]` → KeyError → **整个自检挂掉**。

    用户点自检就是为了知道哪儿坏了，结果它自己先死了。
    已改成 `.get()`，这条钉住它。
    """
    b, t = proj
    t._check_ollama = lambda: {}                     # 空 dict
    t._check_cloud = lambda: {}
    r = self_check.deep_check(t)                     # 不许抛
    assert isinstance(r, str) and "深度自检" in r


def test_deep_check_survives_none_health(proj):
    """返回 None 也要扛住"""
    b, t = proj
    t._check_ollama = lambda: None
    t._check_cloud = lambda: None
    assert isinstance(self_check.deep_check(t), str)


# ══════════════════════════════════════════════════════════════
# ③ 负向：注入问题，验证真的报出来 —— **这才是重点**
# ══════════════════════════════════════════════════════════════
def test_detects_syntax_error(proj):
    """语法错必须报出来（这项对了，用户才知道程序为什么起不来）"""
    b, t = proj
    open(os.path.join(b, "core", "broken.py"), "w",
         encoding="utf-8").write("def f(:\n    pass\n")
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "语法" in l]
    assert line, "报告里没有语法这一行"
    assert "失败" in line[0] and "1" in line[0], \
        "注入了语法错却没报：%s" % line[0]


def test_detects_module_importing_module(proj):
    """⚠️ 星型拓扑：模块之间不许互相 import（架构的硬约束）

    这条是微核架构的底线 —— 模块互相 import 会让它们变成一张网，
    以后没法单独替换/卸载任何一个。
    """
    b, t = proj
    open(os.path.join(b, "modules", "installed", "m1.py"), "w",
         encoding="utf-8").write(
        "from modules.installed.m2 import M2\n"
        "from modules.base import BaseModule\n"
        "class M1(BaseModule):\n"
        "    def run(self):\n        return {}\n")
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "星型拓扑" in l]
    assert line, "报告里没有星型拓扑这一行"
    assert "✓" not in line[0], "模块互相 import 了却没报：%s" % line[0]
    assert "m1" in line[0], "报了但没说清是谁：%s" % line[0]


def test_allows_importing_core_from_module(proj):
    """反过来：模块 import core 是**合规的**，不能误报

    （踩过的坑：老版本的正则只要文件名出现在 import 行里就报违规，
      于是 `from core.realtime.tts import TTS` 被误判成
      realtime_chat.py→tts.py。那是导入 core，完全合规。）
    """
    b, t = proj
    open(os.path.join(b, "modules", "installed", "m1.py"), "w",
         encoding="utf-8").write(
        "from core.safe import safe\n"
        "from modules.base import BaseModule\n"
        "class M1(BaseModule):\n"
        "    def run(self):\n        return {}\n")
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "星型拓扑" in l]
    assert line and "✓" in line[0], \
        "导入 core 被误报成模块互相 import：%s" % (line[0] if line else "?")


def test_detects_key_leak_in_log(proj):
    """日志里出现 API Key 必须报出来（这是安全事故，不是小毛病）"""
    b, t = proj
    open(os.path.join(b, "data", "logs", "app.log"), "w",
         encoding="utf-8").write(
        "[INFO] 调用云端\n[DEBUG] header=sk-abcdef123456\n")
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "密钥泄漏" in l]
    assert line, "报告里没有密钥泄漏这一行"
    assert "0处" not in line[0], "日志里有 sk- 却没报：%s" % line[0]


def test_no_key_leak_reports_zero(proj):
    b, t = proj
    open(os.path.join(b, "data", "logs", "app.log"), "w",
         encoding="utf-8").write("[INFO] 一切正常\n")
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "密钥泄漏" in l]
    assert line and "0处" in line[0], \
        "干净日志被误报：%s" % (line[0] if line else "?")


def test_detects_missing_config_keys(proj):
    """关键配置缺失要报（用户没配模型却不知道，会一直问"为什么不能用"）"""
    b, t = proj
    t.config = {}
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "⚙️ 配置" in l]
    assert line, "报告里没有配置这一行"
    assert "❌" in line[0] or "缺" in line[0], \
        "配置全空却没报：%s" % line[0]


def test_detects_missing_data_files(proj):
    """数据文件缺失要报（少了 memory.json = 它的记忆没了）"""
    b, t = proj
    os.remove(os.path.join(b, "data", "memory.json"))
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "数据文件" in l]
    assert line, "报告里没有数据文件这一行"
    assert "memory.json" in line[0], \
        "删了 memory.json 却没报：%s" % line[0]


def test_detects_hardcoded_path(proj):
    """硬编码路径要报（换台机器就路径不对）"""
    b, t = proj
    # deep_check 数的是"行里出现 base 路径且不含 trunk.base 字样"
    escaped = b.replace("\\", "\\\\")
    open(os.path.join(b, "core", "hard.py"), "w",
         encoding="utf-8").write('P = r"%s"\n' % escaped)
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "硬编码路径" in l]
    assert line, "报告里没有硬编码路径这一行"
    assert "0处" not in line[0], "硬编码了却没报：%s" % line[0]


def test_health_score_reflects_problems(proj):
    """健康分要落在 0~100（它是个总指标，越界就说明逻辑错了）"""
    b, t = proj
    r = self_check.deep_check(t)
    line = [l for l in r.splitlines() if "健康分" in l]
    assert line, "报告里没有健康分"
    import re
    m = re.search(r"(\d+)", line[0])
    assert m, "健康分不是数字：%s" % line[0]
    assert 0 <= int(m.group(1)) <= 100, "健康分越界：%s" % line[0]


# ══════════════════════════════════════════════════════════════
# ④ 和 trunk 的接线（deep_check 是 trunk._deep_check 的委托）
# ══════════════════════════════════════════════════════════════
def test_trunk_delegates_to_self_check():
    """⚠️ `trunk._deep_check()` 必须还在 —— GUI 直接调它、测试打桩它

    搬出去的时候特意保留了同名委托，这条钉住它别再被删。
    """
    from core.trunk import Trunk
    assert hasattr(Trunk, "_deep_check"), \
        "trunk._deep_check 没了 —— gui/system_dialog.py 会调不到"
    src = open(os.path.join(BASE, "core", "trunk_background.py"),
               encoding="utf-8").read()
    assert "self_check" in src, "trunk 后台 mixin 没引用 self_check"


def test_warmup_delegation_still_patchable():
    """4 个测试用 mock.patch.object(Trunk, "_warmup_ollama") 打桩 —— 名字得在"""
    from core.trunk import Trunk
    assert hasattr(Trunk, "_warmup_ollama"), \
        "trunk._warmup_ollama 没了 —— 打桩的测试会失败"
