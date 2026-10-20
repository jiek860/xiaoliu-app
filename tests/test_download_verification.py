# -*- coding: utf-8 -*-
"""下载内容的校验必须真的在生效（#8）

先说清楚核对结果：**这层保护小6 已经有了**，而且比 DSH 的 payloadDigest 强。
    DSH:  runtime.json 里记 payloadDigest（**未签名**的哈希）
    小6:  1) plugin_market 装模块前
              sha256 比对 -> RSA 验签 -> 没登记则**默认拒绝**
              （除非 data/config.json 显式开 allow_unsigned_plugins）
          2) auto_updater 装更新前
              清单验签 -> 下载到 staging -> **逐文件 sha256 校验**
              -> 确认 -> 备份 -> 替换（装之前**再验一次签**）

**缺的不是保护，是"保护有没有生效"没有任何测试钉住** ——
一次重构就可能把它悄悄去掉，而且去掉之后一切照常工作（只是不再验了），
这正是最危险的坏法。

本文件把这几条钉死。
"""
import hashlib
import json
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.conftest import make_trunk               # noqa: E402


@pytest.fixture(scope="module")
def pm():
    t = make_trunk()
    return t._load_lazy("plugin_market")


# ── plugin_market：装模块前的三重校验 ──
def test_hash_mismatch_is_rejected(pm):
    """内容与清单 sha256 不符 -> 必须拒绝"""
    raw = b"print('hello')\n"
    meta = {"sha256": hashlib.sha256(b"other content").hexdigest()}
    res, why = pm._verify_meta(raw, meta)
    assert res is False, "哈希不符竟然通过了"
    assert "sha256" in why or "不匹配" in why, why


def test_good_hash_but_bad_signature_is_rejected(pm):
    """sha256 对得上、但签名验不过 -> 也要拒绝（防止改了清单里的哈希）"""
    raw = b"print('hello')\n"
    good = hashlib.sha256(raw).hexdigest()
    meta = {"sha256": good, "signature": "AAAA" + "B" * 60}
    res, why = pm._verify_meta(raw, meta)
    assert res is False, "签名验不过竟然通过了"
    assert "签名" in why, why


def test_unregistered_module_needs_explicit_optin(pm):
    """清单里没有 sha256/签名 -> 返回 None（由调用方按配置决定）"""
    res, why = pm._verify_meta(b"x", {})
    assert res is None, "没登记信息却给了明确结论：%r" % res
    assert "没有" in why or "缺少" in why, why


def test_missing_metadata_is_refused_by_default():
    """关键：**每一条安装路径**都必须"没登记就拒绝"

    ⚠️ 第一版只断言 `"if res is None and not self._allow_unsigned()" in src` ——
    负向测试把第一处改成 `if False:` 后它照样通过，因为
    **plugin_market 里有两条安装路径**（L234 与 L332），第二处还在，
    字符串一存在断言就成立。
    只钉住其中一条路径，等于另一条没有保护。
    改成：每处 _verify_meta 调用后面都必须跟着这个守卫。
    """
    p = os.path.join(BASE, "modules", "installed", "plugin_market.py")
    lines = open(p, encoding="utf-8").read().splitlines()
    call_sites = [i for i, l in enumerate(lines) if "_verify_meta(" in l
                  and "def " not in l]
    assert call_sites, "找不到 _verify_meta 的调用处"
    for i in call_sites:
        seg = "\n".join(lines[i:i + 8])
        assert "res is None" in seg, \
            "第 %d 行的 _verify_meta 调用后面没有『没登记就拒绝』的守卫：\n%s" \
            % (i + 1, seg)
        assert "_allow_unsigned()" in seg, \
            "第 %d 行的守卫没有走 allow_unsigned 开关" % (i + 1)
        assert '"ok": False' in seg, \
            "第 %d 行的守卫没有真的拒绝（没返回 ok:False）" % (i + 1)


def test_every_install_path_verifies(pm):
    """有两条安装路径就要验两遍 —— 数一数，别漏掉一条"""
    p = os.path.join(BASE, "modules", "installed", "plugin_market.py")
    src = open(p, encoding="utf-8").read()
    n_calls = src.count("_verify_meta(") - 1          # 减掉 def 那一处
    assert n_calls >= 2, \
        "只找到 %d 处校验调用 —— 安装路径可能不止一条，别漏" % n_calls


