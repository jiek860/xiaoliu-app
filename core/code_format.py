# -*- coding: utf-8 -*-
"""保存即格式化（black/ruff/prettier）+ 只格式化改动区 + 与补丁的先后顺序。

为什么单独一个模块
------------------
`core/code_command_runner.py` 管的是"跑命令"（测试 / lint / 沙箱执行），
而格式化是"对文件内容的确定性变换"：要能单测、要能撤销、要能被
**保存钩子**和**补丁应用**两条链路复用。所以独立出来，runner 里只留
两个转发方法，对外入口不变。

三种使用方式
------------
  ① 保存时  format_file()       —— 编辑器保存钩子，先快照再写回（Ctrl+Z 也能退）
  ② 选区时  format_text(line_range=...)  —— 只格式化选中的行（深度⑥）
  ③ 打补丁  format_patch_files() —— 先把目标文件格式化，再确认 hunk 还能定位（深度⑤）

⚠️ 没装任何格式化工具时全部"安静地不可用"：返回 ok=False + 原因，
   调用方照常保存原文本，不报错不弹窗。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

# 每个格式化工具：扩展名 / 可执行名 / 模块兜底 / stdin 参数 / 选区参数
# 选区参数为空 = 该工具不支持只格式化某几行（调用方退回全文格式化）
_FORMATTERS = (
    {"name": "black", "ext": (".py", ".pyw", ".pyi"), "exe": ("black",),
     "module": "black",
     "stdin": ("--quiet", "--stdin-filename", "{path}", "-"),
     "range": ("--line-ranges", "{start}-{end}")},
    {"name": "ruff", "ext": (".py", ".pyw", ".pyi"), "exe": ("ruff",),
     "module": "ruff",
     "stdin": ("format", "--stdin-filename", "{path}", "-"),
     "range": ()},
    {"name": "prettier", "ext": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                                 ".json", ".md", ".css", ".html", ".vue"),
     "exe": ("prettier",), "module": "",
     "stdin": ("--stdin-filepath", "{path}"),
     "range": ("--range-start", "{offset_start}",
               "--range-end", "{offset_end}")},
    {"name": "clang-format", "ext": (".c", ".h", ".cc", ".cpp", ".cxx",
                                     ".hpp", ".hxx"),
     "exe": ("clang-format",), "module": "",
     "stdin": ("--assume-filename={path}",),
     "range": ("--lines={start}:{end}",)},
    {"name": "gofmt", "ext": (".go",), "exe": ("gofmt",), "module": "",
     "stdin": (), "range": ()},
)

FORMATTER_NAMES = tuple(f["name"] for f in _FORMATTERS)
_SNAPSHOT_DIR = os.path.join("backups", "format")


def _module_installed(name):
    try:
        import importlib.util
        return importlib.util.find_spec(str(name)) is not None
    except Exception as e:  # 静默是故意的 - 探测失败按未安装处理
        _x6_swallowed(__name__, e, "probe formatter module")
        return False


def _exe(fmt):
    """格式化命令前缀：[可执行文件] 或 [python, -m, 模块]；都没有返回 None。"""
    for name in fmt.get("exe") or ():
        found = shutil.which(str(name))
        if found:
            return [found]
    module = fmt.get("module") or ""
    if module and _module_installed(module):
        return [sys.executable, "-m", module]
    return None


def available_formatters(path=""):
    """这个文件能用哪些格式化工具（按候选顺序）。"""
    ext = os.path.splitext(str(path or "").lower())[1]
    out = []
    for fmt in _FORMATTERS:
        if path and ext and ext not in fmt["ext"]:
            continue
        if _exe(fmt):
            out.append(fmt["name"])
    return out


def formatter_for(path, preferred="auto"):
    """挑一个格式化工具；preferred 指定时优先用它，不可用则退回候选顺序。"""
    ext = os.path.splitext(str(path or "").lower())[1]
    cands = [f for f in _FORMATTERS if not ext or ext in f["ext"]]
    if preferred and preferred not in ("auto", ""):
        for fmt in cands:
            if fmt["name"] == preferred and _exe(fmt):
                return fmt
    for fmt in cands:
        if _exe(fmt):
            return fmt
    return None


def _offset_of_line(text, line):
    lines = (text or "").split("\n")
    n = len(lines)
    line = max(1, min(int(line or 1), n))
    return sum(len(x) + 1 for x in lines[:line - 1])


def _range_args(fmt, text, line_range):
    """选区参数；不支持时返回 None（调用方决定退回全文还是放弃）。"""
    if not line_range:
        return []
    try:
        lo, hi = int(line_range[0]), int(line_range[1])
    except (TypeError, ValueError, IndexError):
        return []
    lo, hi = min(lo, hi), max(lo, hi)
    if not fmt.get("range"):
        return None
    values = {"start": max(1, lo), "end": max(1, hi),
              "offset_start": _offset_of_line(text, lo),
              "offset_end": max(0, _offset_of_line(text, hi + 1) - 1)}
    out = []
    for tmpl in fmt["range"]:
        try:
            out.append(str(tmpl).format(**values))
        except (KeyError, IndexError):
            return None
    return out


def _parses(text, path):
    if not str(path or "").lower().endswith((".py", ".pyw", ".pyi")):
        return True
    try:
        ast.parse(text or "")
        return True
    except SyntaxError:
        return False


def _safe_output(old_text, new_text, path):
    """格式化结果护栏：原来能解析、格式化后解析不了 → 拒绝采用。"""
    if not new_text.strip():
        return False
    if _parses(old_text, path) and not _parses(new_text, path):
        return False
    return True


def format_text(text, path, root="", line_range=None, preferred="auto",
                timeout=30):
    """格式化一段文本（不落盘）。返回 {ok, text, changed, formatter, reason}。"""
    raw = text or ""
    fmt = formatter_for(path, preferred)
    if fmt is None:
        return {"ok": False, "text": raw, "changed": False, "formatter": "",
                "reason": "未安装格式化工具（black / ruff / prettier）"}
    exe = _exe(fmt)
    if not exe:
        return {"ok": False, "text": raw, "changed": False, "formatter": "",
                "reason": "格式化工具不可用：%s" % fmt["name"]}
    extra = _range_args(fmt, raw, line_range)
    if extra is None:
        return {"ok": False, "text": raw, "changed": False,
                "formatter": fmt["name"],
                "reason": "%s 不支持只格式化选中行" % fmt["name"]}
    abspath = os.path.abspath(str(path or "")) if path else "stdin.py"
    try:
        args = [str(a).format(path=abspath) for a in fmt["stdin"]] + extra
    except (KeyError, IndexError):  # 模板写错时不炸，按不可用处理
        return {"ok": False, "text": raw, "changed": False,
                "formatter": fmt["name"], "reason": "格式化参数模板错误"}
    argv = exe + args
    try:
        r = subprocess.run(
            argv, input=raw, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            cwd=root or None, shell=False)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"ok": False, "text": raw, "changed": False,
                "formatter": fmt["name"],
                "reason": "格式化失败：%s" % str(e)[:200]}
    out = r.stdout or ""
    if r.returncode != 0 or not out.strip():
        why = (r.stderr or "").strip()[:300]
        return {"ok": False, "text": raw, "changed": False,
                "formatter": fmt["name"],
                "reason": why or "格式化返回空结果"}
    if not _safe_output(raw, out, path):
        return {"ok": False, "text": raw, "changed": False,
                "formatter": fmt["name"],
                "reason": "格式化结果没通过语法校验，已放弃"}
    return {"ok": True, "text": out, "changed": out != raw,
            "formatter": fmt["name"], "reason": ""}


def _safe_name(rel):
    text = str(rel or "").replace("\\", "/").strip("/") or "untitled"
    for ch in '<>:"|?*':
        text = text.replace(ch, "_")
    return text.replace("/", "__")[:120]


def snapshot_file(root, path, text=None):
    """落盘前留一份备份（格式化 / 重命名都能用它回退）。返回快照路径。"""
    base = os.path.abspath(str(root or os.getcwd()))
    if text is None:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return ""
    rel = os.path.relpath(os.path.abspath(str(path)), base) \
        if os.path.isabs(str(path)) else str(path)
    folder = os.path.join(base, _SNAPSHOT_DIR)
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = os.path.join(folder, "%s.%s.bak" % (_safe_name(rel), stamp))
        n = 1
        while os.path.exists(target):
            target = os.path.join(
                folder, "%s.%s_%d.bak" % (_safe_name(rel), stamp, n))
            n += 1
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
        return target
    except OSError as e:
        _x6_swallowed(__name__, e, "write format snapshot")
        return ""


def restore_snapshot(snapshot, path):
    """把快照写回文件（手动后悔药；编辑器里 Ctrl+Z 是另一条路）。"""
    if not snapshot or not os.path.isfile(snapshot):
        return {"ok": False, "reason": "快照不存在"}
    try:
        with open(snapshot, encoding="utf-8") as f:
            text = f.read()
        tmp = str(path) + ".rst_tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return {"ok": True, "reason": ""}
    except OSError as e:
        return {"ok": False, "reason": "%s: %s" % (type(e).__name__,
                                                  str(e)[:120])}


def _abs(root, rel):
    raw = str(rel or "")
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return os.path.normpath(os.path.join(os.path.abspath(str(root or ".")),
                                         raw))


def format_file(root, rel, preferred="auto", line_range=None, timeout=30):
    """格式化磁盘上的一个文件：先快照、再原子写回。返回结果 dict。"""
    path = _abs(root, rel)
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read()
    except OSError as e:
        return {"ok": False, "rel": str(rel), "changed": False,
                "reason": "读不到文件：%s" % str(e)[:120], "snapshot": ""}
    res = format_text(old, path, root=root, line_range=line_range,
                      preferred=preferred, timeout=timeout)
    if not res.get("ok"):
        return dict(res, rel=str(rel), snapshot="")
    if not res.get("changed"):
        return dict(res, rel=str(rel), snapshot="")
    snap = snapshot_file(root, path, old)
    try:
        tmp = path + ".fmt_tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(res["text"])
        os.replace(tmp, path)
    except OSError as e:
        return {"ok": False, "rel": str(rel), "changed": False,
                "formatter": res.get("formatter", ""), "snapshot": snap,
                "reason": "写回失败：%s" % str(e)[:120]}
    return {"ok": True, "rel": str(rel), "changed": True, "snapshot": snap,
            "formatter": res.get("formatter", ""),
            "before": len(old), "after": len(res["text"]), "reason": ""}


def format_on_save_enabled(trunk, path=""):
    """``编辑.保存格式化``：off/on，**默认 off**。

    默认关的理由：格式化会重排整个文件，静默重排用户/仓库原有风格是很粗鲁的
    行为（本仓库自己就不是 ruff-format 风格）。打开这一条后，保存才会格式化，
    而且是一个可 Ctrl+Z 的编辑块 + backups/format 快照。
    """
    try:
        value = str(trunk.rule("编辑.保存格式化", "off") or "off").lower()
    # 静默是故意的：读不到开关就不格式化，保存照常进行
    except Exception as e:
        _x6_swallowed(__name__, e, "format on save switch")
        return False
    if value not in ("off", "on"):
        value = "off"
    if value == "off":
        return False
    return bool(available_formatters(path))


def format_preferred(trunk):
    """``编辑.格式化工具``：auto/black/ruff/prettier/clang-format/gofmt。"""
    try:
        value = str(trunk.rule("编辑.格式化工具", "auto") or "auto").lower()
    # 静默是故意的：读不到就按 auto 走
    except Exception as e:
        _x6_swallowed(__name__, e, "format tool switch")
        return "auto"
    return value if value in ("auto",) + FORMATTER_NAMES else "auto"


def format_first_enabled(trunk, path=""):
    """``编辑.格式先行``：应用补丁前先格式化目标文件（默认开）。

    和"保存格式化"同开同关：关掉格式化就不会在打补丁时偷偷重排文件。
    """
    if not format_on_save_enabled(trunk, path):
        return False
    try:
        return bool(trunk.rule("编辑.格式先行", True))
    # 静默是故意的：读不到规则按开处理（受上面那道开关约束）
    except Exception as e:
        _x6_swallowed(__name__, e, "format first switch")
        return True


def _update_files(patch):
    """patch 里需要改内容的文件（相对路径）。"""
    out = []
    for item in (patch or {}).get("files") or []:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "").strip().lower()
        if op in ("delete", "rename", "create", "add", "remove", "move"):
            continue
        rel = str(item.get("path") or "").replace("\\", "/")
        if rel and rel not in out:
            out.append(rel)
    return out


def format_patch_files(root, patch, preferred="auto", trunk=None):
    """深度⑤：先格式化目标文件，再确认 hunk 还能定位，定位不了就整体退回。

    为什么是这个顺序
    ---------------
    格式化会把空白/引号/换行重排，模型写的 ``hunk.old`` 可能就对不上了。
    所以这里先**试**：格式化 → 用 hunk_edit 在磁盘新内容上预演 →
      全部能定位：保留格式化结果，继续应用补丁
      有定位不了的：把文件写回格式化前的原文，返回 ok=False + 原因
    这样永远不会停在"格式化了、补丁没落"的半成品状态。
    """
    if trunk is not None:
        preferred = format_preferred(trunk)
    targets = _update_files(patch)
    memory, formatted, skipped = {}, [], []
    for rel in targets:
        if not os.path.isfile(_abs(root, rel)):
            skipped.append({"rel": rel, "reason": "文件不存在（可能是新建）"})
            continue
        res = format_file(root, rel, preferred=preferred)
        if not res.get("ok"):
            skipped.append({"rel": rel, "reason": res.get("reason", "")})
            continue
        if not res.get("changed"):
            skipped.append({"rel": rel, "reason": "格式本身没变化"})
            continue
        memory[rel] = res
        formatted.append(rel)
    if not formatted:
        return {"ok": True, "formatted": [], "skipped": skipped,
                "reason": "没有文件需要格式化"}
    try:
        from core.hunk_edit import plan as hunk_plan
        p = hunk_plan(root, patch)
    except Exception as e:  # 静默是故意的 - 预演失败就退回格式化结果
        _x6_swallowed(__name__, e, "plan after format")
        p = {}
    bad = [h for h in (p.get("hunks") or [])
           if str(h.get("status")) in ("missing", "duplicate")]
    if bad:
        for rel, res in memory.items():
            restore_snapshot(res.get("snapshot") or "", _abs(root, rel))
        return {"ok": False, "formatted": [], "skipped": skipped,
                "reverted": formatted,
                "reason": ("格式化后有 %d 个 hunk 定位失败，已回退格式化"
                           "（建议重新生成补丁）" % len(bad))}
    return {"ok": True, "formatted": formatted, "skipped": skipped,
            "reason": ""}


def format_report(trunk=None, path=""):
    """给界面/自检的一句话：有哪些格式化工具、当前偏好。"""
    names = available_formatters(path)
    preferred = format_preferred(trunk) if trunk is not None else "auto"
    if not names:
        return {"可用": [], "偏好": preferred,
                "摘要": "未安装格式化工具（black / ruff / prettier）"}
    return {"可用": names, "偏好": preferred,
            "摘要": "格式化工具：%s（偏好 %s）" % ("、".join(names), preferred)}
