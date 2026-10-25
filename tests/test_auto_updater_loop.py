# -*- coding: utf-8 -*-
"""自动更新（modules/installed/auto_updater.py）—— 自更新闭环部分

接在 test_auto_updater.py 的思路后面：这里测**闭环的每一步**，
以及**每一步失败时它退不退得出来**。

这个闭环的设计是"六步任意一步失败就停，绝不带着坏状态往下走"：
    ① 收问题 → ② 出建议 → ③ 打补丁 → ④ 沙盒验证
    → ⑤ 用户确认 → ⑤.5 规则开关 → ⑥ 备份+部署+回滚

**每一道闸都得单独验**：只要有一道能绕过去，用户就可能拿到一个
改坏了的程序，而且不知道是怎么坏的。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from modules.installed.auto_updater import AutoUpdater   # noqa: E402


class FakeTrunk:
    def __init__(self, base, calls=None, rules=None, modules=None):
        self.base = base
        self.modules = modules or {}
        self.logs = []
        self._calls = calls or {}
        self._rules = rules or {}
        self._lazy = {}

    def call(self, name, method, *a):
        k = "%s.%s" % (name, method)
        if k in self._calls:
            v = self._calls[k]
            if isinstance(v, Exception):
                raise v
            return v
        return {}

    def rule(self, key, default=None):
        return self._rules.get(key, default)

    def confirm(self, title, text):
        return self._calls.get("_confirm", True)

    def _log(self, m):
        self.logs.append(m)


@pytest.fixture
def mk(tmp_path):
    def _mk(**kw):
        t = FakeTrunk(str(tmp_path), **kw)
        u = AutoUpdater(t)
        u.base = str(tmp_path)
        u.staging = os.path.join(str(tmp_path), "staging")
        u.backup_dir = os.path.join(str(tmp_path), "backups")
        u.patch_dir = os.path.join(u.staging, "patches")
        for d in (u.staging, u.backup_dir, u.patch_dir,
                  os.path.join(u.base, "core"),
                  os.path.join(u.base, "modules", "installed"),
                  os.path.join(u.base, "modules_repo")):
            os.makedirs(d, exist_ok=True)
        return u
    return _mk


class FakeLLM:
    def __init__(self, reply="", raise_it=False):
        self.reply = reply
        self.raise_it = raise_it
        self.prompts = []

    def chat(self, prompt):
        self.prompts.append(prompt)
        if self.raise_it:
            raise RuntimeError("模型炸了")
        return self.reply


class StagedLLM:
    """第一次回"建议"，第二次回"代码"

    ⚠️ 闭环里 `llm.chat` 会被调**两次**，用途完全不同：
        第 1 次 —— 出更新建议（要的是"目标模块: x.py"这种文本）
        第 2 次 —— 打补丁（要的是**完整 Python 代码**）
    用同一个 FakeLLM 两次都回文本的话，补丁内容就是"目标模块: m.py"
    那两行 —— 它不是合法可执行的代码（注解语句在 import 时求值，
    `m.py` 那个表达式直接 NameError），沙盒会正确地判它失败。

    **第一版就是这么写的**，三条用例红在"沙盒验证失败"上，
    一度以为是沙盒坏了 —— 其实是假件没分清两次调用的用途。
    """

    def __init__(self, suggestion, code):
        self.suggestion = suggestion
        self.code = code
        self.prompts = []

    def chat(self, prompt):
        self.prompts.append(prompt)
        # 打补丁的提示词里带"你是编程小匠"
        return self.code if "编程小匠" in prompt else self.suggestion


# ══════════════════════════════════════════════════════════════
# ① 收集问题
# ══════════════════════════════════════════════════════════════
def test_collect_problems_from_error_lib(mk):
    u = mk(calls={"error_lib.list": {"未修复": 7}})
    p = u.collect_problems()
    assert any("7" in x for x in p), p


def test_collect_problems_error_lib_raises(mk):
    """读错误库失败要**记成一条问题**，不是抛出去

    （自更新的第一步就崩，用户看到的是"点了没反应"。）
    """
    u = mk(calls={"error_lib.list": RuntimeError("库坏了")})
    p = u.collect_problems()
    assert any("失败" in x for x in p), p


def test_collect_problems_self_reflect(mk):
    u = mk(calls={"error_lib.list": {"未修复": 0},
                  "self_reflect.get_history": {"历史": [1, 2, 3]}})
    p = u.collect_problems()
    assert any("3" in x for x in p), p


def test_collect_problems_empty_is_fine(mk):
    u = mk()
    assert isinstance(u.collect_problems(), list)


# ══════════════════════════════════════════════════════════════
# ② 出建议
# ══════════════════════════════════════════════════════════════
def test_build_suggestion_without_llm(mk):
    u = mk()
    r = u.build_suggestion(["有问题"])
    assert r["目标模块"] == "", r
    assert "LLM" in r["建议"], r


def test_build_suggestion_parses_format(mk):
    llm = FakeLLM("目标模块: 记忆.py\n建议: 加快检索\n理由: 太慢")
    u = mk(modules={"llm": llm})
    r = u.build_suggestion(["记忆慢"])
    assert r["目标模块"] == "记忆.py", r
    assert r["建议"] == "加快检索", r


def test_build_suggestion_fullwidth_colon(mk):
    """中文冒号也要认（模型经常输出全角）"""
    llm = FakeLLM("目标模块：记忆.py\n建议：加快检索")
    u = mk(modules={"llm": llm})
    r = u.build_suggestion(["x"])
    assert r["目标模块"] == "记忆.py", r


def test_build_suggestion_llm_raises(mk):
    u = mk(modules={"llm": FakeLLM(raise_it=True)})
    r = u.build_suggestion(["x"])
    assert "失败" in r["建议"], r
    assert r["目标模块"] == ""


def test_build_suggestion_unparsable_keeps_raw(mk):
    """模型没按格式回 -> 人话里保留原文（别丢信息）"""
    u = mk(modules={"llm": FakeLLM("我觉得应该优化一下")})
    r = u.build_suggestion(["x"])
    assert r["建议"], r


# ══════════════════════════════════════════════════════════════
# ③ 打补丁
# ══════════════════════════════════════════════════════════════
def test_gen_patch_without_llm(mk):
    u = mk()
    assert u.gen_patch("建议", "x.py")["ok"] is False


def test_gen_patch_writes_file_and_strips_fence(mk):
    """⚠️ 要去掉 ```python 围栏

    模型很喜欢把代码包在围栏里。不去掉的话补丁文件开头是 ```python，
    `py_compile` 直接语法错 —— 表现为"沙盒验证失败"，
    但真正的原因在提示词输出格式上，很难查。
    """
    u = mk(modules={"llm": FakeLLM("```python\nx = 1\n```")})
    r = u.gen_patch("建议", "mod1.py")
    assert r["ok"] is True, r
    body = open(r["补丁"], encoding="utf-8").read()
    assert not body.startswith("```"), "围栏没去掉：%r" % body[:30]
    assert "x = 1" in body


def test_gen_patch_llm_raises(mk):
    u = mk(modules={"llm": FakeLLM(raise_it=True)})
    assert u.gen_patch("建议", "mod1.py")["ok"] is False


def test_gen_patch_includes_old_source(mk):
    """提示词里要带上现有代码 —— 不带的话模型会瞎编，删掉已有方法"""
    p = os.path.join(BASE, "modules", "installed", "mod_old.py")
    u = mk(modules={"llm": FakeLLM("x = 1\n")})
    open(os.path.join(u.base, "modules", "installed", "mod_old.py"),
         "w", encoding="utf-8").write("原来 = '这段要被参考'\n")
    try:
        u.gen_patch("建议", "mod_old.py")
        prompt = u.trunk.modules["llm"].prompts[0]
        assert "这段要被参考" in prompt, "提示词里没带现有代码"
    finally:
        if os.path.exists(p):
            os.remove(p)


# ══════════════════════════════════════════════════════════════
# ④ 全程序检查 / 沙盒验证
# ══════════════════════════════════════════════════════════════
def test_run_health_checks_counts_files(mk):
    u = mk()
    open(os.path.join(u.base, "core", "a.py"), "w",
         encoding="utf-8").write("x = 1\n")
    p, t, fails = u.run_health_checks()
    assert t >= 1 and p == t and not fails, (p, t, fails)


def test_run_health_checks_reports_syntax_error(mk):
    """⚠️ 有语法错必须**报出来并计入失败**

    这是"部署前最后一道全量检查" —— 它漏了的话，补丁把别的文件
    弄坏了也不会被发现（热重载时才炸，用户就起不来了）。
    """
    u = mk()
    open(os.path.join(u.base, "core", "a.py"), "w",
         encoding="utf-8").write("x = 1\n")
    open(os.path.join(u.base, "core", "bad.py"), "w",
         encoding="utf-8").write("def f(:\n    pass\n")
    p, t, fails = u.run_health_checks()
    assert fails, "有语法错却没报"
    assert any("bad.py" in f for f in fails), fails
    assert p < t, (p, t)


def test_sandbox_missing_patch(mk):
    u = mk()
    ok, msg = u.sandbox_verify_patch(os.path.join(u.staging, "没有这个.py"))
    assert ok is False and "不存在" in msg, msg


def test_sandbox_bad_syntax(mk):
    u = mk()
    p = os.path.join(u.staging, "bad.py")
    open(p, "w", encoding="utf-8").write("def f(:\n")
    ok, msg = u.sandbox_verify_patch(p)
    assert ok is False and "语法" in msg, msg


def test_sandbox_good_code_passes(mk):
    u = mk()
    p = os.path.join(u.staging, "good.py")
    open(p, "w", encoding="utf-8").write("x = 1 + 1\n")
    ok, msg = u.sandbox_verify_patch(p)
    assert ok is True, msg


def test_sandbox_cleans_temp_file(mk):
    """临时验证脚本要删掉（不删会在 staging 里越攒越多）"""
    u = mk()
    p = os.path.join(u.staging, "good.py")
    open(p, "w", encoding="utf-8").write("x = 1\n")
    u.sandbox_verify_patch(p)
    left = [f for f in os.listdir(u.staging) if f.startswith("_patch_test_")]
    assert not left, "临时文件没删：%s" % left


def test_sandbox_uses_unique_temp_name(mk):
    """⚠️ 临时文件名要带 pid + 线程号

    代码注释里记着：与 `hot_reload.sandbox_test` 同一个坑 ——
    共用固定文件名时，两个验证流程并发会互相覆盖，
    验证结果**张冠李戴**（A 的补丁用 B 的结果判通过）。
    """
    src = (open(os.path.join(BASE, "modules", "installed", "auto_updater.py"),
                encoding="utf-8").read() + "\n" +
           open(os.path.join(BASE, "core", "auto_update.py"),
                encoding="utf-8").read())
    assert "getpid()" in src and "get_ident()" in src, \
        "临时文件名没带 pid/线程号 —— 并发会互相覆盖"


# ══════════════════════════════════════════════════════════════
# ⑤ 部署 / 回滚
# ══════════════════════════════════════════════════════════════
def test_deploy_missing_target(mk):
    u = mk()
    r = u.deploy_patch("不存在.py", os.path.join(u.staging, "p.py"), "")
    assert r["ok"] is False and "找不到" in r["原因"], r


def test_deploy_success(mk):
    u = mk()
    tgt = os.path.join(u.base, "modules", "installed", "m.py")
    open(tgt, "w", encoding="utf-8").write("old = 1\n")
    patch = os.path.join(u.staging, "m.py")
    open(patch, "w", encoding="utf-8").write("new = 2\n")
    r = u.deploy_patch("m.py", patch, u.backup_dir)
    assert r["ok"] is True, r
    assert open(tgt, encoding="utf-8").read() == "new = 2\n"


def test_deploy_rolls_back_when_reload_fails(mk):
    """⚠️ **热重载失败必须回滚**

    那是"换上去的代码加载不了"的信号 —— 不回滚的话，程序现在
    磁盘上是坏的，**下次启动就起不来了**。
    """
    class BadHR:
        def reload_module(self, k):
            return False, "加载失败：语法错"

    u = mk(modules={"hot_reload": BadHR()})
    tgt = os.path.join(u.base, "modules", "installed", "m.py")
    open(tgt, "w", encoding="utf-8").write("old = 1\n")
    patch = os.path.join(u.staging, "m.py")
    open(patch, "w", encoding="utf-8").write("new = 2\n")
    # 让懒加载表认识它，才会走热重载
    u.trunk._lazy = {"m": ("m", "M", "测试")}

    r = u.deploy_patch("m.py", patch, u.backup_dir)
    assert r["ok"] is False, r
    assert r.get("已回滚") is True, r
    assert open(tgt, encoding="utf-8").read() == "old = 1\n", \
        "热重载失败却没回滚 —— 磁盘上是坏的，下次启动就起不来了"


def test_rollback_restores_core(mk):
    u = mk()
    # 造备份
    bk = os.path.join(u.backup_dir, "backup_x")
    os.makedirs(os.path.join(bk, "core"), exist_ok=True)
    open(os.path.join(bk, "core", "a.py"), "w",
         encoding="utf-8").write("good = 1\n")
    # 现在的（坏的）
    open(os.path.join(u.base, "core", "a.py"), "w",
         encoding="utf-8").write("broken\n")
    assert u.rollback(bk) is True
    assert open(os.path.join(u.base, "core", "a.py"),
                encoding="utf-8").read() == "good = 1\n"


def test_backup_keeps_at_most_five(mk):
    """⚠️ 备份只留最近 5 个

    auto_updater 的备份是**整个 core + modules** —— 不限个数的话
    每次自更新都留一份完整副本，用几次就把磁盘吃满了。
    （这条和 backups/ 涨到 1.4 GB 那次是同一类问题。）
    """
    u = mk()
    open(os.path.join(u.base, "core", "a.py"), "w", encoding="utf-8").write("x\n")
    for _ in range(8):
        import time
        time.sleep(1.05)                     # 目录名按秒，要错开
        u.backup_current()
        if len(os.listdir(u.backup_dir)) > 5:
            break
    assert len(os.listdir(u.backup_dir)) <= 5, \
        "备份超过 5 个了：%s" % os.listdir(u.backup_dir)


def test_find_module_file_searches_three_places(mk):
    """按文件名在 installed / modules_repo / core 三处找"""
    u = mk()
    open(os.path.join(u.base, "core", "c.py"), "w", encoding="utf-8").write("x\n")
    assert u._find_module_file("c.py"), "core 里的没找到"
    assert u._find_module_file("没有这个.py") is None


# ══════════════════════════════════════════════════════════════
# ⑥ 闭环：每一步失败都要能退出来
# ══════════════════════════════════════════════════════════════
def test_loop_stops_when_no_target_module(mk):
    u = mk(modules={"llm": FakeLLM("我觉得可以优化")})
    r = u.run_auto_update(confirm=False)
    assert r["ok"] is False, r
    assert "目标模块" in r["原因"], r


def test_loop_stops_on_patch_failure(mk):
    llm = FakeLLM("目标模块: x.py\n建议: 改点东西")
    u = mk(modules={"llm": llm})
    # 第二次 chat（打补丁那次）抛错
    calls = {"n": 0}
    real = llm.chat

    def flaky(p):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("打补丁失败")
        return real(p)
    llm.chat = flaky
    r = u.run_auto_update(confirm=False)
    assert r["ok"] is False, r


def test_loop_stops_on_user_cancel(mk):
    """⚠️ 用户点取消 -> **一个文件都不许动**"""
    u = mk(modules={"llm": StagedLLM("目标模块: m.py\n建议: 改",
                                     "x = 1\n")})
    open(os.path.join(u.base, "modules", "installed", "m.py"), "w",
         encoding="utf-8").write("old = 1\n")
    u.ask_confirm = lambda t: False
    r = u.run_auto_update(confirm=True)
    assert r["ok"] is False and r.get("取消") is True, r
    assert open(os.path.join(u.base, "modules", "installed", "m.py"),
                encoding="utf-8").read() == "old = 1\n"


def test_loop_respects_self_upgrade_rule_off(mk):
    """⚠️「自主.升级」关掉时：**分析照做，但不部署**

    代码注释写得很清楚：分析+补丁+沙盒验证都已完成，
    只是不改文件、不热重载。
    """
    u = mk(modules={"llm": StagedLLM("目标模块: m.py\n建议: 改",
                                     "x = 1\n")},
           rules={"自主.升级": False})
    open(os.path.join(u.base, "modules", "installed", "m.py"), "w",
         encoding="utf-8").write("old = 1\n")
    u.ask_confirm = lambda t: True
    r = u.run_auto_update(confirm=True)
    assert r["ok"] is False, r
    assert r.get("已分析") is True, r
    assert "自主.升级" in r["原因"], r
    assert open(os.path.join(u.base, "modules", "installed", "m.py"),
                encoding="utf-8").read() == "old = 1\n", \
        "规则关掉了却还是改了文件"


def test_sandbox_failure_message_contains_reason(mk):
    """⚠️ 沙盒判失败时，消息里**必须有原因**

    原来返回的是 stdout 的尾巴 —— 而 Python 的报错走的是 **stderr**，
    于是用户看到的是"沙盒验证失败: "后面**什么都没有**。
    实测踩到：补丁是两行注解语句，import 时求值报 NameError，
    报错全在 stderr，stdout 是空的。

    这种"只告诉你失败了、不告诉你为什么"的提示，等于没提示 ——
    用户既不能自己修，也没法把错误贴给别人看。
    """
    u = mk()
    p = os.path.join(u.staging, "bad_runtime.py")
    # 语法没问题（py_compile 能过），但 import 时会抛
    open(p, "w", encoding="utf-8").write("raise ValueError('加载就炸')\n")
    ok, msg = u.sandbox_verify_patch(p)
    assert ok is False
    assert msg.strip(), "失败了但消息是空的 —— 用户看不到任何原因"
    assert "ValueError" in msg or "加载就炸" in msg, \
        "消息里没有真正的原因：%r" % msg


def test_loop_never_raises_on_bad_trunk(mk):
    """trunk 给的东西奇形怪状也不能把闭环抛出去"""
    u = mk()
    u.trunk.modules = {"llm": FakeLLM(None)}
    r = u.run_auto_update(confirm=False)
    assert isinstance(r, dict) and "ok" in r, r


# ══════════════════════════════════════════════════════════════
# ⑦ 杂项
# ══════════════════════════════════════════════════════════════
def test_ask_confirm_without_trunk_defaults_false(mk):
    u = mk()
    u.trunk = None
    assert u.ask_confirm("计划") is False


def test_ask_confirm_trunk_error_defaults_false(mk):
    """弹窗回调异常时必须 fail-closed（返回 False），不能静默部署。"""
    u = mk()
    def boom(*a, **k):
        raise RuntimeError("GUI 没了")
    u.trunk.confirm = boom
    assert u.ask_confirm("计划") is False


def test_analyze_performance_and_run(mk):
    u = mk()
    assert u.analyze_performance() is not None
    assert u.get_update_suggestions() is not None
    assert u.run("") is not None


def test_log_callback(mk):
    """_log 要能发出去（界面上那行状态靠它）"""
    u = mk()
    u._log("测试一下")                       # 不许抛


def test_reload_touched_without_hot_reload(mk):
    """没有 hot_reload 模块时安静跳过（不影响更新结果）"""
    u = mk()
    assert u._reload_touched(["a.py", "b.py"]) is None
