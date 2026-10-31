# -*- coding: utf-8 -*-
"""记忆整理的数据安全测试

背景（2026-10-13 发现并修复的真问题）
------------------------------------
`memory_organizer.auto_organize()` 读记忆卡时 `except: pass` 跳过解析失败的行，
写回却是 `open(path, "w")` **全量覆盖** —— 那几行就被**永久删除**。

更隐蔽的是返回值：`"原始": len(cards)` 报的是**解析成功的条数**，
不是文件里的实际行数。于是返回 {"原始": 5, "保留": 5} 看起来"一条没丢"，
而文件里可能有 8 行。**数据丢了，报告还说没事。**

这个文件守住三件事：
    ① 解析不了的行必须**原样保留**（不删）
    ② "原始" 必须是文件里的**真实行数**
    ③ 正常数据仍然被正确去重/归档（不能为了保坏行把功能改坏）
"""
import json
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.memory_organizer import MemoryOrganizer    # noqa: E402


class _T:
    def __init__(self, base):
        self.base = base


def _mk(tmp, lines):
    """造一个 memory_cards.jsonl，返回 organizer"""
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    p = os.path.join(tmp, "data", "memory_cards.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
    return MemoryOrganizer(_T(tmp)), p


def _card(facts, t=9e9):
    return json.dumps({"facts": facts, "time": t}, ensure_ascii=False)


def _pref_card(text, t):
    """v2 偏好卡（当前写入侧真正产出的 schema）。"""
    return json.dumps({"type": "preference", "text": text, "time": t},
                      ensure_ascii=False)


def test_bad_lines_are_preserved_not_deleted():
    """解析不了的行必须原样留着 —— 这是本文件的核心断言"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    good = _card(["用户喜欢 Python"])
    bad1 = '{"facts": ["缺右括号"'
    bad2 = "这根本不是 JSON"
    org, p = _mk(tmp, [good, bad1, bad2])

    r = org.auto_organize()

    after = open(p, encoding="utf-8").read()
    assert bad1 in after, "坏行被删了！这是数据丢失"
    assert bad2 in after, "坏行被删了！这是数据丢失"
    assert "用户喜欢 Python" in after, "好数据也不该丢"
    assert r.get("无法解析") == 2, "没有报出坏行数量：%s" % r


def test_original_count_is_real_line_count():
    """'原始' 必须是文件里的真实行数，不是解析成功的条数"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, p = _mk(tmp, [_card(["a"]), "坏行1", _card(["b"]), "坏行2", "坏行3"])
    r = org.auto_organize()
    assert r["原始"] == 5, "原始应为 5（真实行数），实际 %s" % r["原始"]


def test_reports_bad_line_details():
    """要报出是第几行、为什么 —— 不然用户不知道怎么修"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, _p = _mk(tmp, [_card(["a"]), "{坏的}"])
    r = org.auto_organize()
    assert r.get("无法解析明细"), "没给明细：%s" % r
    assert any("第 2 行" in d for d in r["无法解析明细"]), r["无法解析明细"]


def test_normal_dedup_still_works():
    """正常功能不能被改坏：重复的还是要合并"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, p = _mk(tmp, [
        _card(["用户喜欢 Python", "用户住在杭州"]),
        _card(["用户喜欢 Python", "用户住在杭州"]),   # 完全重复 -> 应合并
        _card(["完全不同的内容xyz"]),
    ])
    r = org.auto_organize()
    assert r["合并"] >= 1, "重复卡没被合并：%s" % r
    assert "无法解析" not in r, "正常数据不该报坏行：%s" % r


def test_old_cards_get_archived():
    """30 天前的还是要归档（原有行为不变）"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, p = _mk(tmp, [_card(["新记忆"], t=9e9),
                       _card(["很旧的记忆"], t=1)])       # time=1 -> 很旧
    r = org.auto_organize()
    assert r["归档"] == 1, "旧卡没被归档：%s" % r
    arch = os.path.join(tmp, "data", "archive")
    files = os.listdir(arch)
    assert files, "归档目录里没有文件"
    content = "".join(open(os.path.join(arch, f), encoding="utf-8").read()
                      for f in files)
    assert "很旧的记忆" in content, "归档内容不对"


def test_write_is_atomic_no_tmp_left():
    """写回用临时文件+替换，不留 .tmp 残骸"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, p = _mk(tmp, [_card(["a"]), "坏行"])
    org.auto_organize()
    assert not os.path.exists(p + ".tmp"), "留下了 .tmp 文件"


def test_no_file_at_all():
    """没有记忆卡文件时给明确状态，不报错"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org = MemoryOrganizer(_T(tmp))
    assert org.auto_organize().get("状态") == "无记忆卡"


def test_check_conflicts_does_not_write():
    """冲突检测是只读的 —— 它不能改动记忆卡文件"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, p = _mk(tmp, [_card(["a"]), "{坏的}"])
    before = open(p, encoding="utf-8").read()
    org.check_conflicts()
    assert open(p, encoding="utf-8").read() == before, \
        "check_conflicts 改了文件（它应该是只读的）"


def test_conflicts_carry_line_numbers_and_newer_line():
    """批次 O2：冲突项要带行号与新旧，记忆页才能让用户选保留哪条"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, _p = _mk(tmp, [
        _pref_card("我喜欢短句", t=1),
        _pref_card("我讨厌短句", t=2),
    ])
    r = org.check_conflicts()
    assert r["冲突数"] == 1, r
    c = r["冲突"][0]
    assert c["line1"] == 1 and c["line2"] == 2
    assert c["newer_line"] == 2 and c["older_line"] == 1


def test_resolve_conflict_drops_only_chosen_line():
    """保留较新：只删较早那条，坏行和其他记忆原样留着"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, p = _mk(tmp, [
        _pref_card("我喜欢短句", t=1),
        "坏行",
        _pref_card("我讨厌短句", t=2),
    ])
    conflict = org.check_conflicts()["冲突"][0]
    result = org.resolve_conflict(conflict, keep="new")
    assert result["ok"] is True
    assert result["删除"] == 1
    lines = open(p, encoding="utf-8").read().splitlines()
    assert "坏行" in lines
    assert any("我讨厌短句" in ln for ln in lines)
    assert not any("我喜欢短句" in ln for ln in lines)
    assert not os.path.exists(p + ".tmp")


def test_resolve_conflict_refuses_when_line_changed():
    """写前要核对行内容；用户在别处改过这条就拒绝，避免误删别的记忆"""
    tmp = tempfile.mkdtemp(prefix="x6mem_")
    org, p = _mk(tmp, [
        _pref_card("我喜欢短句", t=1),
        _pref_card("我讨厌短句", t=2),
    ])
    conflict = org.check_conflicts()["冲突"][0]
    lines = open(p, encoding="utf-8").read().splitlines()
    lines[conflict["older_line"] - 1] = _pref_card("我喜欢长句", t=1)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    before = open(p, encoding="utf-8").read()
    result = org.resolve_conflict(conflict, keep="new")
    assert result["ok"] is False
    assert "变了" in result["error"]
    assert open(p, encoding="utf-8").read() == before
