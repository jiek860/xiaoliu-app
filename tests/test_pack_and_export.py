# -*- coding: utf-8 -*-
"""B6：打包 / 导出 / 安全四个模块

守住的都是**"看起来成功、其实有洞"**的那类问题：
    ① cookie 明文落盘（登录凭证被备份/迁移顺手带走）
    ② 人格包/迁移包照着包内路径乱写（zip slip）+ 改了内容也不报（无校验和）
    ③ 迁移包一键覆盖当前数据（没有确认步骤）
    ④ 验签失败只有一个 False（不知道为什么）
    ⑤ 崩溃包/脱敏规则只覆盖老几样，新密钥格式静默漏出
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


class _T:
    def __init__(self, base, modules=None, config=None):
        self.base = str(base)
        self.data_dir = os.path.join(str(base), "data")
        self.modules = modules or {}
        self.config = config or {}


def _tmp():
    return tempfile.mkdtemp(prefix="x6b6s_")


def _write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if mode == "wb" and isinstance(text, str):
        text = text.encode("utf-8")      # 方便直接用 PEM 字符串写二进制文件
    with open(path, mode, **({} if mode == "wb" else {"encoding": "utf-8"})) as f:
        f.write(text)
    return path


# ══════════════════════════════════════════════════════════════
# browser_session
# ══════════════════════════════════════════════════════════════
def _session(base, modules=None):
    from core.browser_session import BrowserSession
    return BrowserSession(_T(base, modules=modules))


class _FakePage:
    def __init__(self):
        self.added = []

        class _Ctx:
            def __init__(self, outer):
                self.outer = outer

            def add_cookies(self, cookies):
                self.outer.added = list(cookies)

            def cookies(self):
                return [{"name": "sid", "value": "secret-value"}]

        self.context = _Ctx(self)


class _FakeBrowser:
    def __init__(self):
        self._page = _FakePage()


def test_session_refuses_empty_cookies():
    bs = _session(_tmp())
    r = bs.save("登录")
    assert r["ok"] is False and "没拿到 cookie" in r["错误"], r


def test_session_encrypts_cookies_at_rest():
    import core.browser_session as mod
    base = _tmp()
    bs = _session(base)
    r = bs.save("登录", cookies=[{"name": "sid", "value": "secret-value"}])
    assert r["ok"] is True, r
    raw = open(r["文件"], "rb").read()
    if mod._aesgcm() is not None:
        assert raw.startswith(b"X6SESS1"), "加密格式标识不对"
        assert b"secret-value" not in raw, "cookie 明文还在文件里"
        assert r["加密"] == "AES-GCM", r
    else:
        assert r["加密"].startswith("明文"), r


def test_session_load_roundtrip_and_browser_absent():
    base = _tmp()
    bs = _session(base)
    bs.save("登录", cookies=[{"name": "sid", "value": "v"}])
    r = bs.load("登录")
    assert r["ok"] is True, r
    assert r["cookie数"] == 1
    assert "浏览器未启动" in r["状态"]


def test_session_load_into_browser_and_from_old_plain_json():
    base = _tmp()
    fb = _FakeBrowser()
    bs = _session(base, modules={"browser": fb})
    bs.save("登录", cookies=[{"name": "sid", "value": "v"}])
    r = bs.load("登录")
    assert r["ok"] is True and r["状态"] == "已加载到浏览器", r
    assert fb._page.added and fb._page.added[0]["name"] == "sid"

    # 旧版明文 JSON 也要能读
    _write(os.path.join(base, "data", "browser_sessions", "旧.json"),
           json.dumps([{"name": "old", "value": "x"}]))
    r2 = bs.load("旧")
    assert r2["ok"] is True and r2["加密"] == "明文（旧格式）", r2


def test_session_corrupt_and_missing_files_are_reported():
    base = _tmp()
    bs = _session(base)
    assert bs.load("没有这个")["ok"] is False
    _write(os.path.join(base, "data", "browser_sessions", "坏.json"),
           b"X6SESS1" + b"\x00" * 40, mode="wb")
    r = bs.load("坏")
    assert r["ok"] is False and "解密失败" in r["错误"], r


def test_session_list_delete_and_run():
    base = _tmp()
    bs = _session(base)
    bs.save("a", cookies=[{"name": "n", "value": "v"}])
    assert bs.list() == ["a"]
    assert bs.delete("a")["ok"] is True
    assert bs.list() == []
    r = bs.run()
    assert r["会话数"] == 0 and r["加密方式"]


# ══════════════════════════════════════════════════════════════
# personality_market
# ══════════════════════════════════════════════════════════════
def _market(base):
    from core.personality_market import PersonalityMarket
    return PersonalityMarket(_T(base))


def _make_personality(base, mood="开心"):
    _write(os.path.join(base, "data", "personality.json"),
           json.dumps({"mood": mood}, ensure_ascii=False))
    _write(os.path.join(base, "data", "memory_cards.jsonl"),
           json.dumps({"facts": ["偏好:音乐"]}, ensure_ascii=False) + "\n")


def _pack(base):
    _make_personality(base)
    out = os.path.join(base, "pack.zip")
    r = _market(base).export_personality(out)
    assert r["ok"] is True, r
    return out


def test_personality_export_requires_files_and_writes_manifest():
    base = _tmp()
    from core.personality_market import MANIFEST
    assert _market(base).export_personality(os.path.join(base, "x.zip"))["ok"] is False
    out = _pack(base)
    with zipfile.ZipFile(out) as z:
        assert MANIFEST in z.namelist()
        manifest = json.loads(z.read(MANIFEST).decode("utf-8"))
    assert manifest["版本"]
    assert {f["名称"] for f in manifest["文件"]} >= {"personality.json"}


def test_personality_verify_detects_tampering():
    base = _tmp()
    out = _pack(base)
    pm = _market(base)
    assert pm.verify(out)["校验"] == "通过"

    # 改内容但保留原清单 → 校验必须不过
    with zipfile.ZipFile(out) as z:
        manifest = z.read("manifest.json")
    tampered = os.path.join(base, "tampered.zip")
    with zipfile.ZipFile(tampered, "w") as z:
        z.writestr("personality.json", json.dumps({"mood": "被改过"}))
        z.writestr("manifest.json", manifest)
    bad = pm.verify(tampered)
    assert bad["ok"] is False and bad["校验"] == "不匹配", bad
    # 默认拒绝导入
    r = pm.import_personality(tampered)
    assert r["ok"] is False and "校验没过" in r["error"], r


def test_personality_import_overwrites_or_stages():
    base = _tmp()
    out = _pack(base)
    pm = _market(base)

    ok = pm.import_personality(out, overwrite=True)
    assert ok["ok"] is True and ok["导入"] == ["personality.json",
                                             "memory_cards.jsonl"], ok
    assert ok["目录"] == os.path.join(base, "data")

    staged = pm.import_personality(out, overwrite=False)
    assert staged["ok"] is True, staged
    assert os.path.isdir(staged["目录"])
    assert not staged["目录"].endswith(os.sep + "data"), staged
    assert "没有覆盖" in staged["msg"]


def test_personality_import_rejects_traversal_and_ignores_code():
    base = _tmp()
    out = os.path.join(base, "evil.zip")
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("../personality.json", json.dumps({"mood": "越界"}))
        z.writestr("core/evil.py", "print('不该落盘')")
        z.writestr("personality.json", json.dumps({"mood": "正常"}))
    pm = _market(base)
    r = pm.import_personality(out, overwrite=True)
    assert r["ok"] is True, r
    assert r.get("拒绝"), r
    assert r.get("忽略"), r
    # 包外面不能多出文件
    assert not os.path.exists(os.path.join(os.path.dirname(base), "personality.json"))
    assert not os.path.exists(os.path.join(base, "core", "evil.py"))


def test_personality_missing_pack_is_reported():
    r = _market(_tmp()).import_personality("不存在.zip")
    assert r["ok"] is False and "文件不存在" in r["error"]


# ══════════════════════════════════════════════════════════════
# migration
# ══════════════════════════════════════════════════════════════
def _migration(base):
    from core.migration import Migration
    return Migration(_T(base))


def _small_base():
    base = _tmp()
    for d in ("data", "core"):
        os.makedirs(os.path.join(base, d), exist_ok=True)
    for i in range(5):
        _write(os.path.join(base, "data", "f%d.txt" % i), "x" * 50)
    _write(os.path.join(base, "core", "a.py"), "pass\n")
    return base


def test_migration_export_counts_files():
    base = _small_base()
    out = os.path.join(base, "backup.zip")
    r = _migration(base).export(out)
    assert r["ok"] is True and r["已打包"] >= 6, r
    assert "跳过" not in r
    assert os.path.isfile(out)


def test_migration_export_bad_path_returns_error():
    base = _small_base()
    r = _migration(base).export("Z:\\不存在\\x6.zip")
    assert isinstance(r, dict) and r["ok"] is False, r


def test_migration_import_requires_confirmation_before_overwrite():
    src = _small_base()
    out = os.path.join(src, "backup.zip")
    _migration(src).export(out)

    dst = _small_base()
    before = open(os.path.join(dst, "data", "f0.txt"), encoding="utf-8").read()
    r = _migration(dst).import_zip(out)
    assert r["ok"] is False and r.get("需要确认") is True, r
    assert r["将覆盖"], r
    # 关键：没有确认就一个字节都不该写
    after = open(os.path.join(dst, "data", "f0.txt"), encoding="utf-8").read()
    assert before == after

    r2 = _migration(dst).import_zip(out, overwrite=True)
    assert r2["ok"] is True and r2["解压"] >= 6, r2
    assert r2["覆盖"] >= 1


def test_migration_import_rejects_traversal():
    dst = _tmp()
    out = os.path.join(dst, "evil.zip")
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("../evil.txt", "越界")
        z.writestr("data/ok.txt", "ok")
    r = _migration(dst).import_zip(out, overwrite=True)
    assert r["ok"] is True, r
    assert r["解压"] == 1, r
    assert r.get("拒绝"), r
    assert not os.path.exists(os.path.join(os.path.dirname(dst), "evil.txt"))


def test_migration_import_missing_file():
    r = _migration(_tmp()).import_zip("不存在.zip")
    assert r["ok"] is False and "文件不存在" in r["error"]


# ══════════════════════════════════════════════════════════════
# plugin_signer
# ══════════════════════════════════════════════════════════════
def _signer_with_key():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        import pytest
        pytest.skip("没装 cryptography，验签链路没法测")
    base = _tmp()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    _write(os.path.join(base, "core", "公钥.pem"), pem.decode(), mode="wb")
    from core.plugin_signer import PluginSigner
    return PluginSigner(_T(base)), key


def test_signer_verifies_good_and_rejects_tampered_bytes():
    signer, key = _signer_with_key()
    data = b"module code"
    sig = signer.sign_hash(signer.calc_hash_bytes(data), key)
    assert signer.verify_bytes_detail(data, sig)["ok"] is True
    assert signer.verify_bytes(data, sig) is True

    bad = signer.verify_bytes_detail("module code (改过)".encode("utf-8"), sig)
    assert bad["ok"] is False and "验签不通过" in bad["原因"], bad


def test_signer_explains_why_verification_failed():
    signer, _key = _signer_with_key()
    assert "十六进制" in signer.verify_hash_detail("a" * 64, "这不是hex")["原因"]

    no_key = _tmp()
    from core.plugin_signer import PluginSigner
    s = PluginSigner(_T(no_key))
    r = s.verify_hash_detail("a" * 64, "bb")
    assert r["ok"] is False and "公钥" in r["原因"], r

    missing = signer.verify_plugin_detail(os.path.join(_tmp(), "没有.py"), "bb")
    assert missing["ok"] is False and "文件不存在" in missing["原因"]


def test_signer_plugin_file_roundtrip():
    signer, key = _signer_with_key()
    path = _write(os.path.join(signer.base, "demo_mod.py"), "x = 1\n")
    sig = signer.sign_file(path, key)
    assert signer.verify_plugin(path, sig) is True
    _write(path, "x = 2\n")                    # 落盘后被改
    r = signer.verify_plugin_detail(path, sig)
    assert r["ok"] is False and r["sha256"]


# ══════════════════════════════════════════════════════════════
# crash_export
# ══════════════════════════════════════════════════════════════
def _crash(base):
    from core.crash_export import CrashExport
    return CrashExport(_T(base))


def test_crash_export_packs_logs_and_redacts_config():
    base = _tmp()
    _write(os.path.join(base, "data", "logs", "a.log"), "traceback...")
    _write(os.path.join(base, "data", "config.json"),
           json.dumps({"cloud_key": "SECRET_KEY_VALUE",
                       "model": "glm-4", "max_tokens_reply": 500},
                      ensure_ascii=False))
    out = os.path.join(base, "crash.zip")
    r = _crash(base).export(out)
    assert r["ok"] is True
    assert r["日志数"] == 1
    assert r["脱敏字段"] >= 1
    assert r["打包说明"]                      # 一定要有说明
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "logs/a.log" in names
        assert "config.json" in names
        raw = z.read("config.json").decode("utf-8")
    assert "SECRET_KEY_VALUE" not in raw
    assert "glm-4" in raw
    assert "500" in raw                       # 数字设置不能被误脱敏


def test_crash_export_without_config_leaves_note():
    base = _tmp()
    out = os.path.join(base, "crash.zip")
    r = _crash(base).export(out)
    assert r["ok"] is True and "没有 data/config.json" in r["打包说明"], r
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "config_读取失败.txt" in names
    assert "system_info.txt" in names


def test_crash_export_bad_path_does_not_raise():
    base = _tmp()
    r = _crash(base).export("Z:\\不存在\\崩溃.zip")
    assert isinstance(r, dict) and r["ok"] is False, r


# ══════════════════════════════════════════════════════════════
# sensitive_detector（新增密钥格式）
# ══════════════════════════════════════════════════════════════
def _sd():
    from core.sensitive_detector import SensitiveDetector
    return SensitiveDetector()


SECRET_SAMPLES = [
    ("-----BEGIN RSA PRIVATE KEY-----", "私钥"),  # pragma: allowlist secret
    ("ghp_" + "a" * 36, "GitHub令牌"),
    ("AKIA" + "B" * 16, "AWS密钥"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
     "abcdefghijklmnopqrstuv", "JWT"),
]


def test_new_secret_formats_are_detected():
    sd = _sd()
    for secret, kind in SECRET_SAMPLES:
        found = sd.detect("前缀 %s 后缀" % secret)
        assert any(f["type"] == kind for f in found), (kind, found)


def test_new_secret_formats_are_not_echoed_in_results():
    sd = _sd()
    for secret, _kind in SECRET_SAMPLES:
        blob = json.dumps(sd.detect("里有 %s" % secret), ensure_ascii=False)
        assert secret[:12] not in blob, blob


def test_new_secret_formats_are_masked_and_idempotent():
    sd = _sd()
    for secret, _kind in SECRET_SAMPLES:
        once = sd.mask("敏感 %s 完" % secret)
        assert secret not in once, once
        assert sd.mask(once) == once, once
