# -*- coding: utf-8 -*-
"""PatchV2 协议（批次 46.2/46.3）：局部优先、唯一匹配、锚点、语法与最小性。

设计取舍
--------
* **不重造校验器**：路径越界、受保护目录、base_hash、hunk 唯一匹配都沿用
  ``core.patch_engine.validate_patch``，这里只补 v2 独有的规则；
* **已存在的文件禁止 ``write``**：``write`` 等于整文件覆盖，模型一旦把
  1400 行的文件写回 1200 行就会静默丢代码；v2 只允许 ``update + hunks``，
  ``write`` 仅用于新建；
* **行号锚点是"软校验"**：模型给的 ``line`` 与唯一命中位置差 3 行以内算
  通过，差得多只记 warning（不因锚点漂移丢掉一个本来正确的 hunk）；
* **最小性**：单文件改动 >200 行或跨 >5 文件直接拒绝，提示拆分；
* **风险分级**（L2 自动档用）：新建/新增测试=低，单函数小改=中，
  删改/重命名/配置依赖/跨 3 文件/大改=高，受保护路径=禁止；
* **三态开关** ``code.patch_v2``：off 完全走旧逻辑，shadow 只记录校验结果，
  on 才拒绝不合规 patch。默认 shadow，用户可见行为不变。
"""
from __future__ import annotations

import ast
import difflib
import json
import os
import time

from core.patch_engine import (PROTECTED_PARTS, PatchError, _materialize,
                               sha256_text, validate_patch)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MAX_FILES = 5
MAX_DIFF_LINES = 200
MAX_CREATE_LINES = 400
ANCHOR_TOLERANCE = 3
EDIT_LOG = os.path.join("data", "code_edits.jsonl")

CONFIG_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "cargo.toml", "go.mod", "go.sum", "dockerfile", "makefile",
    "tox.ini", "pytest.ini", ".gitlab-ci.yml", "build_release.py",
}
CONFIG_DIRS = (".github/", ".gitlab/", ".circleci/", "requirements/")


def mode(trunk):
    """``code.patch_v2``：off / shadow / on，认不出按 shadow。"""
    try:
        value = str(trunk.rule("code.patch_v2", "shadow") or "shadow").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "patch v2 mode")
        return "shadow"
    return value if value in ("off", "shadow", "on") else "shadow"


def auto_apply_enabled(trunk):
    """``code_agent.auto_apply``：低风险改动是否自动应用，默认关。"""
    try:
        return bool(trunk.rule("code_agent.auto_apply", False))
    except Exception as e:
        _x6_swallowed(__name__, e, "auto apply switch")
        return False


def background_enabled(trunk):
    """``code_agent.background``：工作台任务是否走后台线程，**默认开**。

    为什么默认改成开
    ----------------
    同步执行时整条链路（LLM 请求 → 多轮补丁 → pytest 子进程）都压在 Qt 主线程上，
    用户点"开始"后窗口直接"未响应"，几分钟内连取消都点不动。
    后台线程只是把同一套 Agent 放到 QThread 里跑，事件仍然通过信号回 GUI 线程。

    · 规则 ``code_agent.background``（rules.json）优先；
    · 其次看 ``config.json`` 的 ``code_agent.background`` / ``code_agent_background``；
    · 都没有 → 开。想回到同步版（会卡界面）：上面任一位置设 false 即可。
    """
    try:
        value = trunk.rule("code_agent.background", None)
        if value is not None:
            return bool(value)
    except Exception as e:
        _x6_swallowed(__name__, e, "background switch")
    try:
        cfg = getattr(trunk, "config", None) or {}
        if isinstance(cfg, dict):
            sec = cfg.get("code_agent")
            if isinstance(sec, dict) and sec.get("background") is not None:
                return bool(sec.get("background"))
            if cfg.get("code_agent_background") is not None:
                return bool(cfg.get("code_agent_background"))
    except Exception as e:
        _x6_swallowed(__name__, e, "background switch config")
    return True


def verify_mode(trunk):
    """``code.verify_select``：影响面选测，默认 off（关掉就是全量测试）。"""
    try:
        value = str(trunk.rule("code.verify_select", "off") or "off").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "verify switch")
        return "off"
    return value if value in ("off", "shadow", "on") else "off"


