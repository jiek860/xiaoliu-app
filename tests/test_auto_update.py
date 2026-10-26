# -*- coding: utf-8 -*-
"""core/auto_update.py 的同名测试：策略 / 问题收集 / 补丁 / 下载安装。

合并前的 4 个 Mixin 现在同住一个文件，这里按四段各测一遍，
重点钉「失败时必须退得出来」的分支：策略开关关掉、下载包被篡改、
替换失败要回滚、热重载找不到懒加载项只记日志不抛。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

import core.auto_update as au


class FakeTrunk:
    def __init__(self, base, modules=None, rules=None, config=None):
        self.base = str(base)
        self.modules = modules or {}
        self.config = dict(config or {})
        self._lazy = {}
        self.logs = []
        self.calls = []
        self.confirm_cb = lambda title, text: True
        self._rules = rules or {}
        self.confirm_answer = True
        self.call_result = {}

    def rule(self, key, default=None):
        if key == "raise":
            raise RuntimeError("规则引擎坏了")
        return self._rules.get(key, default)

    def call(self, name, method, *a):
        self.calls.append("%s.%s" % (name, method))
        v = self.call_result.get("%s.%s" % (name, method), {})
        if isinstance(v, Exception):
            raise v
        return v

    def confirm(self, title, text):
        if self.confirm_answer == "raise":
            raise RuntimeError("弹窗没了")
        return self.confirm_answer

    def _log(self, m):
        if self.logs is not None and self.logs == "raise":
            raise RuntimeError("日志坏了")
        self.logs.append(m)

    def reply(self, text):
        if self.config.get("reply_raises"):
            raise RuntimeError("回复炸了")
        return "ok"


class Obj(au.AutoUpdateProblemMixin, au.AutoUpdatePatchMixin,
          au.AutoUpdateDownloadMixin, au.AutoUpdatePolicyMixin):
    def __init__(self, base, trunk=None):
        self.base = str(base)
        self.trunk = trunk
        self.staging = os.path.join(self.base, "staging")
        self.backup_dir = os.path.join(self.base, "backups")
        self.patch_dir = os.path.join(self.staging, "patches")
        for d in (self.staging, self.backup_dir, self.patch_dir,
                  os.path.join(self.base, "core"),
                  os.path.join(self.base, "modules", "installed"),
                  os.path.join(self.base, "modules_repo")):
            os.makedirs(d, exist_ok=True)


@pytest.fixture
def mk(tmp_path):
    def _mk(trunk=None, **kw):
        o = Obj(str(tmp_path), trunk or FakeTrunk(tmp_path, **kw))
        return o
    return _mk


class FakeLLM:
    def __init__(self, reply="", raises=False):
        self.reply = reply
        self.raises = raises
        self.prompts = []

    def chat(self, prompt):
        self.prompts.append(prompt)
        if self.raises:
            raise RuntimeError("模型炸了")
        return self.reply


# ──────────────────────────────────────────────────────────────
# 1. 策略
# ──────────────────────────────────────────────────────────────
def test_self_upgrade_defaults_true_and_swallows_rule_error(mk):
    o = mk()
    assert o._allow_self_upgrade() is True
    o.trunk._rules["自主.升级"] = False
    assert o._allow_self_upgrade() is False

    class BadRule:
        config = {}
        modules = {}

        def rule(self, key, default=None):
            raise RuntimeError("规则引擎炸了")

    o.trunk = BadRule()
    assert o._allow_self_upgrade() is True


def test_version_tuple_handles_dirty_input():
    assert au.AutoUpdatePolicyMixin._version_tuple("v25.2.24") == (25, 2, 24)
    assert au.AutoUpdatePolicyMixin._version_tuple("25.2") == (25, 2)
    assert au.AutoUpdatePolicyMixin._version_tuple("abc") == (0,)
    assert (au.AutoUpdatePolicyMixin._version_tuple("v25.2.24") >
            au.AutoUpdatePolicyMixin._version_tuple("v25.1.99"))


def test_allow_unsigned_update(mk):
    o = mk()
    assert o._allow_unsigned_update() is False
    o.trunk.config["allow_unsigned_update"] = True
    assert o._allow_unsigned_update() is True
    o.trunk = None
    assert o._allow_unsigned_update() is False


def test_log_falls_back_to_print(mk, capsys):
    o = mk()
    o.trunk.logs = "raise"          # trunk._log 抛错 -> 退回 print
    o._log("被吃掉了吗")
    assert "被吃掉了吗" in capsys.readouterr().out

    o.trunk = None                  # 没有 trunk 也直接 print
    o._log("没有躯干")
    assert "没有躯干" in capsys.readouterr().out


# ──────────────────────────────────────────────────────────────
# 2. 问题收集 / 建议 / 补丁 / 健康检查
# ──────────────────────────────────────────────────────────────
def test_collect_problems_swallows_self_reflect_error(mk):
    o = mk()
    o.trunk.call_result["error_lib.list"] = {"未修复": 2}
    o.trunk.call_result["self_reflect.get_history"] = RuntimeError("历史库坏了")
    p = o.collect_problems()
    assert any("2" in x for x in p), p


def test_build_suggestion_no_format_and_llm_raises(mk):
    o = mk(modules={"llm": FakeLLM("我随便说一句")})
    r = o.build_suggestion(["x"])
    assert r["目标模块"] == "" and r["建议"], r
    # 模型给出的目标模块自带 .py，不应变成 "x.py.py"
    o2 = mk(modules={"llm": FakeLLM("目标模块: x.py\n建议: 改")})
    assert o2.build_suggestion(["x"])["目标模块"] == "x.py"
    o3 = mk(modules={"llm": FakeLLM(raises=True)})
    r3 = o3.build_suggestion(["x"])
    assert r3["目标模块"] == "" and "失败" in r3["建议"]


def test_gen_patch_uses_existing_source(mk):
    o = mk(modules={"llm": FakeLLM("x = 1\n")})
    open(os.path.join(o.base, "core", "mod_x.py"), "w",
         encoding="utf-8").write("旧代码 = 1\n")
    r = o.gen_patch("改改", "mod_x.py")
    assert r["ok"] is True
    assert "旧代码" in o.trunk.modules["llm"].prompts[0]
    assert os.path.exists(os.path.join(o.patch_dir, "mod_x.py"))


def test_run_health_checks_catches_installed_syntax_error(mk):
    o = mk()
    open(os.path.join(o.base, "core", "ok.py"), "w", encoding="utf-8").write("x=1\n")
    open(os.path.join(o.base, "modules", "installed", "bad.py"), "w",
         encoding="utf-8").write("def f(:\n")
    passed, total, fails = o.run_health_checks()
    assert fails and "bad.py" in fails[0], fails
    assert passed < total


def test_analyze_performance_swallows_reply_error(mk):
    o = mk(config={"reply_raises": True})
    r = o.analyze_performance()
    assert "响应时间" in r and "性能" in r


def test_get_update_suggestions_without_llm(mk):
    r = mk().get_update_suggestions()
    assert "建议" in r


# ──────────────────────────────────────────────────────────────
# 3. 沙盒 / 确认 / 备份 / 部署
# ──────────────────────────────────────────────────────────────
def test_sandbox_reports_placeholder_when_no_output(mk):
    o = mk()
    p = os.path.join(o.staging, "silent.py")
    open(p, "w", encoding="utf-8").write("import os\nos._exit(1)\n")
    ok, msg = o.sandbox_verify_patch(p)
    assert ok is False and msg.strip(), msg


def test_sandbox_handles_subprocess_error(mk, monkeypatch):
    o = mk()
    p = os.path.join(o.staging, "x.py")
    open(p, "w", encoding="utf-8").write("x = 1\n")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("python", 15)
    monkeypatch.setattr(au.subprocess, "run", boom)
    ok, msg = o.sandbox_verify_patch(p)
    assert ok is False and "超时" in msg, msg


def test_sandbox_temp_cleanup_failure_is_ignored(mk, monkeypatch):
    o = mk()
    p = os.path.join(o.staging, "x.py")
    open(p, "w", encoding="utf-8").write("x = 1\n")
    real = os.remove
    monkeypatch.setattr(au.os, "remove", lambda *a: (_ for _ in ()).throw(OSError("占用")))
    ok, _ = o.sandbox_verify_patch(p)
    monkeypatch.setattr(au.os, "remove", real)
    assert ok is True


def test_ask_confirm_requires_callback(mk):
    o = mk()
    assert o.ask_confirm("计划") is True
    o.trunk.confirm_cb = None
    assert o.ask_confirm("计划") is False
    o2 = mk()
    o2.trunk.confirm_answer = "raise"
    assert o2.ask_confirm("计划") is False
    o3 = mk()
    o3.trunk.confirm_answer = False
    assert o3.ask_confirm("计划") is False


def test_backup_current_creates_copy(mk):
    o = mk()
    open(os.path.join(o.base, "core", "a.py"), "w", encoding="utf-8").write("x\n")
    bk = o.backup_current()
    assert os.path.exists(os.path.join(bk, "core", "a.py"))


def test_deploy_logs_when_lazy_table_missing_entry(mk):
    class HR:
        def reload_module(self, key):
            return True, "ok"

    o = mk(modules={"hot_reload": HR()})
    open(os.path.join(o.base, "core", "m.py"), "w", encoding="utf-8").write("old\n")
    patch = os.path.join(o.staging, "m.py")
    open(patch, "w", encoding="utf-8").write("new\n")
    r = o.deploy_patch("m.py", patch, o.backup_dir)
    assert r["ok"] is True
    assert any("未在懒加载表找到" in x for x in o.trunk.logs), o.trunk.logs


def test_deploy_rollback_failure_is_reported(mk, monkeypatch):
    class BadHR:
        def reload_module(self, key):
            return False, "加载失败"

    o = mk(modules={"hot_reload": BadHR()})
    target = os.path.join(o.base, "core", "m.py")
    open(target, "w", encoding="utf-8").write("old\n")
    patch = os.path.join(o.staging, "m.py")
    open(patch, "w", encoding="utf-8").write("new\n")
    o.trunk._lazy = {"m": ("m", "M", "")}

    real_open = open
    state = {"writes": 0}

    def flaky_open(path, mode="r", *a, **k):
        if os.path.abspath(str(path)) == os.path.abspath(target) and "w" in mode:
            state["writes"] += 1
            if state["writes"] >= 2:      # 第一次替换成功，回滚那次失败
                raise OSError("磁盘满了")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", flaky_open)
    r = o.deploy_patch("m.py", patch, o.backup_dir)
    monkeypatch.undo()
    assert r["ok"] is False and r.get("已回滚") is True
    assert any("回滚失败" in x for x in o.trunk.logs), o.trunk.logs


def test_rollback_without_backup_dir_reports_failure(mk):
    o = mk()
    assert o.rollback(os.path.join(o.base, "backups", "没有这个")) is False
    assert any("回滚失败" in x for x in o.trunk.logs), o.trunk.logs


def test_rollback_restores_backup_files_without_wiping_new_ones(tmp_path):
    """回滚只覆盖备份里有的文件：更新后新装的插件不能被抹掉。

    老实现是 rmtree(core/modules) + copytree(备份)——回滚一次，
    用户更新后自己装的插件和改过的文件全没了。
    """
    o = Obj(str(tmp_path))
    o.trunk = FakeTrunk(tmp_path)
    core = os.path.join(o.base, "core")
    installed = os.path.join(o.base, "modules", "installed")
    open(os.path.join(core, "a.py"), "w", encoding="utf-8").write("new = 2\n")
    open(os.path.join(installed, "新装的插件.py"), "w", encoding="utf-8").write("x = 1\n")
    bk = os.path.join(o.base, "backups", "backup_x")
    os.makedirs(os.path.join(bk, "core"), exist_ok=True)
    open(os.path.join(bk, "core", "a.py"), "w", encoding="utf-8").write("old = 1\n")

    assert o.rollback(bk) is True
    assert open(os.path.join(core, "a.py"), encoding="utf-8").read() == "old = 1\n"
    assert os.path.exists(os.path.join(installed, "新装的插件.py")), \
        "回滚不该删掉更新之后新装的文件"


def test_reload_touched_matches_lazy_and_swallows_error(mk):
    calls = []

    class HR:
        def reload_module(self, key):
            calls.append(key)
            if key == "bad":
                raise RuntimeError("重载失败")
            return True, "ok"

    o = mk(modules={"hot_reload": HR()})
    o.trunk._lazy = {"good": ("mod_good",), "bad": ("mod_bad",)}
    o._reload_touched(["a/mod_good.py", "mod_bad.py", "没有登记.py"])
    assert calls == ["good", "bad"], calls


# ──────────────────────────────────────────────────────────────
# 4. 更新检查 / 下载安装
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def allow_net(monkeypatch):
    class Guard:
        def check(self, url, **kw):
            return {"allow": True}
    monkeypatch.setattr("core.net_guard.get_net_guard", lambda t: Guard())


def _manifest(version="v99.0.0"):
    return {"version": version, "changelog": "测试更新", "files": []}


def _stub_sign(monkeypatch, ok=True):
    import core.release_sign as rs
    monkeypatch.setattr(rs, "verify_manifest", lambda m, k: ok)
    monkeypatch.setattr(rs, "load_release_pubkey", lambda base: b"pub")


def test_check_update_without_url(mk):
    o = mk()
    r = o.check_update()
    assert r["ok"] is False and "未配置更新地址" in r["error"], r


def test_check_update_rejects_unsigned_manifest(mk, monkeypatch, allow_net):
    _stub_sign(monkeypatch, ok=False)
    o = mk(config={"update_manifest_url": "https://example.com/m.json"})

    class Resp:
        def read(self):
            return json.dumps(_manifest()).encode("utf-8")

    monkeypatch.setattr(au, "safe_open_url", lambda req, timeout=10: Resp())
    r = o.check_update()
    assert r["ok"] is False and r["verified"] is False and "验签" in r["error"], r


def test_check_update_allows_unsigned_when_opted_in(mk, monkeypatch, allow_net):
    _stub_sign(monkeypatch, ok=False)
    o = mk(config={"update_manifest_url": "https://example.com/m.json",
                   "allow_unsigned_update": True})

    class Resp:
        def read(self):
            return json.dumps(_manifest("v99.0.0")).encode("utf-8")

    monkeypatch.setattr(au, "safe_open_url", lambda req, timeout=10: Resp())
    r = o.check_update()
    assert r["ok"] is True and r["has_update"] is True, r
    assert any("警告" in x for x in o.trunk.logs)


def test_check_update_fetch_error_is_friendly(mk, monkeypatch, allow_net):
    o = mk(config={"update_manifest_url": "https://example.com/m.json"})

    def boom(req, timeout=10):
        raise OSError("断网")
    monkeypatch.setattr(au, "safe_open_url", boom)
    r = o.check_update()
    assert r["ok"] is False and "拉取更新清单失败" in r["error"], r


def test_safe_relpath_blocks_traversal(tmp_path):
    o = Obj(str(tmp_path))
    assert o._safe_relpath("a/b.py").endswith("b.py")
    assert o._safe_relpath("../evil.py") is None
    assert o._safe_relpath("") is None
    assert o._safe_relpath("a\x00b.py") is None


def test_download_rejects_unsigned(mk, monkeypatch):
    _stub_sign(monkeypatch, ok=False)
    r = mk().download_and_install(_manifest())
    assert r["ok"] is False and "验签" in r["错误"], r


def test_download_rejects_empty_file_list(mk, monkeypatch):
    _stub_sign(monkeypatch)
    r = mk().download_and_install(_manifest())
    assert r["ok"] is False and "为空" in r["错误"], r


def test_download_rejects_bad_entry(mk, monkeypatch):
    _stub_sign(monkeypatch)
    m = _manifest()
    m["files"] = [{"path": "../evil.py", "url": "https://x/e.py"}]
    r = mk().download_and_install(m)
    assert r["ok"] is False and "非法" in r["错误"], r


def test_download_sha_mismatch(mk, monkeypatch, allow_net):
    _stub_sign(monkeypatch)
    m = _manifest()
    m["files"] = [{"path": "core/a.py", "url": "https://x/a.py",
                   "sha256": hashlib.sha256(b"other").hexdigest()}]

    class Resp:
        def read(self):
            return b"hello"
    monkeypatch.setattr(au, "safe_open_url", lambda req, timeout=30: Resp())
    r = mk().download_and_install(m)
    assert r["ok"] is False and "sha256" in r["错误"], r


def test_download_success_writes_files_and_history(tmp_path, monkeypatch, allow_net):
    _stub_sign(monkeypatch)
    body = b"x = 1\n"
    m = _manifest("v99.0.0")
    m["files"] = [{"path": "core/a.py", "url": "https://x/a.py",
                   "sha256": hashlib.sha256(body).hexdigest()}]

    class Resp:
        def read(self):
            return body
    monkeypatch.setattr(au, "safe_open_url", lambda req, timeout=30: Resp())
    seen = []
    o = Obj(str(tmp_path))
    o.trunk = FakeTrunk(tmp_path)
    r = o.download_and_install(m, progress_cb=lambda i, t, rel: seen.append((i, t, rel)),
                               confirm=False)
    assert r["ok"] is True and r["更新数"] == 1, r
    assert open(os.path.join(o.base, "core", "a.py"), encoding="utf-8").read() == "x = 1\n"
    hist = os.path.join(o.base, "updates", "update_history.jsonl")
    assert os.path.exists(hist) and "v99.0.0" in open(hist, encoding="utf-8").read()
    entry = json.loads(open(hist, encoding="utf-8").read().splitlines()[-1])
    # 历史里要记备份目录：更新对话框靠它提供「回滚到这次更新之前」
    assert entry["backup"] and os.path.isdir(entry["backup"]), entry
    assert entry["verified"] is True
    assert seen and seen[-1][0] == seen[-1][1]


def test_download_history_records_unsigned_state_honestly(tmp_path, monkeypatch, allow_net):
    """放行未签名更新时，历史不能写成 verified=True（否则回滚时看起来像验过签）"""
    _stub_sign(monkeypatch, ok=False)
    body = b"x = 1\n"
    m = _manifest("v99.1.0")
    m["files"] = [{"path": "core/a.py", "url": "https://x/a.py",
                   "sha256": hashlib.sha256(body).hexdigest()}]

    class Resp:
        def read(self):
            return body
    monkeypatch.setattr(au, "safe_open_url", lambda req, timeout=30: Resp())
    o = Obj(str(tmp_path))
    o.trunk = FakeTrunk(tmp_path, config={"allow_unsigned_update": True})
    r = o.download_and_install(m, confirm=False)
    assert r["ok"] is True, r
    hist = os.path.join(o.base, "updates", "update_history.jsonl")
    entry = json.loads(open(hist, encoding="utf-8").read().splitlines()[-1])
    assert entry["verified"] is False
    assert os.path.isdir(entry["backup"])


def test_download_rolls_back_when_replace_fails(tmp_path, monkeypatch, allow_net):
    _stub_sign(monkeypatch)
    body = b"new = 2\n"
    m = _manifest()
    m["files"] = [{"path": "core/a.py", "url": "https://x/a.py",
                   "sha256": hashlib.sha256(body).hexdigest()}]

    class Resp:
        def read(self):
            return body
    monkeypatch.setattr(au, "safe_open_url", lambda req, timeout=30: Resp())
    o = Obj(str(tmp_path))
    o.trunk = FakeTrunk(tmp_path)
    open(os.path.join(o.base, "core", "a.py"), "w", encoding="utf-8").write("old = 1\n")
    real_copy2 = shutil.copy2
    target = os.path.abspath(os.path.join(o.base, "core", "a.py"))

    def flaky(src, dst, *a, **k):
        if os.path.abspath(str(dst)) == target:
            raise OSError("写入失败")
        return real_copy2(src, dst, *a, **k)

    monkeypatch.setattr(au.shutil, "copy2", flaky)
    r = o.download_and_install(m, confirm=False)
    monkeypatch.undo()
    assert r["ok"] is False and "回滚" in r["错误"], r
    assert open(os.path.join(o.base, "core", "a.py"), encoding="utf-8").read() == "old = 1\n"
