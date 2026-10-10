# -*- coding: utf-8 -*-
r"""重建 modules_repo：只保留"能在插件市场真正下载安装"的模块

背景
----
插件市场实测 100% 装不上：lazy_config 里写着"v3.0 全部使用英文模块名"，
install() 按 LAZY_MAP 去找 modules_repo/agent_coder.py，而仓库里还叫 编程助手.py。
这个重构做了一半。同时清单里有 15 条指向不存在文件的僵尸条目。

做法
----
1. 以 LAZY_MAP 指向 modules/installed/ 的条目为准（52 项，去掉 stt/voice 同文件重名 → 51 个）
2. 用当前 modules/installed/<英文名>.py 作为仓库内容（不再保留仓库里那份旧副本）
3. 仓库文件名 = LAZY_MAP 的文件名（英文），中文名只留在清单的 title 字段
4. 元信息尽量保留：installed_meta.json（按英文名）→ 旧清单（按中文 title）→ 模块 docstring
5. 删掉所有旧的中文名文件与幽灵条目
6. 签名由 tools/sign_modules.py 负责

默认只做"预演"（--dry-run），加 --apply 才真改文件。
"""
import argparse
import ast
import json
import os
import re
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INST = os.path.join(BASE, "modules", "installed")
REPO = os.path.join(BASE, "modules_repo")

sys.path.insert(0, BASE)
from core.lazy_config import LAZY_MAP  # noqa: E402


def doc_of(path):
    """取模块首行 docstring 作为描述"""
    try:
        t = open(path, encoding="utf-8", errors="ignore").read(4000)
        m = re.search(r'"""(.*?)"""', t, re.S)
        if m:
            lines = [x.strip() for x in m.group(1).splitlines() if x.strip()]
            if lines:
                return lines[0][:60]
    except Exception:
        pass
    return ""


# 旧元信息里没有分组的模块，按名字关键词归类，免得插件市场里一半都堆在"其他"
GROUP_HINTS = [
    ("联网检索", ("搜索", "search", "知识", "qa", "ocr", "多模态", "mcp", "浏览", "browse",
                  "翻译", "translate", "天气", "weather")),
    ("学习记忆", ("学习", "记忆", "遗忘", "技能", "笔记", "notes", "待办", "todo", "日历", "calendar")),
    ("工程系统", ("更新", "updater", "热重载", "reload", "代码", "code", "文件", "file",
                  "上传", "upload", "错误", "error", "工具", "tool", "路由", "router",
                  "任务", "task", "调度", "schedul", "缓存", "cache")),
    ("智能体", ("群聊", "group", "智能体", "agent", "循环", "loop", "闭环", "升级", "upgrade")),
    ("认知心理", ("人格", "personality", "共情", "empathy", "反思", "reflect",
                  "推理", "reason")),
    ("系统服务", ("电脑", "computer", "手机", "mobile", "远程", "语音", "voice",
                  "tts", "实时", "realtime")),
]


