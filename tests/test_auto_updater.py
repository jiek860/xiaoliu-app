# -*- coding: utf-8 -*-
"""自动更新（modules/installed/auto_updater.py）

为什么补这个文件
----------------
工程化方案实测它 **13.7% 覆盖**（366 条语句）。它是**全项目最危险的一段代码**：

    · 它会**覆盖程序自己的文件**（core/gui/modules 下的 .py）
    · 它是**唯一从网上拉代码并写进磁盘**的地方
    · 写坏了用户就打不开程序了 —— 而且**用户不知道为什么**

所以这里的测试重点不是"功能对不对"，而是**"坏事发生时它拦不拦得住"**：
    · 验签不过 → 必须**在下载之前**就终止
    · 一个文件的 sha256 不符 → 必须终止，且**不能写盘**
    · 替换中途失败 → 必须**回滚**到原样
    · 用户取消 → **一个文件都不许动**
    · 路径穿越（`../../x.py`）→ 必须拒绝

本文件全部用假清单 + 假下载，不联网、不碰真项目文件。
"""
import hashlib
import json
import os
import shutil
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from modules.installed.auto_updater import AutoUpdater   # noqa: E402


class FakeTrunk:
    def __init__(self, base):
        self.base = base
        self.modules = {}
        self.logs = []
        self.calls = []

    def call(self, *a, **k):
        self.calls.append(a)
        return {}

    def rule(self, key, default=None):
        return default

    def _log(self, m):
        self.logs.append(m)


@pytest.fixture
def up(tmp_path, monkeypatch):
    """一个指向临时项目的更新器（不碰真项目）"""
    monkeypatch.setenv("X6_ALLOW_UNSIGNED_UPDATE", "")
    u = AutoUpdater(FakeTrunk(str(tmp_path)))
    u.base = str(tmp_path)
    u.staging = os.path.join(str(tmp_path), "staging")
    os.makedirs(u.staging, exist_ok=True)
    # 默认不许装未签名的（测单项时会单独放开）
    u._allow_unsigned_update = lambda: False
    return u


# ══════════════════════════════════════════════════════════════
# ① `_safe_relpath` —— 安全的第一道闸
# ══════════════════════════════════════════════════════════════
def test_safe_relpath_normal(up):
    p = up._safe_relpath("core/version.py")
    assert p == os.path.normpath(os.path.join(up.base, "core", "version.py"))


@pytest.mark.parametrize("evil", [
    "../outside.py",
    "../../outside.py",
    "core/../../outside.py",
    "core/./../../x.py",
    "..\\outside.py",                 # 反斜杠也要挡
    "core\\..\\..\\x.py",
])
def test_safe_relpath_blocks_traversal(up, evil):
    """⚠️ **路径穿越必须挡住**

    这是整条更新链路里最要紧的一条：清单里的 `path` 是**服务端给的**。
    如果 `../../某个文件` 能通过，就等于"别人可以在你机器上任意位置
    写文件" —— 比覆盖程序本身还严重。

    注意反斜杠那两条：清单是 JSON，`path` 里既可能用 `/` 也可能用 `\\`，
    两个都得挡。
    """
    r = up._safe_relpath(evil)
    assert r is None, "%r 没被挡住，解析成了 %s" % (evil, r)


@pytest.mark.parametrize("p", ["/absolute.py", "//server/share/x.py"])
def test_leading_slash_is_stripped_not_escaped(up, p):
    """⚠️ 前导斜杠要**去掉后当相对路径**，不是拒绝

    一开始我把这两条列进了"必须挡住"，断言它们返回 None ——
    其实返回的是 base 里面的路径，**那才是对的**：
        `/absolute.py`   -> lstrip("/") -> `absolute.py`  -> 落在 base 内
        `//server/x.py`  -> lstrip("/") -> `server/x.py`  -> 落在 base 内

    如果这里返回 None（拒绝），那清单里所有以 / 开头的正常路径
    都会被拒 —— 拒绝得太狠，功能就废了。
    关键性质是"**落在 base 内**"，而不是"返回 None"。
    """
    r = up._safe_relpath(p)
    assert r is not None, "%r 被拒了 —— 拒过头" % p
    base = os.path.normpath(up.base)
    assert r == base or r.startswith(base + os.sep), \
        "%r 跑出项目目录了：%s" % (p, r)