def locate_mode(trunk):
    """``code.locate_failures``：失败定位（file:line → 函数），默认 on（批次 D9）。

    和影响面选测拆开：定位只是给回修提示补一段"失败在哪个函数"，
    不改跑哪些测试，所以可以默认开；选测仍由 ``verify_mode`` 控制。
    """
    try:
        value = str(trunk.rule("code.locate_failures", "on") or "on").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "locate switch")
        return "on"
    return value if value in ("off", "shadow", "on") else "on"


def lint_extra_mode(trunk):
    """``code.lint_extra``：ruff/mypy 附加静态检查，默认 shadow（批次 D9）。

    shadow 只把输出记进结果、不参与 ``ok``（避免旧仓库被历史问题卡住）；
    on 才让类型错/风格错真正挡完成；off 完全不跑。
    """
    try:
        value = str(trunk.rule("code.lint_extra", "shadow") or "shadow").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "lint extra switch")
        return "shadow"
    return value if value in ("off", "shadow", "on") else "shadow"


def _rel(path):
    return str(path or "").replace("\\", "/").strip().lstrip("/")


def _full(root, rel):
    return os.path.join(str(root or "."), _rel(rel).replace("/", os.sep))


def _protected(rel):
    parts = [p for p in _rel(rel).split("/") if p not in ("", ".")]
    return any(p in PROTECTED_PARTS for p in parts) or ".." in parts


def _is_config(rel):
    low = _rel(rel).lower()
    name = os.path.basename(low)
    return name in CONFIG_NAMES or low.startswith(CONFIG_DIRS)


def _hunk_lines(hunk):
    """hunk 影响行数：片段形状按 old 行数；行号形状按 end-start+1。"""
    old = str((hunk or {}).get("old") or "")
    if old:
        return len(old.splitlines())
    try:
        start = int(hunk.get("start", hunk.get("start_line")) or 0)
        end = int(hunk.get("end") or start)
    except (AttributeError, TypeError, ValueError):
        return 1
    return max(1, end - start + 1)


def changed_lines(patch):
    """估算改动行数：hunk 新旧行数之和；create/write 取内容行数。"""
    total = 0
    for fp in (patch or {}).get("files") or []:
        op = str(fp.get("op") or "update")
        if op in ("create", "write"):
            total += len(str(fp.get("content") or "").splitlines())
            continue
        if op != "update":
            continue
        for hunk in fp.get("hunks") or []:
            total += _hunk_lines(hunk)
            total += len(str(hunk.get("new") or "").splitlines())
    return total


def classify_patch(root, patch):
    """给 patch 定风险等级：low / medium / high / forbidden。

    L2 只自动应用 low / medium；high 交给审批；forbidden 直接拒绝
    （``validate_patch`` 也会挡受保护路径，这里再兜一层）。
    """
    files = []
    ops = set()
    for fp in (patch or {}).get("files") or []:
        rel = _rel(fp.get("path"))
        files.append(rel)
        ops.add(str(fp.get("op") or "update"))
    lines = changed_lines(patch)
    reasons = []
    if any(_protected(rel) for rel in files):
        return {"level": "forbidden", "reasons": ["受保护路径，禁止修改"],
                "files": files, "diff_lines": lines, "auto_apply": False}
    if ops & {"delete", "rename"}:
        reasons.append("删除/重命名文件")
    if any(_is_config(rel) for rel in files):
        reasons.append("修改配置/依赖/构建脚本")
    if len(files) >= 3:
        reasons.append("跨 %d 个文件" % len(files))
    if lines > 120:
        reasons.append("改动 %d 行" % lines)
    if reasons:
        level = "high"
    elif ops and ops <= {"create"}:
        level = "low"
        reasons.append("新建文件")
        if any(rel.startswith("tests/") or os.path.basename(rel).startswith("test_")
               for rel in files):
            reasons.append("新增测试")
    elif lines <= 40 and len(files) <= 2:
        level = "medium"
        reasons.append("局部修改 %d 行" % lines)
    else:
        level = "high"
        reasons.append("改动范围偏大")
    return {"level": level, "reasons": reasons, "files": files,
            "diff_lines": lines, "auto_apply": level in ("low", "medium")}


