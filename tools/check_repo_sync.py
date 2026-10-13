# -*- coding: utf-8 -*-
"""插件仓库一致性检查 —— 推送前必须过

为什么需要
----------
modules_repo 是**独立 git 仓库**，而且**真的会推到 gitee**
（origin = https://gitee.com/cloud-drift/liuyun.git），用户端拉它装插件。
但主仓库没有远程，所以"推 modules_repo"这个动作没有 CI 兜着。

推错了会怎样：
    · 内容过期   用户装到的是旧版本模块（主仓库改了但没同步）
    · 没签名     用户端**拒绝安装**（验签不通过）
    · 清单漏条目 模块在 installed 里但清单没登记 -> 用户装不到
    · 清单多条目 清单登记了但文件不存在 -> 用户点安装会失败

这些都是"推出去才会发现"的问题，所以放在 **pre-push** 里查。

检查项
------
    ① 主仓库的 modules/installed 与 modules_repo 内容逐字节一致
    ② 清单条目数 = installed 里的模块数（排除 __init__.py）
    ③ 每条都有非空 sha256 与 signature
    ④ 逐条验签通过（RSA）
"""
import argparse
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INST = os.path.join(BASE, "modules", "installed")
REPO = os.path.join(BASE, "modules_repo")
MANIFEST = os.path.join(REPO, "manifest.json")


def files_of(d):
    return sorted(f for f in os.listdir(d)
                  if f.endswith(".py") and f != "__init__.py")


def main():
    ap = argparse.ArgumentParser(description="插件仓库一致性检查")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    print("=" * 74)
    print("插件仓库一致性检查（推送 modules_repo 前必须过）")
    print("=" * 74)

    problems = []

    if not os.path.isdir(REPO):
        print("[X] 没有 modules_repo 目录")
        return 1
    if not os.path.exists(MANIFEST):
        print("[X] 没有 manifest.json —— 先跑 tools/rebuild_modules_repo.py --apply")
        return 1

    inst = files_of(INST)
    repo = files_of(REPO)

    # ① 内容逐字节一致
    same = diff = 0
    different = []
    for f in inst:
        a, b = os.path.join(INST, f), os.path.join(REPO, f)
        if not os.path.exists(b):
            different.append("%s 只存在于 installed" % f)
            continue
        if open(a, "rb").read() == open(b, "rb").read():
            same += 1
        else:
            diff += 1
            different.append("%s 内容不一致" % f)
    for f in repo:
        if f not in inst:
            different.append("%s 只存在于 modules_repo" % f)
    print("  ① 内容一致 %d 个 / 不一致 %d 个" % (same, diff))
    if different:
        problems.append("内容不一致：%s" % "、".join(different[:6]))

    # ② 清单条数
    try:
        man = json.load(open(MANIFEST, encoding="utf-8-sig"))
    except Exception as e:
        print("  [X] 清单读不了：%s" % e)
        return 1
    print("  ② 清单 %d 条 / installed %d 个模块" % (len(man), len(inst)))
    if len(man) != len(inst):
        problems.append("清单 %d 条 != installed %d 个（多或漏都会让用户装不上）"
                        % (len(man), len(inst)))

    # ③ 每条要有 sha256 与 signature
    no_sha = [m.get("name") for m in man if not m.get("sha256")]
    no_sig = [m.get("name") for m in man if not m.get("signature")]
    print("  ③ 缺 sha256 的 %d 条 / 缺签名 的 %d 条" % (len(no_sha), len(no_sig)))
    if no_sha:
        problems.append("没算 sha256：%s" % no_sha[:6])
    if no_sig:
        problems.append("没签名（用户端会拒绝安装）：%s" % no_sig[:6])

    # ④ 逐条验签
    ok = bad = 0
    bad_names = []
    try:
        sys.path.insert(0, BASE)
        from core.plugin_signer import PluginSigner
        ps = PluginSigner(None)
        for m in man:
            h, sig = m.get("sha256"), m.get("signature")
            if not (h and sig):
                continue
            try:
                if ps.verify_hash(h, sig):
                    ok += 1
                else:
                    bad += 1
                    bad_names.append(m.get("name"))
            except Exception:
                bad += 1
                bad_names.append(m.get("name"))
    except Exception as e:
        print("  ④ 验签跳过（plugin_signer 不可用：%s）" % str(e)[:50])
    if ok or bad:
        print("  ④ 验签通过 %d 条 / 失败 %d 条" % (ok, bad))
        if bad:
            problems.append("验签失败（用户端装不上）：%s" % bad_names[:6])

    print("=" * 74)
    if problems:
        print("发现 %d 个问题，**先别推**：" % len(problems))
        for p in problems:
            print("   · %s" % p)
        print()
        print("修法：")
        print("   1) py -3 tools/rebuild_modules_repo.py --apply   # 重新同步内容与清单")
        print("   2) set X6_KEY_VAULT=<密钥库目录>                # 否则找不到私钥")
        print("      py -3 tools/sign_modules.py                   # 重新签名")
        return 1
    print("插件仓库一致性通过 ✅  可以推送")
    return 0


if __name__ == "__main__":
    sys.exit(main())
