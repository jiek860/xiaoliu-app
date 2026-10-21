# -*- coding: utf-8 -*-
"""签名验证工具（小6插件标准 v2.1 S5 / N14）。

用法：
    py -3 tools/verify_signature.py <plugin>          # 校验单个插件
    py -3 tools/verify_signature.py --all             # 校验全部
    py -3 tools/verify_signature.py --algo             # 打印算法参数
    py -3 tools/verify_signature.py --json

校验内容：
  1. 文件字节 sha256 == manifest.sha256
  2. RSA 验签通过（RSASSA-PKCS1-v1_5 + SHA-256）
  3. 密钥长度 >= 2048 位
  4. 吊销列表（CRL）中不存在该签名
"""
from __future__ import annotations

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.plugin_signer import PluginSigner  # noqa: E402

MANIFEST = os.path.join(BASE, "modules_repo", "manifest.json")
SRC_DIR = os.path.join(BASE, "modules_repo")
CRL_PATH = os.path.join(BASE, "config", "plugin_key_revocation.json")
MIN_KEY_BITS = 2048
ALGO = {"key": "RSA", "min_bits": MIN_KEY_BITS,
        "scheme": "RSASSA-PKCS1-v1_5", "hash": "SHA-256",
        "encoding": "Base64 (no wrap)"}


def _load():
    with open(MANIFEST, encoding="utf-8-sig") as f:
        return json.load(f)


def _crl():
    """读取密钥吊销列表（N14）。缺文件视为空列表。"""
    try:
        data = json.load(open(CRL_PATH, encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"signatures": [], "keys": []}
    if not isinstance(data, dict):
        return {"signatures": [], "keys": []}
    return {"signatures": list(data.get("signatures") or []),
            "keys": list(data.get("keys") or [])}


def key_bits(signer):
    """返回公钥位数；拿不到返回 0。"""
    try:
        pub = signer.load_pubkey()
        if pub is None:
            return 0
        return int(getattr(pub, "key_size", 0) or 0)
    except Exception:
        return 0


def verify_one(meta, signer, crl):
    name = meta.get("name")
    path = os.path.join(SRC_DIR, meta.get("file") or "")
    if not os.path.isfile(path):
        return {"name": name, "ok": False, "errors": ["源码不存在"]}
    raw = open(path, "rb").read()
    digest = signer.calc_hash_bytes(raw)
    errors = []
    if digest != str(meta.get("sha256") or ""):
        errors.append("sha256 不匹配")
    sig = str(meta.get("signature") or "")
    if not sig:
        errors.append("未签名")
    elif sig in crl["signatures"]:
        errors.append("签名已在吊销列表中（N14）")
    else:
        try:
            if not signer.verify_hash(digest, sig):
                errors.append("RSA 验签失败")
        except Exception as e:
            errors.append("验签异常: %s" % str(e)[:80])
    return {"name": name, "ok": not errors, "errors": errors}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    if "--algo" in argv:
        print(json.dumps(ALGO, ensure_ascii=False, indent=2))
        return 0
    names = [a for a in argv if not a.startswith("-")]
    modules = _load()
    if names and "--all" not in argv:
        modules = [m for m in modules if m.get("name") in names]
    signer = PluginSigner(BASE)
    bits = key_bits(signer)
    crl = _crl()
    results = [verify_one(m, signer, crl) for m in modules]
    failed = [r for r in results if not r["ok"]]
    report = {"algo": ALGO, "key_bits": bits,
              "key_bits_ok": bits >= MIN_KEY_BITS if bits else False,
              "crl_signatures": len(crl["signatures"]),
              "checked": len(results), "failed": len(failed),
              "ok": not failed, "results": results}
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("插件签名验证（v2.1 S5）")
        print("=" * 70)
        print("  算法      : %s %d+ 位 / %s / %s"
              % (ALGO["key"], MIN_KEY_BITS, ALGO["scheme"], ALGO["hash"]))
        print("  公钥位数  : %s%s" % (bits or "未知",
                                      "" if report["key_bits_ok"] else "  ⚠ 低于 2048"))
        print("  吊销列表  : %d 条" % report["crl_signatures"])
        print("  校验模块  : %d，失败 %d" % (len(results), len(failed)))
        for r in failed[:10]:
            print("  [E] %s: %s" % (r["name"], "；".join(r["errors"])))
        print()
        print("[OK] 签名与哈希全部有效" if not failed else "[X] 存在签名问题")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