def test_safe_relpath_allows_dot_in_name(up):
    """别挡过头：文件名里带点（如 `a.b.py`）是正常的"""
    assert up._safe_relpath("core/a.b.py") is not None
    assert up._safe_relpath("a.b.c/d.py") is not None


def test_safe_relpath_empty_is_base(up):
    """空路径解析成项目根 —— 调用方要自己判非法（下载那边有判）"""
    r = up._safe_relpath("")
    assert r == os.path.normpath(up.base)


# ══════════════════════════════════════════════════════════════
# ② 验签：**必须在下载之前**就拦
# ══════════════════════════════════════════════════════════════
def test_unsigned_manifest_refused_before_download(up, monkeypatch):
    """⚠️ 验签不过要**在下载之前**终止

    顺序很重要：先下载再验签的话，**恶意内容已经落盘了** ——
    哪怕最后没替换，磁盘上留了个木马也很难发现。
    """
    touched = []

    def spy_urlopen(*a, **k):
        touched.append(a)
        raise AssertionError("验签没过却去下载了！")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", spy_urlopen)

    r = up.download_and_install({"files": [{"path": "a.py",
                                            "url": "http://x/a.py",
                                            "sha256": "00"}]})
    assert r["ok"] is False
    assert "验签" in r["错误"], r
    assert not touched, "验签失败却发起了下载"


def test_empty_file_list_refused(up):
    # ⚠️ 验签在"空列表"检查**之前** —— 要放开未签名才测得到这一条。
    #    （顺序是对的：先确认"这个包可信"，再看内容合不合理。）
    up._allow_unsigned_update = lambda: True
    r = up.download_and_install({"version": "1", "files": []})
    assert r["ok"] is False
    assert "空" in r["错误"], r


# ══════════════════════════════════════════════════════════════
# ③ 校验：sha256 不符必须终止且**不写盘**
# ══════════════════════════════════════════════════════════════
def _manifest(files, ver="9.9.9"):
    return {"version": ver, "files": files, "signature": "x"}


def _fake_urlopen(payloads, monkeypatch, fail_on=None):
    """让 urlopen 返回预设内容（key = url）"""
    import urllib.request

    class R:
        def __init__(self, b):
            self._b = b

        def read(self):
            return self._b

    def fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if fail_on and fail_on in url:
            raise OSError("网络断了")
        if url not in payloads:
            raise OSError("没有为 %s 准备内容" % url)
        return R(payloads[url])

    monkeypatch.setattr(urllib.request, "urlopen", fake)


def test_sha256_mismatch_refuses_and_writes_nothing(up, monkeypatch):
    """⚠️ 校验不过**一个字节都不许写**"""
    up._allow_unsigned_update = lambda: True
    data = b"print('evil')\n"
    _fake_urlopen({"http://x/a.py": data}, monkeypatch)

    target = os.path.join(up.base, "a.py")
    open(target, "w", encoding="utf-8").write("原来好好的\n")

    r = up.download_and_install(_manifest([{
        "path": "a.py", "url": "http://x/a.py",
        "sha256": hashlib.sha256(b"different content").hexdigest(),  # 故意不符
    }]))
    assert r["ok"] is False
    assert "校验失败" in r["错误"], r
    assert open(target, encoding="utf-8").read() == "原来好好的\n", \
        "校验失败却把原文件改了！"


def test_download_failure_refuses(up, monkeypatch):
    up._allow_unsigned_update = lambda: True
    _fake_urlopen({}, monkeypatch)
    r = up.download_and_install(_manifest([{
        "path": "a.py", "url": "http://x/a.py", "sha256": "00"}],
        ver="1"))
    assert r["ok"] is False
    assert "下载失败" in r["错误"], r


def test_illegal_entry_refused(up, monkeypatch):
    """清单里 path 是穿越路径 -> 拒绝（**下载之前**就判）"""
    up._allow_unsigned_update = lambda: True
    called = []
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: called.append(1))
    r = up.download_and_install(_manifest([{
        "path": "../../evil.py", "url": "http://x/a.py", "sha256": "00"}]))
    assert r["ok"] is False
    assert "非法" in r["错误"], r
    assert not called, "路径非法却去下载了"


def test_entry_without_url_refused(up):
    up._allow_unsigned_update = lambda: True
    r = up.download_and_install(_manifest([{"path": "a.py", "sha256": "0"}]))
    assert r["ok"] is False and "非法" in r["错误"], r


