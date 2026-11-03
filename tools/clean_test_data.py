# -*- coding: utf-8 -*-
"""清掉测试/自检留在真实 data/ 里的垃圾 —— 「牛头不对马嘴」的根因之一

背景（2026-11-01 用户截图）
--------------------------
22:19 用户问「查询完没有」，小6 回的是
「我并没有情感…我是一个AI机器人，我的任务是为用户提供服务」。
排查下来，除了规划器/联网搜索的问题，还有一个很脏的原因：真实 data/
早被跑测试和自检的**假对话**污染了 ——

    data/memory.json          userA / userB / checker / 回归 这些测试用户键；
                              default 里还塞着「测试用户消息」「这是自动检测发的消息」
    data/chat_shadow.jsonl    983 行里 890 行是「我的猫叫豆豆」「第 1 轮提问」
    data/chat_failures.jsonl  失败库里混进测试短语，反思建议跟着跑偏
    data/plugin_data/self_reflect/reflect_history.json   同上

真实轮次会读这些文件（近期话题、记忆卡、失败库建议、反思建议），
回复自然被带偏。代码侧已经把落盘统一到 `core/data_paths.py`
（测试/自检重定向到临时目录，见 tests/conftest.py::_redirect_data），
**新的垃圾不会再产生**；这个脚本只负责把**已经躺在里面**的清掉。

判据（只删能证明是测试的）
--------------------------
    1. 测试用户键：userA / userB / checker / 回归 / u1 / u2 —— 名字来自 tests/
    2. 整条文本**恰好等于**夹具文本 —— 不做模糊包含匹配，
       否则真聊天里顺口说的「测试」会被连坐
    3. 整条文本含有**只可能来自自检**的短语（FIXTURE_MARKERS）
    4. 「[压缩记忆]」条目只要正文命中 2/3 就整条删（它本来就是一个摘要）

用法
----
    py -3 tools\\clean_test_data.py                  # 只报告，不动文件（默认干跑）
    py -3 tools\\clean_test_data.py --apply          # 备份后真删
    py -3 tools\\clean_test_data.py --apply --no-backup
    py -3 tools\\clean_test_data.py --base D:\\x       # 清别的目录

安全底线
--------
    · 默认**不动文件**；--apply 会先复制到 backups/data_cleanup_<时间>/ 再写
    · 坏行/读不懂的行**一律保留**（宁可留脏，不可误删）
    · 报告里单独列出「疑似但没删」的（比如同一个问题被重复问了 5 次），
      让人自己判断
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import argparse
import json
import os
import re
import shutil
import sys
import time
import io

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 测试用户键（tests/ 里的夹具名，见 conftest::_redirect_data 的注释）──
TEST_USER_KEYS = frozenset(["userA", "userB", "checker", "回归", "u1", "u2"])

# ── 整句恰好相同的夹具文本（来自 tests/test_reply.py 等）──
#   这几个"看着像真聊天"的（成功了/再试一次/说点什么）**只用于日志**，
#   记忆库不敢动 —— 真用户完全可能回一句"成功了"。
MEMORY_EXACT = frozenset([
    "测试", "测试用户消息", "测试用户", "检测测试",
    "测试AI回复", "测试回复", "模拟模型故障",
    "我的猫叫豆豆", "请记住暗号是菠萝", "测试一下人格",
    "空回复", "没有模型",
])
LOG_EXACT = MEMORY_EXACT | frozenset(["成功了", "再试一次", "说点什么"])

# 「第 1 轮提问」「第 3 轮提问」这类循环提问
FIXTURE_RE = re.compile(r"^第\s*\d+\s*轮提问$")

# ── 只要包含就删（这些串只可能来自自检/夹具，真人不会这么说话）──
FIXTURE_MARKERS = (
    "测试一下本地模型回复是否正常",
    "这是自动检测发的消息",
    "测试AI回复",
    "测试回复",
    "【系统信息】",
    "数据版本: 正常（",
)

# ── 只看不改：疑似重复提问（评测脚本常把同一组题连跑好几遍）──
SUSPICIOUS_MIN_COUNT = 3
SUSPICIOUS_MIN_LEN = 4


def is_test_text(text, exact=None):
    """这条文本是不是测试/自检产生的（exact 给了就按那个集合判整句）"""
    s = str(text or "").strip()
    if not s:
        return False
    if s in (LOG_EXACT if exact is None else exact):
        return True
    if FIXTURE_RE.match(s):
        return True
    return any(m in s for m in FIXTURE_MARKERS)


def clean_memory(memory):
    """返回 (新 memory, 明细)。**不修改入参**。

    明细形如::

        {"用户键": {"userA": 1, "回归": 0}, "条目": 2, "疑似": [("什么是量子纠缠", 5)]}
    """
    detail = {"用户键": {}, "条目": 0, "疑似": []}
    out = {}
    for key, value in list(memory.items()):
        if key in TEST_USER_KEYS and isinstance(value, list):
            detail["用户键"][key] = len(value)
            continue
        out[key] = value
    rows = out.get("default")
    if isinstance(rows, list):
        kept = []
        for row in rows:
            if isinstance(row, dict) and (
                    is_test_text(row.get("u"), MEMORY_EXACT)
                    or is_test_text(row.get("a"), MEMORY_EXACT)):
                detail["条目"] += 1
                continue
            kept.append(row)
        out["default"] = kept
        detail["疑似"] = suspicious_rows(kept)
    return out, detail


def suspicious_rows(rows):
    """同一个问题被问了 >=3 次 —— 多半是评测脚本连跑（只报告，不删）"""
    counts = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        u = str(row.get("u") or "").strip()
        if len(u) < SUSPICIOUS_MIN_LEN or is_test_text(u, MEMORY_EXACT):
            continue
        counts[u] = counts.get(u, 0) + 1
    return sorted([(u, n) for u, n in counts.items() if n >= SUSPICIOUS_MIN_COUNT],
                  key=lambda item: -item[1])


def clean_rows(rows, key="用户"):
    """清 jsonl / 列表里的测试行（失败库、反思历史）。返回 (保留, 删除数)"""
    kept = []
    dropped = 0
    for row in rows:
        if isinstance(row, dict) and is_test_text(row.get(key)):
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped


def clean_jsonl(lines, key="text"):
    """清 jsonl 文本行（影子日志 / 失败库）。读不懂的行**保留**（宁可留脏不可误删）

    保留原行文本，不重新序列化 —— 这些文件是"日志"，
    重排字段会让人对不上时间线和签名。
    """
    kept = []
    dropped = 0
    for line in lines:
        body = line.strip()
        if not body:
            kept.append(line)
            continue
        try:
            row = json.loads(body)
        except ValueError:          # 坏行：保留，交给原样写回
            kept.append(line)
            continue
        if isinstance(row, dict) and is_test_text(row.get(key)):
            dropped += 1
            continue
        kept.append(line)
    return kept, dropped


def clean_shadow_lines(lines):
    """影子日志（data/chat_shadow.jsonl 的字段是 text）"""
    return clean_jsonl(lines, "text")


def clean_failure_lines(lines):
    """失败库（data/chat_failures.jsonl 的字段是 用户）"""
    return clean_jsonl(lines, "用户")


# ---------------------------------------------------------------- 文件读写
def targets(base):
    """要清理的文件：逻辑名 -> 路径"""
    data = os.path.join(str(base), "data")
    return {
        "memory.json": os.path.join(data, "memory.json"),
        "chat_shadow.jsonl": os.path.join(data, "chat_shadow.jsonl"),
        "chat_failures.jsonl": os.path.join(data, "chat_failures.jsonl"),
        "reflect_history.json": os.path.join(
            data, "plugin_data", "self_reflect", "reflect_history.json"),
    }


def _read_json(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_lines(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def plan(base):
    """算出每个文件要删什么（**不落盘**）。返回 (计划, 疑似清单)"""
    result = {}
    paths = targets(base)
    for name, path in paths.items():
        if not os.path.exists(path):
            continue
        try:
            if name == "memory.json":
                memory = _read_json(path)
                if not isinstance(memory, dict):
                    continue
                new, detail = clean_memory(memory)
                pretty = dict(detail, 疑似=["%s ×%d" % (u, n)
                                            for u, n in detail["疑似"]])
                result[name] = {"path": path, "kind": "json",
                                "payload": new, "detail": pretty}
            elif name == "reflect_history.json":
                rows = _read_json(path)
                if not isinstance(rows, list):
                    continue
                kept, dropped = clean_rows(rows)
                result[name] = {"path": path, "kind": "json",
                                "payload": kept, "detail": {"条目": dropped}}
            elif name == "chat_failures.jsonl":
                kept, dropped = clean_failure_lines(_read_lines(path))
                result[name] = {"path": path, "kind": "jsonl",
                                "payload": kept, "detail": {"行": dropped}}
            else:
                kept, dropped = clean_shadow_lines(_read_lines(path))
                result[name] = {"path": path, "kind": "jsonl",
                                "payload": kept,
                                "detail": {"行": dropped,
                                           "总行数": len(kept) + dropped}}
        except (OSError, ValueError):
            # 读不动就跳过这个文件：别的文件照清，坏的那个留给人看
            _x6_swallowed("clean_test_data", sys.exc_info()[1], path)
    return result


def _has_change(item):
    detail = item["detail"]
    for key in ("用户键", "条目", "行"):
        value = detail.get(key)
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, int) and value:
            return True
    return False


def backup(paths, base):
    """把所有要动的文件复制一份，返回备份目录

    按 base 下的**相对路径**摆（backups/data_cleanup_<时间>/data/xxx），
    不拼成一个大平铺文件名 —— Windows 上拼出来会超过 MAX_PATH，
    shutil.copy2 直接报 WinError 3。
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst_root = os.path.join(str(base), "backups", "data_cleanup_%s" % stamp)
    os.makedirs(dst_root, exist_ok=True)
    for path in paths:
        if not os.path.exists(path):
            continue
        rel = os.path.relpath(path, str(base))
        if os.path.isabs(rel) or rel.startswith(".."):
            rel = os.path.basename(path)
        dst = os.path.join(dst_root, rel)
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(path, dst)
    return dst_root