def _anchor_warning(root, fp, rel):
    """模型给了 ``line`` 时校验锚点；偏移过大只记 warning。"""
    text = ""
    try:
        with open(_full(root, rel), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    warnings = []
    for i, hunk in enumerate(fp.get("hunks") or []):
        try:
            anchor = int(hunk.get("line") or 0)
        except (TypeError, ValueError):
            anchor = 0
        if anchor <= 0:
            continue
        old = str(hunk.get("old") or "")
        if not old:
            continue
        idx = text.find(old)
        if idx < 0:
            continue
        actual = text[:idx].count("\n") + 1
        if abs(actual - anchor) > ANCHOR_TOLERANCE:
            warnings.append("%s#%d 行号锚点 %d 与实际 %d 相差较大"
                            % (rel, i, anchor, actual))
    return warnings


def _protocol_errors(root, patch):
    errors, warnings = [], []
    files = patch.get("files") or []
    if len(files) > MAX_FILES:
        errors.append("一次最多改 %d 个文件，当前 %d 个，请拆分"
                      % (MAX_FILES, len(files)))
    total = changed_lines(patch)
    if total > MAX_DIFF_LINES:
        errors.append("单次改动 %d 行超过 %d 行上限，请拆分为小步"
                      % (total, MAX_DIFF_LINES))
    for fp in files:
        rel = _rel(fp.get("path"))
        op = str(fp.get("op") or "update")
        if op == "write":
            if os.path.isfile(_full(root, rel)):
                errors.append("已存在文件禁止 write（会导致整文件覆盖）：%s，"
                              "请改用 update + hunks" % rel)
        if op in ("create", "write"):
            lines = len(str(fp.get("content") or "").splitlines())
            if lines > MAX_CREATE_LINES:
                warnings.append("%s 新建 %d 行，注意是否只是生成物" % (rel, lines))
            continue
        if op == "update":
            for i, hunk in enumerate(fp.get("hunks") or []):
                # 第 6 批：行号形状由本地按文件内容切 old，不需要模型给原文
                if "old" not in hunk and ("start" in hunk or "start_line" in hunk):
                    continue
                if not str(hunk.get("old") or "").strip():
                    errors.append("%s#%d hunk.old 为空" % (rel, i))
            warnings.extend(_anchor_warning(root, fp, rel))
    return errors, warnings


def _render(root, patch):
    """在内存里按顺序模拟应用，返回 {rel: 新内容}（delete 为 None）。"""
    virtual = {}

    def current(rel):
        if rel in virtual:
            return virtual[rel]
        try:
            with open(_full(root, rel), encoding="utf-8", errors="strict") as f:
                return f.read()
        except (OSError, ValueError):
            return None

    for fp in patch.get("files") or []:
        rel = _rel(fp.get("path"))
        op = str(fp.get("op") or "update")
        if op in ("create", "write"):
            virtual[rel] = str(fp.get("content") or "")
        elif op == "delete":
            virtual[rel] = None
        elif op == "rename":
            virtual[_rel(fp.get("new_path"))] = current(rel)
            virtual[rel] = None
        else:
            text = current(rel) or ""
            for hunk in fp.get("hunks") or []:
                hunk = _materialize(hunk, text)
                old = str(hunk.get("old") or "")
                new = str(hunk.get("new") or "")
                if old and text.count(old) == 1:
                    text = text.replace(old, new, 1)
                else:
                    virtual[rel + "#unresolved"] = text
            virtual[rel] = text
    return virtual


def compile_check(root, patch):
    """Python/JSON 语法检查：改完解析不了就不该落盘。"""
    errors, warnings = [], []
    try:
        rendered = _render(root, patch)
    except Exception as e:  # 静默是故意的 - 渲染失败只记录，不误判语法
        _x6_swallowed(__name__, e, "render patch")
        return {"ok": True, "errors": [], "warnings": ["无法预演，跳过语法检查"]}
    for rel, text in rendered.items():
        if rel.endswith("#unresolved"):
            warnings.append("%s 有 hunk 未能在内存中精确定位，语法检查跳过"
                            % rel.split("#")[0])
            continue
        if text is None:
            continue
        low = rel.lower()
        if low.endswith(".py"):
            try:
                ast.parse(text)
            except SyntaxError as e:
                errors.append("%s: Python 语法错误 L%s: %s"
                              % (rel, e.lineno, e.msg))
        elif low.endswith(".json"):
            try:
                json.loads(text or "null")
            except ValueError as e:
                errors.append("%s: JSON 解析失败: %s" % (rel, str(e)[:120]))
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _merge_anchors(normalized, raw):
    """把模型给的 ``line`` 锚点补回规范化 patch（validate_patch 会丢弃它）。"""
    raw_files = (raw or {}).get("files") or []
    for i, fp in enumerate(normalized.get("files") or []):
        raw_fp = raw_files[i] if i < len(raw_files) else {}
        raw_hunks = raw_fp.get("hunks") if isinstance(raw_fp, dict) else None
        raw_hunks = raw_hunks if isinstance(raw_hunks, list) else []
        for j, hunk in enumerate(fp.get("hunks") or []):
            raw_hunk = raw_hunks[j] if j < len(raw_hunks) else {}
            if isinstance(raw_hunk, dict) and raw_hunk.get("line"):
                hunk["line"] = raw_hunk.get("line")
    return normalized


def review(root, patch, trunk=None):
    """完整审查：旧校验 + v2 规则 + 语法 + 风险分级 + 逐 hunk 定位预演。

    返回 ``{ok, errors, warnings, normalized, risk, mode, hunks, hunk_summary}``；
    ``validate_patch`` 抛出的 ``PatchError`` 原样向上传播（旧行为不变）。
    """
    normalized = _merge_anchors(validate_patch(root, patch), patch)
    errors, warnings = _protocol_errors(root, normalized)
    checked = compile_check(root, normalized)
    errors.extend(checked.get("errors") or [])
    warnings.extend(checked.get("warnings") or [])
    risk = classify_patch(root, normalized)
    if risk["level"] == "forbidden":
        errors.append("受保护路径，禁止修改：" + ", ".join(risk["files"]))
    # 第 6 批 B1：逐 hunk 预演（定位分级），把"靠锚点落位"这类信息暴露出来，
    # 界面据 hunk 行给"应用/跳过/撤销"。预演失败不改变 ok 判定（validate 已挡）。
    try:
        from core.hunk_edit import plan as hunk_plan
        planned = hunk_plan(root, normalized)
        warnings.extend(planned.get("warnings") or [])
        hunk_rows = planned.get("hunks") or []
        hunk_summary = _hunk_summary(hunk_rows)
    except Exception as e:  # 静默是故意的 - 行级预演失败不阻断审查
        _x6_swallowed(__name__, e, "hunk plan")
        hunk_rows, hunk_summary = [], ""
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "normalized": normalized, "risk": risk, "mode": mode(trunk),
            "hunks": hunk_rows, "hunk_summary": hunk_summary}


