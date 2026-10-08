# -*- coding: utf-8 -*-
"""发版签名脚本 - 用【密钥库】里的私钥给 manifest.json 签名

用法:
    python sign_release.py                  # 签名并用公钥自校验
    python sign_release.py --verify         # 只校验已有签名，不重新签

私钥来源（按顺序查找，绝不放项目目录）:
    1. 环境变量 X6_SIGN_KEY 指向的 pem 文件
    2. %USERPROFILE%\\.xiao6-keys\\RSA私钥-更新签名.pem
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.release_sign import (load_signing_privatekey, load_release_pubkey,
                               sign_manifest, verify_manifest)

base = os.path.dirname(os.path.abspath(__file__))
manifest_path = os.path.join(base, "manifest.json")

if not os.path.exists(manifest_path):
    print("[X] 找不到 manifest.json，先跑 build_release.py")
    sys.exit(1)

with open(manifest_path, "r", encoding="utf-8-sig") as f:
    manifest = json.load(f)

pub = load_release_pubkey(base)
if pub is None:
    print("[X] 找不到验签公钥 core/公钥.pem")
    sys.exit(1)

if "--verify" in sys.argv:
    ok = verify_manifest(manifest, pub)
    print("[OK] 签名校验通过" if ok else "[X] 签名校验失败")
    sys.exit(0 if ok else 1)

try:
    private_key = load_signing_privatekey()
except Exception as e:
    print("[X] %s" % e)
    sys.exit(1)

manifest["signature"] = sign_manifest(manifest, private_key)

# 自校验：签完立刻用公钥验一遍，防止签名端与用户端算法不一致
ok = verify_manifest(manifest, pub)
if not ok:
    print("[X] 自校验失败，manifest 未写入")
    sys.exit(1)

with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print("[OK] 签名完成并自校验通过")
print("     版本: %s" % manifest.get("version"))
print("     文件数: %d" % len(manifest.get("files", [])))
print("     签名值: %s..." % manifest["signature"][:32])
print()
print("下一步: 把签名后的 manifest.json + 所有文件上传到 Gitee 仓库")
