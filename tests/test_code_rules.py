# -*- coding: utf-8 -*-
"""项目约定（批次 45.5）：抽取、来源、缓存与失效。"""
import os

from core.code.rules import candidates, extract, summary


def _write(root, rel, text):
    path = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return path


def test_extract_keeps_headings_bullets_and_constraints():
    text = ("# 命名规范\n"
            "这里是一段普通说明，不带约束。\n"
            "- 函数用 snake_case\n"
            "必须为每个函数写测试\n"
            "1. 提交前跑全量\n")
    out = extract(text)
    assert "## 命名规范" in out
    assert "函数用 snake_case" in out
    assert "必须为每个函数写测试" in out
    assert "提交前跑全量" in out
    assert "普通说明" not in out


def test_extract_respects_max_chars():
    out = extract("# 标题\n" + "\n".join("- 必须测试 %d" % i
                                          for i in range(200)), 100)
    assert len(out) <= 100


def test_summary_reads_rules_file_and_caches(tmp_path):
    _write(tmp_path, "x6.rules.md",
           "# 代码规范\n- 函数用 snake_case\n必须跑测试\n")
    out = summary(str(tmp_path))
    assert "来源：x6.rules.md" in out
    assert "snake_case" in out
    cache = os.path.join(str(tmp_path), "data", "code_rules_cache.json")
    assert os.path.isfile(cache)
    assert summary(str(tmp_path)) == out


def test_summary_cache_invalidates_on_change(tmp_path):
    _write(tmp_path, "x6.rules.md", "# 规范\n- 必须测试\n")
    first = summary(str(tmp_path))
    assert "必须测试" in first
    _write(tmp_path, "x6.rules.md",
           "# 规范\n- 必须测试\n- 禁止裸 except\n")
    second = summary(str(tmp_path))
    assert "禁止裸 except" in second


def test_docs_rules_are_discovered(tmp_path):
    _write(tmp_path, "docs/99_代码规范.md",
           "# 接口\n必须保持公开接口兼容\n")
    files = candidates(str(tmp_path))
    assert "docs/99_代码规范.md" in files
    assert "公开接口兼容" in summary(str(tmp_path))


def test_summary_without_rules_is_empty(tmp_path):
    assert summary(str(tmp_path)) == ""
    assert candidates(str(tmp_path)) == []


def test_summary_honours_max_chars(tmp_path):
    _write(tmp_path, "x6.rules.md",
           "\n".join("- 必须测试 %d" % i for i in range(100)))
    out = summary(str(tmp_path), max_chars=200)
    assert len(out) <= 200