# ══════════════════════════════════════════════════════════════
# ④ 用户取消：一个文件都不许动
# ══════════════════════════════════════════════════════════════
def test_user_cancel_changes_nothing(up, monkeypatch):
    """⚠️ 取消之后**一个字节都不许变**

    用户点了"取消"就应该什么都没发生 —— 包括不能留下备份目录、
    不能改动任何文件。（下载到 staging 是允许的，那是临时区。）
    """
    up._allow_unsigned_update = lambda: True
    up.ask_confirm = lambda text: False
    data = b"new = 1\n"
    _fake_urlopen({"http://x/a.py": data}, monkeypatch)
    target = os.path.join(up.base, "a.py")
    open(target, "w", encoding="utf-8").write("old = 1\n")

    r = up.download_and_install(_manifest([{
        "path": "a.py", "url": "http://x/a.py",
        "sha256": hashlib.sha256(data).hexdigest()}]))
    assert r["ok"] is False and r.get("取消") is True, r
    assert open(target, encoding="utf-8").read() == "old = 1\n", \
        "用户取消了但文件被改了"


# ══════════════════════════════════════════════════════════════
# ⑤ 成功路径 + 回滚
# ══════════════════════════════════════════════════════════════
def test_successful_install_replaces_files(up, monkeypatch):
    up._allow_unsigned_update = lambda: True
    up.ask_confirm = lambda text: True
    data = b"new = 2\n"
    _fake_urlopen({"http://x/a.py": data}, monkeypatch)
    target = os.path.join(up.base, "a.py")
    open(target, "w", encoding="utf-8").write("old = 1\n")

    r = up.download_and_install(_manifest([{
        "path": "a.py", "url": "http://x/a.py",
        "sha256": hashlib.sha256(data).hexdigest()}]))
    assert r["ok"] is True, r
    assert open(target, encoding="utf-8").read() == "new = 2\n"
    assert r["更新数"] == 1


def test_successful_install_makes_backup(up, monkeypatch):
    """⚠️ 换掉的旧文件要留下备份 —— 那是回滚的唯一依据"""
    up._allow_unsigned_update = lambda: True
    up.ask_confirm = lambda text: True
    data = b"new = 2\n"
    _fake_urlopen({"http://x/a.py": data}, monkeypatch)
    target = os.path.join(up.base, "a.py")
    open(target, "w", encoding="utf-8").write("old = 1\n")

    r = up.download_and_install(_manifest([{
        "path": "a.py", "url": "http://x/a.py",
        "sha256": hashlib.sha256(data).hexdigest()}]))
    bk = r.get("备份")
    assert bk and os.path.isdir(bk), "没做备份：%r" % bk
    kept = os.path.join(bk, "a.py")
    assert os.path.exists(kept), "备份目录里没有原文件"
    assert open(kept, encoding="utf-8").read() == "old = 1\n"


def test_replace_failure_rolls_back(up, monkeypatch):
    """⚠️ **替换中途失败必须回滚** —— 否则程序会处于"改了一半"的状态

    那是比"更新失败"更糟的情况：一半新一半旧，
    程序可能**直接起不来**，而且用户无从判断。

    这里让**第二个**文件替换时失败，看第一个有没有被还原。
    """
    up._allow_unsigned_update = lambda: True
    up.ask_confirm = lambda text: True
    d1, d2 = b"new1 = 1\n", b"new2 = 2\n"
    _fake_urlopen({"http://x/a.py": d1, "http://x/b.py": d2}, monkeypatch)
    fa = os.path.join(up.base, "a.py")
    fb = os.path.join(up.base, "b.py")
    open(fa, "w", encoding="utf-8").write("old1 = 1\n")
    open(fb, "w", encoding="utf-8").write("old2 = 2\n")

    # 让第二个文件的 copy2 失败
    real_copy2 = shutil.copy2
    state = {"n": 0}

    def flaky(src, dst, *a, **k):
        if dst == fb:
            raise OSError("磁盘满了")
        return real_copy2(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "copy2", flaky)
    r = up.download_and_install(_manifest([
        {"path": "a.py", "url": "http://x/a.py",
         "sha256": hashlib.sha256(d1).hexdigest()},
        {"path": "b.py", "url": "http://x/b.py",
         "sha256": hashlib.sha256(d2).hexdigest()},
    ]))
    assert r["ok"] is False, r
    assert "回滚" in r["错误"], r
    # a.py 必须被还原
    assert open(fa, encoding="utf-8").read() == "old1 = 1\n", \
        "替换失败却没把 a.py 还原 —— 程序会处于改了一半的状态"