def test_allow_unsigned_defaults_to_false(pm):
    """允许无签名的开关默认必须是关的"""
    # 默认配置里不该有 allow_unsigned_plugins=True
    src = open(os.path.join(BASE, "modules", "installed",
                            "plugin_market.py"), encoding="utf-8").read()
    assert 'get("allow_unsigned_plugins", False)' in src, \
        "开关的默认值不是 False"


def test_signature_is_verified_not_just_hash():
    """必须真的走 RSA 验签，不能只比 sha256

    只比 sha256 的话，能改内容的人通常也能改清单里的 sha256 —— 等于没验。
    """
    src = open(os.path.join(BASE, "modules", "installed",
                            "plugin_market.py"), encoding="utf-8").read()
    assert "verify_hash" in src, "没有调用 RSA 验签"
    assert "_signer()" in src, "没有取签名器"


# ── auto_updater：装更新前的校验 ──
@pytest.fixture(scope="module")
def au():
    t = make_trunk()
    return t._load_lazy("auto_updater")


def test_updater_verifies_manifest_signature(au):
    """更新清单必须验签 —— 否则可以伪造一个"官方更新"塞任意代码"""
    src = (open(os.path.join(BASE, "modules", "installed", "auto_updater.py"),
                encoding="utf-8").read() + "\n" +
           open(os.path.join(BASE, "core", "auto_update_download.py"),
                encoding="utf-8").read())
    assert "verify_manifest" in src, "更新清单没有验签"
    assert "签名缺失或被篡改" in src, "验签失败后没有明确拒绝的文案"


def test_updater_verifies_each_file_hash(au):
    src = (open(os.path.join(BASE, "modules", "installed", "auto_updater.py"),
                encoding="utf-8").read() + "\n" +
           open(os.path.join(BASE, "core", "auto_update_download.py"),
                encoding="utf-8").read())
    assert "hashlib.sha256(data).hexdigest()" in src, \
        "没有逐文件校验 sha256"
    assert "sha256 不符" in src, "校验失败后没有明确拒绝的文案"


def test_updater_verifies_again_before_install(au):
    """**装之前要再验一次签**（下载和安装之间隔着用户确认，有时间窗）

    ⚠️ 第一版只数 `verify_manifest` 出现次数 —— 负向测试把它改成
    `if False and not release_sign.verify_manifest(...)` 后次数没变，
    照样通过。**数出现次数不等于数"真的在把关"**。
    改成：每一处 verify_manifest 调用后面都要跟着"失败就返回"。
    """
    p = os.path.join(BASE, "core", "auto_update_download.py")
    lines = open(p, encoding="utf-8").read().splitlines()
    sites = [i for i, l in enumerate(lines)
             if "verify_manifest(" in l and "def " not in l]
    assert len(sites) >= 2, \
        "只找到 %d 处验签 —— 下载与安装之间应当各验一次" % len(sites)
    for i in sites:
        seg = "\n".join(lines[i:i + 6])
        assert "if not" in seg, \
            "第 %d 行的验签没有把结果当条件用（可能是 if False and ...）：\n%s" \
            % (i + 1, seg)
        assert "return" in seg, \
            "第 %d 行的验签失败后没有返回（没真的拦住）" % (i + 1)


def test_updater_backs_up_before_replacing(au):
    """替换程序文件前必须先备份（出问题要能回滚）"""
    src = open(os.path.join(BASE, "core",
                            "auto_update_download.py"), encoding="utf-8").read()
    assert "备份" in src, "没有备份步骤"
    i_dl = src.find("download_and_install")
    assert i_dl >= 0
    seg = src[i_dl:i_dl + 2000]
    assert "备份" in seg, "下载安装流程里没有备份"


# ── 这两条保护不能只写在注释里 ──
def test_protection_code_is_reachable():
    """校验代码必须真的在安装路径上，不能是"写了但没人调"的死代码

    这类"保护存在但没接上"的坏法，这一轮已经踩过一次
    （tool_presets 的 bg 字段标了没接上）。
    """
    src = open(os.path.join(BASE, "modules", "installed",
                            "plugin_market.py"), encoding="utf-8").read()
    # 定义处
    assert "def _verify_meta" in src
    # 调用处（至少一次，且在 install 流程里）
    assert src.count("_verify_meta(") >= 2, \
        "_verify_meta 只有定义没有调用 —— 保护没接上"
