# -*- coding: utf-8 -*-
"""守卫：数据目录只许走 core.data_paths（硬编码 base/data 只减不增）

为什么要有这一条
----------------
2026-11-02 第二轮体检：第一方代码里还有 **196 处** ``os.path.join(..., "data")``
（135 个文件）自己拼数据目录，而 ``core/data_paths.py`` 只有 20 来个文件在用。
后果是这几个真实故障：

* 换 ``X6_DATA_DIR`` 跑批处理/评测时，这些文件仍然写真实 ``data/``；
* 测试重定向 ``data_dir`` 后，它们照样往用户的真数据里写假对话
  （``core/data_paths.py`` 的模块注释里有 2026-11-01 的事故记录）；
* 装到 ``Program Files`` 这类不可写目录时，写失败被 ``except`` 吞掉。

所以这里做**棘轮**：计数只能降不能升。迁移一处就把基线调小一处
（``--update`` 会重写基线），新代码再手拼 ``base/data`` 会被门禁拦下。

用法
----
    py -3 tools/check_data_paths.py            # 校验（门禁用）
    py -3 tools/check_data_paths.py --update   # 迁移后刷新基线
"""
import ast
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(BASE, "tools", "data_paths_baseline.json")

# 第一方代码；tests/tools/scripts 不算（测试自己造目录是正常的）
SCOPE = ("core", "gui", "modules/installed", "modules/support")

# 定义入口本身：它拼 "data" 是天经地义
ALLOW = {"core/data_paths.py"}


def _files():
    for d in SCOPE:
        top = os.path.join(BASE, d.replace("/", os.sep))
        for root, dirs, names in os.walk(top):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for n in sorted(names):
                if n.endswith(".py"):
                    yield os.path.join(root, n)


def _is_data(node):
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.replace("\\", "/").strip("/") == "data")


def scan():
    """返回 [(相对路径, 行号, 原始片段)]"""
    hits = []
    for path in _files():
        rel = os.path.relpath(path, BASE).replace("\\", "/")
        if rel in ALLOW:
            continue
        try:
            src = io.open(path, encoding="utf-8-sig").read()
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError):
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fn != "join":
                continue
            args = node.args
            # 只看 os.path.join(<x>, "data"[, ...]) 这种形态
            if len(args) < 2 or not _is_data(args[1]):
                continue
            ln = node.lineno
            raw = lines[ln - 1].strip() if ln - 1 < len(lines) else ""
            hits.append((rel, ln, raw))
    return hits


def load_baseline():
    try:
        with io.open(BASELINE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _per_dir(hits):
    out = {}
    for rel, _ln, _raw in hits:
        d = rel.split("/")[0]
        out[d] = out.get(d, 0) + 1
    return out


def check():
    """返回错误列表（空 = 通过）"""
    hits = scan()
    files = {h[0] for h in hits}
    base = load_baseline()
    limit = int(base.get("count") or 0)
    limit_files = int(base.get("files") or 0)
    errs = []
    if hits and len(hits) > limit:
        errs.append("硬编码 data 目录回升：现 %d 处 / %d 文件（基线 %d 处 / %d 文件）"
                    % (len(hits), len(files), limit, limit_files))
        worst = {}
        for rel, ln, _raw in hits:
            worst.setdefault(rel, []).append(ln)
        for rel, lns in sorted(worst.items(), key=lambda kv: -len(kv[1]))[:8]:
            errs.append("    %s:%s" % (rel, ",".join(str(x) for x in lns[:8])))
        errs.append("    改用 core.data_paths.data_path(target, *parts)"
                    " / data_dir(target))")
    return errs


def update():
    hits = scan()
    data = {
        "count": len(hits),
        "files": len({h[0] for h in hits}),
        "updated": "2026-11-02",
        "by_dir": _per_dir(hits),
        "why": ("第一方代码里仍手拼 base/data 的数据目录处数；只许降。"
                "改 core/data_paths 里那一处之后跑 --update 调小。"),
    }
    with io.open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("✅ 基线已更新：%d 处 / %d 文件 %s"
          % (data["count"], data["files"], data["by_dir"]))


def main():
    if "--update" in sys.argv:
        update()
        return 0
    hits = scan()
    errs = check()
    print("硬编码 base/data：%d 处 / %d 文件（基线 %s 处）  %s"
          % (len(hits), len({h[0] for h in hits}),
             load_baseline().get("count", "?"),
             "✅" if not errs else "❌"))
    for e in errs:
        print(e)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
