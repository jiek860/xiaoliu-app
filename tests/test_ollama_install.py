# -*- coding: utf-8 -*-
"""Ollama 一键下载 + 云端服务商预设的测试

背景
----
对比同类程序（E:\\程序代码编辑器）后补上的两条差距：
    1. 它把 Ollama 下载安装做成了**程序内一键完成 + 进度条**，
       小6 原来只给一句"去官网下载"。
    2. 它有云端模型"一键填入"常见服务商，小6 原来要用户自己抄 URL。

本文件守住：
    · 下载源列表非空、地址形如 exe、都是"不带版本号"的稳定地址
    · 自动挑源能挑出东西、挑不到时不崩
    · 下载能报进度、能取消、取消后不留半个文件
    · 安装包大小写的是**实测值**（写小了用户会以为下完了）
    · 云端预设的地址格式正确、能按名字找到
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core import model_setup                    # noqa: E402
from core import ollama_installer as oi         # noqa: E402


# ── 下载源 ──
def test_sources_are_not_empty_and_have_names():
    assert oi.SOURCES, "下载源列表是空的"
    for s in oi.SOURCES:
        assert s.get("名字"), s
        assert s.get("url", "").startswith("http"), s
        assert s.get("实测"), "每个源都该记着实测数据：%s" % s.get("名字")


def test_sources_point_at_the_installer():
    for s in oi.SOURCES:
        assert s["url"].endswith("OllamaSetup.exe"), \
            "这个源下的不是 OllamaSetup.exe：%s" % s["url"]


def test_sources_are_versionless():
    """地址里不能带版本号

    钉了版本号就会随官方发版而失效 —— 用户点下载拿到 404。
    必须用 /releases/latest/download/ 这种"永远指向最新"的地址。
    """
    for s in oi.SOURCES:
        u = s["url"]
        if "github.com" not in u:
            continue                     # 官网直链本来就不带版本
        assert "/releases/latest/download/" in u, \
            "这个源钉了版本号，官方发版后会 404：%s" % u
        # 不能出现 vX.Y.Z 这种版本号
        import re
        m = re.search(r"/download/v?\d+\.\d+", u)
        assert not m, "地址里有版本号：%s" % u


def test_at_least_one_accelerated_source():
    """必须至少有一个国内加速源

    实测官网直链 0.05 MB/s、GitHub 0.08 MB/s —— 下 1.5GB 要 5~8 小时。
    只有它们等于没有可用的下载方式。
    """
    acc = [s for s in oi.SOURCES
           if any(h in s["url"] for h in
                  ("gh-proxy.com", "ghproxy.net", "ghfast.top",
                   "ghproxy", "gh-proxy"))]
    assert acc, "一个国内加速源都没有"
    assert acc[0] is oi.SOURCES[0], \
        "加速源应该排在前面（默认优先级），实际第一个是 %s" % oi.SOURCES[0]["名字"]


def test_official_source_kept_as_fallback():
    """官网要留着兜底 —— 第三方加速随时可能挂"""
    urls = " ".join(s["url"] for s in oi.SOURCES)
    assert "ollama.com" in urls, "没有官网兜底源"


def test_approx_size_is_realistic():
    """安装包大小要写**实测值**

    实测 1509 MB（现在的 Ollama 把 GPU 运行库打进去了）。
    写小了（比如"约 100MB"）用户会以为卡住或者下完了其实没有。
    """
    assert oi.APPROX_MB >= 500, \
        "安装包大小写着 %d MB —— 比实测小太多，用户会误判" % oi.APPROX_MB
    assert "1509" in oi.info()["安装包大小"] or \
        str(oi.APPROX_MB) in oi.info()["安装包大小"]


def test_pick_best_returns_none_when_nothing_works():
    """所有源都连不上时要返回 None，不能抛"""
    saved = oi.SOURCES[:]
    try:
        oi.SOURCES[:] = [{"名字": "假的", "url": "http://127.0.0.1:1/x.exe",
                          "实测": "无"}]
        assert oi.pick_best(timeout=2) is None
    finally:
        oi.SOURCES[:] = saved


def test_probe_reports_failure_without_raising():
    r = oi.probe("http://127.0.0.1:1/none.exe", timeout=2)
    assert isinstance(r, dict) and r["ok"] is False
    assert r.get("错误"), "失败时要说明原因"


# ── 下载 ──
def test_download_cancels_and_cleans_up():
    """取消后不能留下半个文件

    留半个 exe 最坏：用户双击它，得到一个"安装程序已损坏"的报错，
    完全不知道是自己上次取消造成的。
    """
    import tempfile
    d = os.path.join(tempfile.mkdtemp(prefix="x6dl_"), "a.exe")
    r = oi.download(oi.SOURCES[0]["url"], dest=d,
                    should_stop=lambda: True)      # 立刻取消
    assert r.get("取消") is True, r
    assert not os.path.exists(d), "留下了半个文件"
    assert not os.path.exists(d + ".part"), "留下了 .part"


def test_download_bad_url_returns_error():
    import tempfile
    d = os.path.join(tempfile.mkdtemp(prefix="x6dl_"), "b.exe")
    r = oi.download("http://127.0.0.1:1/none.exe", dest=d)
    assert r.get("ok") is False and r.get("错误"), r
    assert not os.path.exists(d)


def test_run_installer_refuses_missing_or_truncated_file():
    """安装包不存在 / 太小（没下完）时要拒绝，别把坏文件拉起来"""
    r = oi.run_installer(os.path.join(BASE, "绝对不存在的文件.exe"))
    assert r.get("ok") is False and "不存在" in r.get("错误", "")

    import tempfile
    p = os.path.join(tempfile.mkdtemp(prefix="x6dl_"), "tiny.exe")
    with open(p, "wb") as f:
        f.write(b"MZ" + b"x" * 100)              # 只有 102 字节
    r2 = oi.run_installer(p)
    assert r2.get("ok") is False, "没下完的安装包不该被拉起来"
    assert "太小" in r2.get("错误", "") or "下完" in r2.get("错误", "")


# ── 云端服务商预设 ──
def test_cloud_providers_have_required_fields():
    assert model_setup.CLOUD_PROVIDERS, "服务商预设是空的"
    for p in model_setup.CLOUD_PROVIDERS:
        for k in ("名字", "地址", "模型", "申请", "备注"):
            assert p.get(k), "缺字段 %s：%s" % (k, p)


def test_cloud_urls_look_like_chat_endpoints():
    """地址必须是 chat/completions 这种完整接口地址

    填成 base URL（比如 https://api.deepseek.com）会 404 ——
    这是用户自己抄地址时最容易犯的错，预设里不能也犯。
    """
    for p in model_setup.CLOUD_PROVIDERS:
        u = p["地址"]
        assert u.startswith("https://"), u
        assert "chat/completions" in u, \
            "%s 的地址不像对话接口地址：%s" % (p["名字"], u)


def test_provider_names_and_lookup():
    names = model_setup.provider_names()
    assert "自定义（自己填）" in names, "没有『自定义』选项"
    assert len(names) == len(model_setup.CLOUD_PROVIDERS) + 1
    for p in model_setup.CLOUD_PROVIDERS:
        got = model_setup.find_provider(p["名字"])
        assert got is p, "按名字找不到：%s" % p["名字"]
    assert model_setup.find_provider("自定义（自己填）") is None
    assert model_setup.find_provider("不存在的服务商") is None


def test_no_dead_provider_in_presets():
    """预设里不能有"连都连不上"的服务商

    实测 OpenAI 在国内直连超时 —— 收进来只会让用户白填一次再失败。
    这条用**本地判断**（不联网，避免测试依赖网络）：
    每个预设要么标注了国内直连，要么在备注里说明限制。
    """
    for p in model_setup.CLOUD_PROVIDERS:
        assert ("直连" in p["备注"]) or ("国内" in p["备注"]), \
            "%s 没说明国内能不能直连：%s" % (p["名字"], p["备注"])
