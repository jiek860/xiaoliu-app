# -*- coding: utf-8 -*-
"""CLI for local team roles, central config and audit export."""
from __future__ import annotations

import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.team_policy import TeamStore  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--requester", default="local")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("users")
    p_add = sp.add_parser("add-user")
    p_add.add_argument("user_id")
    p_add.add_argument("--name", default="")
    p_add.add_argument("--role", default="viewer")
    p_role = sp.add_parser("set-role")
    p_role.add_argument("user_id")
    p_role.add_argument("role")
    sp.add_parser("config-get")
    p_set = sp.add_parser("config-set")
    p_set.add_argument("json_text")
    p_audit = sp.add_parser("audit-export")
    p_audit.add_argument("out")
    args = ap.parse_args(argv)
    store = TeamStore(args.base)
    if args.cmd == "add-user":
        out = store.add_user(args.user_id, args.name, args.role, args.requester)
    elif args.cmd == "set-role":
        out = store.set_role(args.user_id, args.role, args.requester)
    elif args.cmd == "config-get":
        out = store.get_central_config(args.requester)
    elif args.cmd == "config-set":
        out = store.set_central_config(json.loads(args.json_text), args.requester)
    elif args.cmd == "audit-export":
        out = store.export_audit(args.out, args.requester)
    else:
        out = store.list_users(args.requester)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
