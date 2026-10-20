# -*- coding: utf-8 -*-
"""SBOM生成 - 软件物料清单"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import json
import hashlib
import subprocess
import sys
import time


def _version(base):
    try:
        sys.path.insert(0, base)
        from core.version import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def _dependencies():
    try:
        out = subprocess.run([sys.executable, "-m", "pip", "freeze"],
                             capture_output=True, text=True, timeout=30)
        return [x.strip() for x in (out.stdout or "").splitlines() if x.strip()]
    except Exception:
        return []


def generate_sbom(base=None):
    """生成SBOM清单"""
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    files = []
    for root, _, filenames in os.walk(base):
        # 跳过不需要的目录
        if any(x in root for x in
               ("__pycache__", ".git", "backups", "updates", "dist", "data", "tools")):
            continue
        for f in filenames:
            if f.endswith((".py", ".txt", ".md", ".pem", ".json")):
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, base)
                try:
                    size = os.path.getsize(fp)
                    sha = hashlib.sha256(open(fp, "rb").read()).hexdigest()
                    files.append({
                        "path": rel.replace(os.sep, "/"),
                        "size": size,
                        "sha256": sha,
                    })
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass

    sbom = {
        "name": "小6智能体",
        "version": _version(base),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_count": len(files),
        "dependencies": _dependencies(),
        "files": files,
    }

    out = os.path.join(base, "sbom.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sbom, f, ensure_ascii=False, indent=2)

    return {"ok": True, "file": out, "files": len(files)}


if __name__ == "__main__":
    r = generate_sbom()
    print("SBOM generated:", r["file"])
    print("files:", r["files"])
