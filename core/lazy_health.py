# -*- coding: utf-8 -*-
"""懒加载模块健康检查：编译 + 导入探测，避免错误延迟到用户点击才暴露。"""
from __future__ import annotations

import importlib.util
import json
import os
import py_compile
import subprocess
import sys
import time


def _lazy_map(base):
    from core.lazy_config import LAZY_MAP
    return LAZY_MAP


def _module_path(base, mod_file):
    installed = os.path.join(base, "modules", "installed", str(mod_file) + ".py")
    if os.path.isfile(installed):
        return installed
    corep = os.path.join(base, "core", str(mod_file) + ".py")
    if os.path.isfile(corep):
        return corep
    return ""


def compile_lazy_sources(base):
    """只做语法编译，不执行模块，适合启动后台快速自检。"""
    errors = []
    for key, (mod_file, _cls_name, _cn) in _lazy_map(base).items():
        p = _module_path(base, mod_file)
        if not p:
            errors.append({"module": key, "error": "文件不存在"})
            continue
        try:
            py_compile.compile(p, doraise=True)
        except Exception as e:
            errors.append({"module": key, "file": p, "error": str(e)[:300]})
    return {"ok": not errors, "checked": len(_lazy_map(base)),
            "errors": errors}


def probe_lazy_imports(base, only=None):
    """逐模块导入并检查声明类是否存在。

    注意：只 import，不实例化，避免启动网络/窗口/后台线程。
    """
    results = []
    for key, (mod_file, cls_name, _cn) in _lazy_map(base).items():
        if only and key not in only:
            continue
        p = _module_path(base, mod_file)
        if not p:
            results.append({"module": key, "ok": False,
                            "error": "文件不存在"})
            continue
        t0 = time.time()
        try:
            spec = importlib.util.spec_from_file_location(
                "x6_lazy_probe_%s_%s" % (key, time.time_ns()), p)
            if spec is None or spec.loader is None:
                raise RuntimeError("无法加载模块 spec")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            found = hasattr(mod, cls_name)
            results.append({"module": key, "ok": found,
                            "file": p, "class": cls_name,
                            "elapsed": round(time.time() - t0, 3),
                            "error": "" if found else "缺少类 %s" % cls_name})
        except Exception as e:
            results.append({"module": key, "ok": False, "file": p,
                            "elapsed": round(time.time() - t0, 3),
                            "error": str(e)[:400]})
    return {"ok": all(x.get("ok") for x in results),
            "checked": len(results), "results": results}


def isolated_check(base, timeout=180):
    """在子进程里全量探测，避免某个模块崩溃影响主进程。"""
    script = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from core.lazy_health import probe_lazy_imports
print(json.dumps(probe_lazy_imports(sys.argv[1]), ensure_ascii=False))
'''
    try:
        r = subprocess.run(
            [sys.executable, "-c", script, str(base)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=int(timeout), cwd=str(base))
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or "")[-1000:]}
        return json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


def format_report(report):
    lines = []
    for r in report.get("results") or []:
        if not r.get("ok"):
            lines.append(" %s: %s" % (r.get("module"), r.get("error")))
    return "\n".join(lines) or "全部通过"
