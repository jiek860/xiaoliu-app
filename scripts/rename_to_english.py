# -*- coding: utf-8 -*-
"""批量重命名中文模块为英文名 + 全局搜索替换 import 引用。"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import argparse
import json
import re
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INSTALLED = BASE / "modules" / "installed"
MAP_FILE = INSTALLED / "rename_map.json"
BACKUP_DIR = BASE / "backups" / "rename_chinese"


def load_map() -> dict:
    with open(MAP_FILE, encoding="utf-8") as f:
        return json.load(f)


def backup_all(mapping: dict, dry: bool):
    if dry:
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for cn, en in mapping.items():
        src = INSTALLED / cn
        if src.exists():
            shutil.copy2(src, BACKUP_DIR / cn)


def rename_files(mapping: dict, dry: bool):
    done, skipped = [], []
    for cn, en in mapping.items():
        src = INSTALLED / cn
        dst = INSTALLED / en
        if not src.exists():
            skipped.append(cn)
            continue
        if dst.exists():
            print(f"  [WARN] 目标已存在，跳过：{en}")
            skipped.append(cn)
            continue
        print(f"  {'[DRY]' if dry else '[REN]'} {cn}  ->  {en}")
        if not dry:
            src.rename(dst)
        done.append((cn, en))
    return done, skipped


def replace_references(mapping: dict, dry: bool):
    name_map = {cn[:-3]: en[:-3] for cn, en in mapping.items()}
    file_map = {cn: en for cn, en in mapping.items()}
    changed_files = []
    for py in BASE.rglob("*.py"):
        if "backups" in str(py) or "__pycache__" in str(py):
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except Exception as e:
            _x6_swallowed(__name__, e)
            continue
        new = src
        for cn_name, en_name in name_map.items():
            for q in ('"', "'"):
                new = re.sub(
                    r'(?P<pre>[:=,\[\(\s])' + q + re.escape(cn_name) + q,
                    lambda m: f"{m.group('pre')}{q}{en_name}{q}",
                    new,
                )
        for cn_file, en_file in file_map.items():
            for q in ('"', "'"):
                new = new.replace(f"{q}{cn_file}{q}", f"{q}{en_file}{q}")
        if new != src:
            changed_files.append(py)
            print(f"  {'[DRY]' if dry else '[MOD]'} {py.relative_to(BASE)}")
            if not dry:
                py.write_text(new, encoding="utf-8")
    return changed_files


def check_leftover():
    leftovers = []
    for py in BASE.rglob("*.py"):
        if "backups" in str(py) or "__pycache__" in str(py):
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except Exception as e:
            _x6_swallowed(__name__, e)
            continue
        for m in re.finditer(r'["\']([^"\']*[\u4e00-\u9fff][^"\']*\.py)["\']', src):
            leftovers.append((py.relative_to(BASE), m.group(1)))
    return leftovers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true", help="实际执行")
    args = ap.parse_args()
    dry = not args.apply

    mapping = load_map()
    print(f"=== {'DRY-RUN' if dry else 'APPLY'} 模式 ===")
    print(f"映射条目：{len(mapping)}")

    print("\n[1] 备份原文件")
    backup_all(mapping, dry)

    print("\n[2] 重命名文件")
    done, skipped = rename_files(mapping, dry)

    print("\n[3] 替换代码中的引用")
    changed = replace_references(mapping, dry)
    print(f"  修改 {len(changed)} 个文件")

    print("\n[4] 残留检查")
    leftovers = check_leftover()
    if leftovers:
        print(f"  [WARN] 发现 {len(leftovers)} 处中文 .py 引用，需人工处理：")
        for f, s in leftovers[:30]:
            print(f"      {f}  <-  {s}")
    else:
        print("  OK 无残留")

    print(f"\n完成：重命名 {len(done)}，跳过 {len(skipped)}")


if __name__ == "__main__":
    main()