def test_install_records_history(up, monkeypatch):
    """装了要留一条历史（对话框会读它，用户靠它知道"什么时候更新过"）"""
    up._allow_unsigned_update = lambda: True
    up.ask_confirm = lambda text: True
    data = b"new = 1\n"
    _fake_urlopen({"http://x/a.py": data}, monkeypatch)
    open(os.path.join(up.base, "a.py"), "w", encoding="utf-8").write("o\n")
    up.download_and_install(_manifest([{
        "path": "a.py", "url": "http://x/a.py",
        "sha256": hashlib.sha256(data).hexdigest()}], ver="9.9.9"))
    hp = os.path.join(up.base, "updates", "update_history.jsonl")
    assert os.path.exists(hp), "没记更新历史"
    rec = json.loads(open(hp, encoding="utf-8").read().strip().splitlines()[-1])
    assert rec["to"] == "9.9.9", rec
    assert rec["files"] == 1, rec


def test_progress_callback_called(up, monkeypatch):
    """进度回调要被调用（界面上那根进度条靠它）"""
    up._allow_unsigned_update = lambda: True
    up.ask_confirm = lambda text: True
    data = b"x = 1\n"
    _fake_urlopen({"http://x/a.py": data}, monkeypatch)
    got = []
    up.download_and_install(_manifest([{
        "path": "a.py", "url": "http://x/a.py",
        "sha256": hashlib.sha256(data).hexdigest()}]),
        progress_cb=lambda i, t, rel: got.append((i, t, rel)))
    assert got, "进度回调一次都没调"
    assert got[-1][1] == 1, got


# ══════════════════════════════════════════════════════════════
# ⑥ 备份 / 回滚 / 版本比较
# ══════════════════════════════════════════════════════════════
def test_backup_current_makes_dir(up):
    open(os.path.join(up.base, "a.py"), "w", encoding="utf-8").write("x=1\n")
    bk = up.backup_current()
    assert bk and os.path.isdir(bk), bk


def test_version_tuple_parsing(up):
    """版本比较的解析 —— 它错了会装成旧版/漏更新"""
    assert up._version_tuple("v25.1.6") == (25, 1, 6), up._version_tuple("v25.1.6")
    assert up._version_tuple("25.1.6") == (25, 1, 6)
    assert up._version_tuple("v26.0.0") > up._version_tuple("v25.9.9")


def test_allow_self_upgrade_defaults_on_by_design(up, monkeypatch):
    """⚠️ 自升级开关**默认是开的** —— 这是**有意**的，不是漏了

    代码里的注释写着："「自主.升级」规则，默认开（等于改动前的无条件执行）"
    —— 也就是加这个开关时选了"保持原有行为"，而不是"默认关掉"。

    我一开始断言它该默认关，跑出来是红的 —— 看过代码才确认是我想当然了。

    记录一下这个取舍（不是要改它，是要让下一个人知道它是有意的）：
      · 支持默认开：它只决定"规则开关"，真正动手前还有
        `ask_confirm()` 弹窗 + 沙盒验证 + 备份回滚
      · 风险：`run_auto_update()` 的设计就是**让程序改自己的代码**，
        默认开意味着"没特别设置过的情况下它是允许这么做的"
      · 真要收紧的话，改 `trunk.rule("自主.升级", True)` 的默认值即可，
        但那是产品决策，不是测试该单方面定的
    """
    monkeypatch.delenv("X6_ALLOW_SELF_UPGRADE", raising=False)
    assert up._allow_self_upgrade() is True, \
        "默认值变了？那要重新评估上面的取舍"


def test_allow_unsigned_default_off(up, monkeypatch):
    """⚠️ 未签名更新**默认必须拒绝**

    这是更新的信任根：验签是唯一能证明"这个包是作者发的"的手段。
    默认放开等于把远程代码执行的门开着。
    """
    monkeypatch.delenv("X6_ALLOW_UNSIGNED_UPDATE", raising=False)
    u2 = AutoUpdater(FakeTrunk(str(up.base)))
    assert not u2._allow_unsigned_update(), \
        "未签名更新默认是开着的 —— 非常危险"