def apply(plan_result, base, do_backup=True):
    """真写。返回 (写了几个文件, 备份目录)"""
    paths = [item["path"] for item in plan_result.values() if _has_change(item)]
    dst = ""
    if paths and do_backup:
        dst = backup(paths, base)
    written = 0
    for item in plan_result.values():
        if not _has_change(item):
            continue
        if item["kind"] == "json":
            with io.open(item["path"], "w", encoding="utf-8") as f:
                json.dump(item["payload"], f, ensure_ascii=False)
        else:
            with io.open(item["path"], "w", encoding="utf-8") as f:
                f.writelines(item["payload"])
        written += 1
    return written, dst


def render(plan_result, applied=False, backup_dir=""):
    lines = []
    if applied:
        lines.append("已清理（备份在 %s）" % (backup_dir or "无"))
    else:
        lines.append("干跑（没有动任何文件；加 --apply 才真删）")
    if not plan_result:
        lines.append("  没有找到需要清理的文件")
    for name, item in sorted(plan_result.items()):
        detail = item["detail"]
        parts = []
        if detail.get("用户键"):
            parts.append("测试用户键 " + " ".join(
                "%s(%d)" % (k, v) for k, v in detail["用户键"].items()))
        if detail.get("条目"):
            parts.append("条目 %s 条" % detail["条目"])
        if detail.get("行"):
            parts.append("行 %s/%s" % (detail["行"], detail.get("总行数", "?")))
        flag = "要删" if _has_change(item) else "干净"
        lines.append("  [%s] %s：%s" % (flag, name, "；".join(parts) or "无"))
        for text in detail.get("疑似") or []:
            lines.append("      疑似未删（重复提问，看着像评测）：%s" % text)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="清掉测试/自检留在 data/ 里的假对话")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--apply", action="store_true", help="真删（默认只报告）")
    ap.add_argument("--no-backup", action="store_true", help="不备份直接写（不建议）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    result = plan(args.base)
    if not args.apply:
        if args.json:
            print(json.dumps({k: v["detail"] for k, v in result.items()},
                             ensure_ascii=False, indent=2))
        else:
            print(render(result))
        return 0

    written, backup_dir = apply(result, args.base, do_backup=not args.no_backup)
    if args.json:
        print(json.dumps({"写了": written, "备份": backup_dir,
                          "明细": {k: v["detail"] for k, v in result.items()}},
                         ensure_ascii=False, indent=2))
    else:
        print(render(result, applied=True, backup_dir=backup_dir))
        print("共写了 %d 个文件。" % written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
