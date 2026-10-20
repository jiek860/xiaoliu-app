# -*- coding: utf-8 -*-
"""文件修改 diff 预览。"""
import difflib
import os


def unified_diff(path, old, new, context=3):
    try:
        old_lines = str(old).splitlines(keepends=True)
        new_lines = str(new).splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=str(path) + " (old)",
            tofile=str(path) + " (new)",
            n=context))
        text = "".join(diff)
        return {
            "path": os.path.abspath(str(path)),
            "diff": text[:12000],
            "added": sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++")),
            "removed": sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---")),
            "truncated": len(text) > 12000,
        }
    except Exception as e:
        return {"path": str(path), "diff": "", "error": str(e)[:120],
                "added": 0, "removed": 0, "truncated": False}


def preview_edit(path, old, new):
    try:
        if os.path.isfile(path):
            content = open(path, encoding="utf-8", errors="replace").read()
        else:
            content = ""
        updated = content.replace(str(old), str(new), 1)
        r = unified_diff(path, content, updated)
        r["exists"] = os.path.isfile(path)
        return r
    except Exception as e:
        return {"path": str(path), "diff": "", "error": str(e)[:120],
                "added": 0, "removed": 0, "truncated": False}