def guess_group(title, fname):
    hay = (title or "") + " " + (fname or "")
    low = hay.lower()
    for group, keys in GROUP_HINTS:
        for k in keys:
            if k.lower() in low:
                return group
    return "其他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正修改文件（默认只预演）")
    args = ap.parse_args()

    # ---------- 1. 发布集 ----------
    publish, seen_files = [], {}
    for name, val in LAZY_MAP.items():
        fname, cls, cn = val[0], val[1], val[2]
        src = os.path.join(INST, fname + ".py")
        if not os.path.exists(src):
            continue                      # 指向 core 的，不进市场
        if fname in seen_files:
            # stt / voice 指向同一个文件，只保留一个条目
            print("  [跳过] %-22s 与 %s 指向同一文件 %s.py"
                  % (name, seen_files[fname], fname))
            continue
        seen_files[fname] = name
        # 类名必须真的在文件里
        try:
            names = {n.name for n in ast.walk(ast.parse(open(src, "rb").read()))
                     if isinstance(n, ast.ClassDef)}
        except Exception as e:
            print("  [X] %s 语法错误: %s" % (fname, str(e)[:50]))
            continue
        if cls not in names:
            print("  [X] %s.py 里没有类 %s" % (fname, cls))
            continue
        publish.append({"name": name, "file": fname + ".py", "cls": cls,
                        "title": cn, "src": src})

    # ---------- 2. 元信息 ----------
    # 来源优先级：
    #   1. modules_repo/manifest.json 里同 name 的旧条目
    #      —— 现在它才是权威（随程序发布，界面按钮也从它读），重建时要保留
    #   2. modules/installed_meta.json（可能已被移到 core/_deprecated/，两个位置都找）
    #   3. 模块文件自己的 docstring
    old_manifest = []
    opath = os.path.join(REPO, "manifest.json")
    if os.path.exists(opath):
        try:
            old_manifest = json.load(open(opath, encoding="utf-8-sig"))
        except Exception:
            pass
    old_by_name, old_by_title = {}, {}
    for m in old_manifest:
        if m.get("name"):
            old_by_name.setdefault(m["name"], m)
        if m.get("title"):
            old_by_title.setdefault(m["title"], m)

    meta_by_name = {}
    for cand in (os.path.join(BASE, "modules", "installed_meta.json"),
                 os.path.join(BASE, "core", "_deprecated", "installed_meta.json")):
        if os.path.exists(cand):
            try:
                meta_by_name = json.load(open(cand, encoding="utf-8-sig"))
                break
            except Exception:
                pass

    manifest = []
    src_meta, src_old, src_doc = 0, 0, 0
    for item in sorted(publish, key=lambda x: x["name"]):
        entry = {"name": item["name"], "title": item["title"],
                 "file": item["file"], "cls": item["cls"]}
        om = old_by_name.get(item["name"]) or old_by_title.get(item["title"])
        mm = meta_by_name.get(item["name"])
        base = om or mm
        if mm:
            src_meta += 1
        elif om:
            src_old += 1
        else:
            src_doc += 1
        entry["desc"] = (base or {}).get("desc") or doc_of(item["src"])
        entry["group"] = (base or {}).get("group") or guess_group(item["title"], item["file"])
        if entry["group"] == "其他":
            entry["group"] = guess_group(item["title"], item["file"])
        entry["version"] = (base or {}).get("version") or "1.0"
        entry["button"] = (base or {}).get("button")
        entry["needs_model"] = bool((base or {}).get("needs_model"))
        entry["depends"] = (base or {}).get("depends") or []
        entry["size"] = os.path.getsize(item["src"])
        entry["sha256"] = ""
        entry["signature"] = ""
        manifest.append(entry)

    # ---------- 3. 报告 ----------
    print("=" * 66)
    print("发布集：%d 个模块（元信息来自 meta %d / 旧清单 %d / docstring %d）"
          % (len(manifest), src_meta, src_old, src_doc))
    print("=" * 66)
    groups = {}
    for m in manifest:
        groups.setdefault(m["group"], []).append(m["title"])
    for g in sorted(groups):
        print("  [%s] %s" % (g, "、".join(groups[g])))

    will_delete = sorted(f for f in os.listdir(REPO)
                         if f.endswith(".py") and f not in {m["file"] for m in manifest})
    print()
    print("将删除的旧文件（%d 个）：" % len(will_delete))
    for f in will_delete:
        print("   ", f)

    will_add = [m["file"] for m in manifest
                if not os.path.exists(os.path.join(REPO, m["file"]))
                or open(os.path.join(REPO, m["file"]), "rb").read()
                != open(os.path.join(INST, m["file"]), "rb").read()]
    print()
    print("将写入/更新的文件（%d 个）：" % len(will_add))
    for f in will_add:
        print("   ", f)

    if not args.apply:
        print()
        print("（预演结束，未改动任何文件。加 --apply 真正执行）")
        return 0

    # ---------- 4. 执行 ----------
    print()
    print("正在执行 ...")
    for m in manifest:
        shutil.copy2(os.path.join(INST, m["file"]), os.path.join(REPO, m["file"]))
    for f in will_delete:
        os.remove(os.path.join(REPO, f))
    json.dump(manifest, open(opath, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("  已写入 %d 个模块文件，删除 %d 个旧文件，重建 manifest.json"
          % (len(manifest), len(will_delete)))
    print("  下一步：python tools\\sign_modules.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
