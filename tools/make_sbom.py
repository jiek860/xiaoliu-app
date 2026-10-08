# -*- coding: utf-8 -*-
"""SBOM生成 - 软件物料清单"""
import os
import json
import hashlib
import time


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
                except Exception:
                    pass

    sbom = {
        "name": "小6智能体",
        "version": "v24.1.0",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_count": len(files),
        "files": files,
    }

    out = os.path.join(base, "sbom.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sbom, f, ensure_ascii=False, indent=2)

    return {"ok": True, "file": out, "files": len(files)}


if __name__ == "__main__":
    r = generate_sbom()
    print("✅ SBOM已生成:", r["file"])
    print("文件数:", r["files"])