def _hunk_summary(rows):
    """一行中文：3 个 hunk 全部精确定位 / 1 个靠上下文锚点。"""
    rows = list(rows or [])
    if not rows:
        return ""
    exact = sum(1 for r in rows if r.get("status") == "exact")
    other = len(rows) - exact
    if other:
        return "%d 个 hunk：%d 精确定位 · %d 靠模糊匹配" % (len(rows), exact, other)
    return "%d 个 hunk 全部精确定位" % len(rows)


def function_span(code, line_no):
    """找包含指定行的最内层函数/类，返回 1 基的 ``start/end/name``。"""
    try:
        tree = ast.parse(str(code or ""))
    except (SyntaxError, ValueError):
        return None
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        start = int(getattr(node, "lineno", 1) or 1)
        for deco in getattr(node, "decorator_list", []) or []:
            start = min(start, int(getattr(deco, "lineno", start) or start))
        end = int(getattr(node, "end_lineno", start) or start)
        try:
            line_no = int(line_no)
        except (TypeError, ValueError):
            return None
        if not start <= line_no <= end:
            continue
        if best is None or start >= best["start"]:
            best = {"start": start, "end": end, "name": str(node.name)}
    return best


def minimal_hunks(old, new, context=3):
    """把"整文件新内容"压成最少行级 hunk，供内联编辑局部替换。"""
    a = str(old or "").splitlines(True)
    b = str(new or "").splitlines(True)
    out = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for group in matcher.get_grouped_opcodes(context):
        i1, i2 = group[0][1], group[-1][2]
        j1, j2 = group[0][3], group[-1][4]
        old_text = "".join(a[i1:i2])
        new_text = "".join(b[j1:j2])
        if old_text == new_text:
            continue
        out.append({"old": old_text, "new": new_text, "start_line": i1 + 1})
    return out


