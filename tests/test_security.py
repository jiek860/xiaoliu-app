# -*- coding: utf-8 -*-
"""安全回归测试：密钥分离、私钥不外泄、更新包必须验签

这几条对应用户端最容易悄悄退化的地方，改代码后跑一遍即可。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

SKIP_DIRS = {"libs", "optional_libs", "backups", "__pycache__", ".git",
             "node_modules", ".venv", "updates"}


def _all_text_files():
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        for f in files:
            if f.lower().endswith((".py", ".json", ".txt", ".md", ".pem",
                                   ".key", ".ini", ".bat", ".vbs", ".spec")):
                yield os.path.join(root, f)


def test_no_private_key_in_project():
    """项目里不得出现私钥内容"""
    # 拼接构造，避免本文件自身被这条规则误伤
    marker = "-----BEGIN " + "PRIVATE KEY-----"
    bad = []
    for fp in _all_text_files():
        try:
            txt = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if marker in txt:
            bad.append(os.path.relpath(fp, BASE))
    assert not bad, "项目里发现私钥: %s" % bad


def test_no_shared_secret_in_project():
    """HMAC 共享密钥不随程序分发（core/密钥.key 不应存在）"""
    assert not os.path.exists(os.path.join(BASE, "core", "密钥.key")), \
        "core/密钥.key 存在：HMAC 共享密钥会随程序分发，激活码即可被无限伪造"
    assert not os.path.exists(os.path.join(BASE, "密钥.key")), "项目根出现 密钥.key"


def test_activation_key_differs_from_release_key():
    """激活码公钥与更新签名公钥必须是两套（历史上混用导致 RSA 激活码全部验签失败）"""
    a = os.path.join(BASE, "core", "激活公钥.pem")
    b = os.path.join(BASE, "core", "公钥.pem")
    if not (os.path.exists(a) and os.path.exists(b)):
        return  # 缺文件由别的测试覆盖
    na = "".join(open(a, encoding="utf-8").read().split())
    nb = "".join(open(b, encoding="utf-8").read().split())
    assert na != nb, "激活公钥与更新签名公钥相同：两套密钥被混用"


def test_license_secret_is_external():
    """密钥查找优先项目外；找不到时应返回 None 而不是抛异常"""
    from core import license_core as lc
    s = lc.find_license_secret()
    assert s is None or len(s) >= 16
    # 激活公钥必须能加载
    assert lc.load_activation_pubkey(BASE) is not None, "active 公钥加载失败"


def test_manifest_signature_roundtrip():
    """manifest 签名 → 验签必须通过；被篡改必须失败"""
    from core import release_sign
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    manifest = {"version": "9.9.9",
                "files": [{"path": "a.py", "sha256": "aa" * 32},
                          {"path": "b.py", "sha256": "bb" * 32}]}
    manifest["signature"] = release_sign.sign_manifest(manifest, key)
    pub = key.public_key()
    assert release_sign.verify_manifest(manifest, pub) is True
    # 篡改文件哈希
    bad = dict(manifest)
    bad["files"] = [{"path": "a.py", "sha256": "cc" * 32}, manifest["files"][1]]
    assert release_sign.verify_manifest(bad, pub) is False
    # 篡改版本号
    bad2 = dict(manifest)
    bad2["version"] = "0.0.1"
    assert release_sign.verify_manifest(bad2, pub) is False
    # 无签名
    nosig = {"version": "9.9.9", "files": manifest["files"]}
    assert release_sign.verify_manifest(nosig, pub) is False
    # 换一把公钥
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert release_sign.verify_manifest(manifest, other.public_key()) is False


def test_manifest_path_traversal_rejected():
    """更新包路径不得逃出项目目录"""
    from modules.installed.auto_updater import AutoUpdater
    up = AutoUpdater.__new__(AutoUpdater)   # 不跑 __init__，只测纯函数
    up.base = BASE
    assert up._safe_relpath("core/trunk.py") is not None
    assert up._safe_relpath("../../evil.py") is None
    assert up._safe_relpath("..\\..\\evil.py") is None
    assert up._safe_relpath("C:/Windows/evil.py") is None


def test_version_compare():
    """版本比较：只认数字段，'v' 前缀不影响"""
    from modules.installed.auto_updater import AutoUpdater
    vt = AutoUpdater._version_tuple
    assert vt("v25.1.3") > vt("25.1.2")
    assert vt("26.0.0") > vt("v25.9.9")
    assert vt("v25.1.3") == vt("25.1.3")
    assert not (vt("v25.1.3") > vt("25.1.3"))
