# -*- coding: utf-8 -*-
"""记忆 v2 灰度对照报告（批次 43.5）。

只读 ``data/chat_shadow.jsonl``，统计：
    - v2 预览字数 vs 旧记忆段字数（目标：注入字数 -20%）
    - 用户问「还记得…」时 v2 是否有可注入内容（目标：命中率 ≥80%）
    - 影子期本来会写入的记忆条数

用法：
    py -3 tools\\memory_report.py
    py -3 tools\\memory_report.py --base . --json data/memory_report.json
    py -3 tools\\memory_report.py --markdown docs/20_优化路线与实施记录.md
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def load_rows(path):
    """读影子日志；坏行跳过。"""
    rows = []
    if not os.path.exists(path):
        return rows
    try:
        with open(path, encoding="utf-8") as fp:
            lines = fp.readlines()
    except OSError:
        return rows
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def summarize(rows):
    """返回灰度统计；分母为 0 时比率记 0。"""
    memory_rows = [r for r in rows if r.get("kind") == "memory_v2"]
    write_rows = [r for r in rows if r.get("kind") == "memory_write"]
    v2_chars = 0
    legacy_chars = 0
    for row in memory_rows:
        try:
            v2_chars += int(row.get("v2_chars") or len(str(row.get("preview") or "")))
        except (TypeError, ValueError):
            v2_chars += len(str(row.get("preview") or ""))
        try:
            legacy_chars += int(row.get("legacy_chars") or 0)
        except (TypeError, ValueError):
            pass
    asks, hits, last_preview = 0, 0, ""
    for row in rows:
        kind = row.get("kind")
        if kind == "memory_v2":
            last_preview = str(row.get("preview") or "")
            continue
        if kind == "memory_write":
            continue
        text = str(row.get("text") or "")
        if "还记得" in text or "记得" in text:
            asks += 1
            if last_preview:
                hits += 1
    count = len(memory_rows)
    return {
        "turns": len([r for r in rows if not r.get("kind")]),
        "memory_shadow": count,
        "v2_chars": v2_chars,
        "legacy_chars": legacy_chars,
        "avg_v2_chars": round(v2_chars / float(count), 1) if count else 0.0,
        "avg_legacy_chars": round(legacy_chars / float(count), 1) if count else 0.0,
        "char_reduction": round(1 - v2_chars / float(legacy_chars), 4)
                          if legacy_chars else 0.0,
        "asks": asks,
        "hits": hits,
        "hit_rate": round(hits / float(asks), 4) if asks else 0.0,
        "write_previews": len(write_rows),
        "source": "",
    }


def markdown(stats, title="记忆 v2 灰度报告"):
    lines = ["# %s" % title, "",
             "- 统计轮次：%d；v2 影子命中：%d 轮" % (
                 stats.get("turns", 0), stats.get("memory_shadow", 0)),
             "- 注入字数：v2 平均 %.1f 字，旧记忆段平均 %.1f 字，变化 %.1f%%" % (
                 stats.get("avg_v2_chars", 0.0),
                 stats.get("avg_legacy_chars", 0.0),
                 -100.0 * stats.get("char_reduction", 0.0)),
             "- 「还记得」命中：%d/%d = %.1f%%" % (
                 stats.get("hits", 0), stats.get("asks", 0),
                 100.0 * stats.get("hit_rate", 0.0)),
             "- 影子期本应写入：%d 条" % stats.get("write_previews", 0),
             "",
             "> 目标：注入字数下降 ≥20%，「还记得」命中率 ≥80% 后再把"
             "「记忆.v2」从 shadow 切到 on。"]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--json", default="")
    parser.add_argument("--markdown", default="")
    args = parser.parse_args(argv)
    base = os.path.abspath(args.base or BASE)
    path = os.path.join(base, "data", "chat_shadow.jsonl")
    stats = summarize(load_rows(path))
    stats["source"] = path
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump(stats, fp, ensure_ascii=False, indent=2)
    text = markdown(stats)
    print(text)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fp:
            fp.write(text + "\n")
    return stats


if __name__ == "__main__":
    main()