def record_edit(root, entry):
    """内联编辑审计：谁、哪个任务、哪个文件、前后哈希、结果。"""
    row = dict(entry or {})
    row.setdefault("time", time.time())
    try:
        folder = os.path.join(os.path.abspath(root or "."), "data")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, os.path.basename(EDIT_LOG))
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return path
    except OSError as e:
        _x6_swallowed(__name__, e, "record code edit")
        return ""


def text_hash(text):
    return sha256_text(str(text or ""))


# 换模型的建议：写补丁要严格 JSON + 精确原文片段，小模型/视觉模型做不好。
_MODEL_TIP = ("这通常不是代码问题，而是模型不适合写补丁；"
              "换成代码模型（如 qwen2.5-coder / deepseek-coder / GLM-4）再试，"
              "或把要求拆小、一次只改一个文件")


def explain_patch_error(error):
    """把 PatchError 的原文翻成"（原因, 下一步怎么做）"。

    为什么需要这一层
    ----------------
    ``PatchError`` 的文本是给模型看的（"原文没找到（已尝试空白差异匹配）"），
    直接甩到时间线上，用户只看到"本轮修改无效"反复刷屏，既不知道是模型输出
    格式错了、还是目录选错了，也不知道该换模型还是该点「打开文件夹」。

    纯函数：不读配置、不碰界面，方便单测。
    """
    text = str(error or "").strip()
    low = text.lower()
    if "合法 json" in low or "不是 patch" in low or "未返回有效 patch" in low \
            or "未返回 patch" in low:
        return ("模型这次没给出合法的补丁格式（不是 JSON，或缺少 files 字段）",
                _MODEL_TIP)
    if "路径越界" in text or "受保护路径" in text:
        return ("模型想改的文件不在当前工作区里（被路径检查挡下了）",
                "点顶部「📂 打开文件夹」把工作区切到目标文件夹；"
                "或者让目标里的路径相对工作区写，别用绝对路径")
    if "原文没找到" in text or "原文不唯一" in text:
        return ("模型引用的原文片段和文件对不上（找不到，或出现了不止一次）",
                "确认文件没被手动改过；新建文件请让它标注「新建」，"
                "不要拿 update 改一个还不存在的文件")
    if "不能 create" in text or "请使用 create" in text:
        return ("文件已存在却被要求新建（或文件不存在却被要求修改）",
                "让它改成「修改已有文件」，或者换一个文件名新建")
    if "base_hash" in text or "已被修改" in text:
        return ("文件在生成补丁之后又被改过（哈希对不上）",
                "重新发一次任务，让它按当前文件内容重新生成补丁")
    if "无需修改" in text:
        return ("模型认为这个目标不需要改代码",
                "把要求写具体一点：文件名、函数名、要加的功能和期望结果")
    if "探索轮数超限" in text:
        return ("探索阶段轮数用完（目标太大，没找到落点）",
                "缩小目标：一次只做一个文件/一个函数；或直接说清文件名")
    if "预演失败" in text or "校验失败" in text:
        return ("补丁预演失败（有一个文件对不上，整批都没落盘）",
                "让它分文件提交改动；先改一个文件，跑通再做下一个")
    if "超时" in low:
        return ("模型调用或命令执行超时",
                "把任务拆小；本地模型可以换更小的量化版本")
    return ("补丁没过校验", "把要求写得更具体（文件名 + 函数名 + 期望行为），或换代码模型再试")
