# -*- coding: utf-8 -*-
"""CLI for the incremental permission-aware RAG knowledge base."""
from __future__ import annotations

import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.rag_pipeline import KnowledgeBase  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--namespace", default="default")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p_ing = sp.add_parser("ingest")
    p_ing.add_argument("path")
    p_ing.add_argument("--roles", default="")
    p_ing.add_argument("--force", action="store_true")
    p_search = sp.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--role", default="viewer")
    p_search.add_argument("--top-k", type=int, default=5)
    sp.add_parser("stats")
    p_del = sp.add_parser("delete")
    p_del.add_argument("source")
    args = ap.parse_args(argv)
    kb = KnowledgeBase(args.base, args.namespace)
    if args.cmd == "ingest":
        roles = [x.strip() for x in str(args.roles or "").split(",") if x.strip()]
        if os.path.isdir(args.path):
            out = kb.ingest_directory(args.path, acl_roles=roles, force=args.force)
        else:
            out = kb.ingest_file(args.path, acl_roles=roles, force=args.force)
    elif args.cmd == "search":
        out = kb.search(args.query, top_k=args.top_k, role=args.role)
    elif args.cmd == "delete":
        out = {"ok": kb.delete_source(args.source)}
    else:
        out = kb.stats()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not isinstance(out, dict) or out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
