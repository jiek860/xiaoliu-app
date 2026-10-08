# -*- coding: utf-8 -*-
"""给 modules_repo/manifest.json 里的每个模块补 sha256 与 RSA 签名

用法:
    python tools/sign_modules.py                # 签名（并把缺文件的条目标出来）
    python tools/sign_modules.py --prune        # 顺便删掉指向不存在文件的条目

做的事：
    1. 读 modules_repo/manifest.json
    2. 对每条登记的 file 计算 sha256
    3. 用密钥库私钥给 sha256 签名，写入该条的 sha256 / signature 字段
    4. 用 core/公钥.pem 自校验一遍，全部通过才写盘

用户端 plugin_market 下载/安装模块时会用同一把公钥验签，验不过不落盘。
私钥来源同 sign_release.py：环境变量 X6_SIGN_KEY，或密钥库 E:\\xiao6-keys。

关于"僵尸条目"
--------------
清单里可能残留指向已不存在文件的条目（模块被删了、条目忘了删）。
它们会让插件市场的在线列表显示一些点了会 404 的模块，所以本脚本一定会把它们
列出来。默认**只报告不删除**（删掉会丢描述/分组等元信息，属于产品决定），
要清理就加 --prune。
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.plugin_signer import PluginSigner
from core.release_sign import load_signing_privatekey


def main():
    ap = argparse.ArgumentParser(description="给模块仓库清单签名")
    ap.add_argument("--prune", action="store_true",
                    help="删掉指向不存在文件的条目（默认只报告）")
    args = ap.parse_args()

    repo = os.path.join(BASE, "modules_repo")
    mpath = os.path.join(repo, "manifest.json")
    if not os.path.exists(mpath):
        print("[X] 找不到 %s" % mpath)
        return 1

    manifest = json.load(open(mpath, encoding="utf-8-sig"))
    if not isinstance(manifest, list):
        print("[X] manifest.json 结构不是列表")
        return 1

    try:
        priv = load_signing_privatekey()
    except Exception as e:
        print("[X] %s" % e)
        return 1

    ps = PluginSigner()
    signed, stale, failed = 0, [], []

    for m in manifest:
        fname = m.get("file", "")
        fp = os.path.join(repo, fname)
        if not fname or not os.path.exists(fp):
            stale.append((m.get("name", "?"), fname or "(未填 file)"))
            m["sha256"] = ""
            m["signature"] = ""
            continue
        h = ps.calc_hash(fp)
        m["sha256"] = h
        m["signature"] = ps.sign_hash(h, priv)
        # 立刻自校验，防止签名端与用户端算法不一致
        if not ps.verify_hash(h, m["signature"]):
            failed.append(fname)
        else:
            signed += 1

    if failed:
        print("[X] 自校验失败，未写盘: %s" % failed)
        return 1

    if stale:
        print("[!] 有 %d 条指向不存在的文件：" % len(stale))
        for n, f in stale:
            print("      %-22s -> %s" % (n, f))
        if args.prune:
            names = {n for n, _ in stale}
            manifest = [m for m in manifest if m.get("name") not in names]
            print("    已按 --prune 删除这些条目")
        else:
            print("    它们会出现在插件市场的在线列表里，点了会下载失败。")
            print("    要清理请重新运行：python tools\\sign_modules.py --prune")
        print()

    json.dump(manifest, open(mpath, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("[OK] 已签名并写回: %s" % mpath)
    print("     清单共 %d 条，已签名 %d 条" % (len(manifest), signed))
    print("     现在可以上传 modules_repo 到仓库；用户端会验签后才安装。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
