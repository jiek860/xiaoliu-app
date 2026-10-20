# -*- coding: utf-8 -*-
"""导出类能力的产品级加固测试

覆盖两件事（都是"看起来成功、其实少了东西"那类问题）：
    ① 崩溃包的脱敏：原来靠硬编码 3 个键名 —— 将来加了新密钥就会**静默漏出去**，
       而崩溃包恰恰是"发给别人帮你排查"的，漏一次就是真泄露。
       现在按模式脱敏 + 名单兜底。
    ② 迁移包的完整性：写不进 zip 的文件原来 `except: pass` 静默跳过，
       最后照样返回 {"ok": True} —— 用户以为备份完整，换电脑才发现少数据。
       现在把跳过数量和原因报出来。
"""
import json
import os
import sys
import tempfile
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.crash_export import _redact          # noqa: E402
from core.trunk import Trunk                   # noqa: E402
from tests.conftest import make_trunk          # noqa: E402


# ── 脱敏 ──
def test_redact_covers_hardcoded_names():
    """原来名单里的 3 个仍然脱敏（不能改出回归）"""
    out, n = _redact({
        "cloud_key": "FAKE_GLM_KEY_FOR_TEST",
        "feedback_email_pass": "FAKE_EMAIL_AUTH_FOR_TEST",
        "wecom_webhook": "https://qyapi.weixin.qq.com/x",
    })
    assert all(out[k] == "***已脱敏***" for k in
               ("cloud_key", "feedback_email_pass", "wecom_webhook")), out
    assert n == 3


def test_redact_catches_unknown_secret_names():
    """**本次改进的重点**：名单里没有、但名字像密钥的，也要脱"""
    out, _ = _redact({
        "some_new_api_token": "abcdef1234567890",
        "my_secret": "hello",
        "db_password": "p@ssw0rd",
        "github_credential": "ghp_xxx",
        "nested": {"inner_secret": "xyz"},
    })
    assert out["some_new_api_token"] == "***已脱敏***"
    assert out["my_secret"] == "***已脱敏***"
    assert out["db_password"] == "***已脱敏***"
    assert out["github_credential"] == "***已脱敏***"
    assert out["nested"]["inner_secret"] == "***已脱敏***"


def test_redact_does_not_touch_numeric_settings():
    """数字设置不能被误伤 —— 脱了它崩溃包反而更难排查

    回归：`max_tokens_reply = 500` 曾因为键名含 "token" 被误脱敏。
    """
    out, _ = _redact({
        "max_tokens_reply": 500,
        "token_limit": 100,
        "secret_count": 0,
        "timeout": 30,
    })
    assert out["max_tokens_reply"] == 500
    assert out["token_limit"] == 100
    assert out["secret_count"] == 0
    assert out["timeout"] == 30


def test_redact_does_not_touch_urls_and_plain_values():
    """URL 和普通值不能被误伤"""
    out, _ = _redact({
        "cloud_url": "https://open.bigmodel.cn/api",
        "ollama_url": "http://192.168.1.2:11434",
        "ai_name": "小6",
        "font_size": 13,
    })
    assert out["cloud_url"].startswith("https://")
    assert out["ollama_url"].startswith("http://")
    assert out["ai_name"] == "小6"
    assert out["font_size"] == 13


# ── 迁移包 ──
def test_migration_export_reports_packed_count():
    """迁移包要报告打了多少文件（否则没法判断完整性）

    用临时小目录而不是整个项目 —— 压 1200+ 个文件要 40 秒，
    而我们验的是"有没有报数"这个行为，不是压缩性能。
    """
    import shutil
    from core.migration import Migration

    tmpbase = tempfile.mkdtemp(prefix="x6_mig_")
    try:
        for d in ("data", "core"):
            os.makedirs(os.path.join(tmpbase, d), exist_ok=True)
        for i in range(5):
            with open(os.path.join(tmpbase, "data", "f%d.txt" % i), "w",
                      encoding="utf-8") as f:
                f.write("x" * 50)
        with open(os.path.join(tmpbase, "core", "a.py"), "w",
                  encoding="utf-8") as f:
            f.write("pass\n")

        class _T:
            base = tmpbase
        mg = Migration(_T())
        out = os.path.join(tempfile.gettempdir(), "x6_test_migrate.zip")
        try:
            r = mg.export(out)
            assert r.get("ok") is True, r
            assert r.get("已打包", 0) >= 6, "没报告打包数量：%s" % r
            assert "跳过" not in r, "没有跳过却报了跳过：%s" % r
            assert os.path.exists(out)
        finally:
            if os.path.exists(out):
                os.remove(out)
    finally:
        shutil.rmtree(tmpbase, ignore_errors=True)


# ── 崩溃包 ──
def test_crash_export_states_redaction_and_lists_files():
    """崩溃包要说明脱敏了几个字段，且 config 真的进包"""
    t = make_trunk()
    ce = t._load_lazy("crash_export")
    tmp = os.path.join(tempfile.gettempdir(), "x6_test_crash.zip")
    try:
        r = ce.export(tmp)
        assert r.get("ok") is True, r
        assert "打包说明" in r, "没说明 config 的状态"
        with zipfile.ZipFile(tmp) as z:
            names = z.namelist()
        assert "system_info.txt" in names
        # config.json 在（有配置时）或有一份说明，总之不能静默少文件
        assert ("config.json" in names) or ("config_读取失败.txt" in names), names
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def test_crash_export_config_is_actually_redacted():
    """进包的 config 里不能有明文密钥（端到端，不只看函数）"""
    t = make_trunk()
    ce = t._load_lazy("crash_export")
    tmp = os.path.join(tempfile.gettempdir(), "x6_test_crash2.zip")
    try:
        ce.export(tmp)
        with zipfile.ZipFile(tmp) as z:
            if "config.json" not in z.namelist():
                return                      # 没有配置，跳过
            cfg = json.loads(z.read("config.json").decode("utf-8"))
        for k, v in cfg.items():
            if any(w in k.lower() for w in
                   ("key", "secret", "webhook", "passwd", "password")):
                if isinstance(v, str) and v and v != "***已脱敏***":
                    pytest_fail = "崩溃包里 %s 是明文：%s" % (k, v[:12])
                    raise AssertionError(pytest_fail)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
