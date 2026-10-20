# -*- coding: utf-8 -*-
"""手动执行数据版本迁移。"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.data_migrations import migrate_all  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="迁移小6数据文件到当前 schema")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = migrate_all(a.base, dry_run=a.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else str(r))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
