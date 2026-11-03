# -*- coding: utf-8 -*-
"""B7：门禁自身的守卫

为什么测"门禁"而不是只测功能
----------------------------
门禁被删掉/改坏的时候，**所有检查仍然是全绿** —— 这是最不容易被发现的一类退化。
所以这里把门禁的关键结构钉住：

    1. pre-push 是 13 项，且 pre-commit 那 10 项全集包含在 --full 里；
    2. `懒加载来源` 等关键项（REQUIRED）一旦被移除，脚本必须自己失败；
    3. CHECKS 里每个 `tools/xxx.py` 都得真的存在（改名/删除要同步改门禁）；
    4. `.githooks/pre-push` 确实调 `--full`（否则推送前等于没检查）。
"""
import importlib.util
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

SPEC = os.path.join(BASE, "tools", "pre_commit_check.py")


def _gate():
    spec = importlib.util.spec_from_file_location("x6_gate", SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate_has_thirteen_checks_and_two_tiers():
    gate = _gate()
    assert len(gate.CHECKS) == 13, "门禁项数变了，确认后改 docs/30 与这句断言"
    tiers = {}
    for label, _cmd, full in gate.CHECKS:
        tiers.setdefault(bool(full), []).append(label)
    assert len(tiers[False]) == 10, tiers[False]       # pre-commit 档
    assert len(tiers[True]) == 3, tiers[True]          # 只在 --full 跑
    # --full 跑的是全集
    assert len(tiers[False]) + len(tiers[True]) == 13


def test_lazy_sources_is_a_required_guard():
    gate = _gate()
    labels = [c[0] for c in gate.CHECKS]
    assert "懒加载来源" in labels
    assert "懒加载来源" in gate.REQUIRED
    # 关键项必须在快检档就跑到（pre-push 是快检的超集）
    fast = {c[0] for c in gate.CHECKS if not c[2]}
    for k in gate.REQUIRED:
        assert k in fast, "%s 应该放进快检档，否则本地提交看不到" % k


def test_removing_a_required_check_makes_the_gate_fail():
    """把 REQUIRED 里的一项从 CHECKS 里删掉，main() 必须返回非 0"""
    gate = _gate()
    saved_checks = list(gate.CHECKS)
    saved_argv = sys.argv
    try:
        gate.CHECKS[:] = [c for c in saved_checks if c[0] != "懒加载来源"]
        sys.argv = ["pre_commit_check.py"]      # argparse 不该看到 pytest 的参数
        assert gate.main() != 0
    finally:
        gate.CHECKS[:] = saved_checks
        sys.argv = saved_argv


def test_every_check_script_exists():
    gate = _gate()
    missing = []
    for label, cmd, _full in gate.CHECKS:
        for part in cmd:
            text = str(part)
            if text.endswith(".py") and "/" in text:
                if not os.path.isfile(os.path.join(BASE, text)):
                    missing.append("%s → %s" % (label, text))
    assert not missing, "门禁引用了不存在的脚本：%s" % missing


def test_pre_push_hook_runs_full():
    hook = os.path.join(BASE, ".githooks", "pre-push")
    assert os.path.isfile(hook)
    text = open(hook, encoding="utf-8", errors="replace").read()
    assert "--full" in text, "pre-push 没跑全套，等于推送前没有检查"
    assert "pre_commit_check.py" in text


def test_lazy_source_check_itself_passes():
    """守卫本体要能跑通（它一挂说明登记真错位了，不是测试的问题）"""
    spec = importlib.util.spec_from_file_location(
        "x6_lazy", os.path.join(BASE, "tools", "check_lazy_sources.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.check() == []
    assert mod.main() == 0


# ---------------------------------------------------------------- S4 新增守卫
def _tool(name):
    spec = importlib.util.spec_from_file_location(
        "x6_" + name, os.path.join(BASE, "tools", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _main(mod):
    """跑守卫的 main()，但不让它看见 pytest 自己的参数（argparse 会直接 exit）"""
    saved = sys.argv
    try:
        sys.argv = ["tools/guard.py"]
        return mod.main()
    finally:
        sys.argv = saved


def test_s4_guards_are_required_and_fast():
    """两条新守卫既在 CHECKS 里、又属于关键守卫、还要在快检档"""
    gate = _gate()
    labels = [c[0] for c in gate.CHECKS]
    fast = {c[0] for c in gate.CHECKS if not c[2]}
    for k in ("死代码棘轮", "信号接线"):
        assert k in labels, k
        assert k in gate.REQUIRED, k
        assert k in fast, "%s 应该在快检档，否则本地提交看不到" % k


def test_dead_code_guard_passes():
    """仓库当前状态：可疑死代码 0（S3 清完，KEEP 4 项不计）"""
    mod = _tool("check_dead_code")
    assert mod.check() == []
    assert _main(mod) == 0


def test_dead_code_guard_flags_new_dead_def():
    """守卫要真能拦住：多一个零引用函数就必须失败（基线 0）"""
    mod = _tool("check_dead_code")
    fake = {"dead_modules": [], "duplicates": [], "kept_defs": [], "scanned": 1,
            "dead_defs": [{"file": "core/x.py", "line": 3, "kind": "def",
                           "name": "nobody_calls_me", "private": False}]}
    errs = mod.check(fake)
    text = "\n".join(errs)
    assert errs
    assert "nobody_calls_me" in text


def test_signal_guard_passes():
    """仓库当前状态：91 个 pyqtSignal 全部有人 connect"""
    mod = _tool("check_signals")
    assert mod.check() == []
    assert _main(mod) == 0


def test_signal_guard_catches_unconnected_signal(tmp_path):
    """守卫要真能抓：定义了 pyqtSignal 但没人 .connect 的那个必须被点名"""
    mod = _tool("check_signals")
    gui = os.path.join(str(tmp_path), "gui")
    os.makedirs(gui)
    with open(os.path.join(gui, "fake.py"), "w", encoding="utf-8") as f:
        f.write("from PyQt5.QtCore import pyqtSignal\n"
                "\n"
                "\n"
                "class W:\n"
                "    lonely = pyqtSignal(str)\n"
                "    used = pyqtSignal()\n"
                "\n"
                "    def f(self):\n"
                "        self.used.connect(lambda: None)\n"
                "        self.lonely.emit('x')\n")
    saved_base, saved_baseline = mod.BASE, mod.BASELINE
    try:
        mod.BASE = str(tmp_path)
        mod.BASELINE = os.path.join(str(tmp_path), "signals_baseline.json")
        unconnected, connected, total = mod.scan()
        assert [x["name"] for x in unconnected] == ["lonely"]
        assert total == 2 and connected == 1
        assert mod.check((unconnected, connected, total)) != []
    finally:
        mod.BASE, mod.BASELINE = saved_base, saved_baseline
