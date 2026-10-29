# -*- coding: utf-8 -*-
"""评测底座：多域用例加载、结构校验、样例执行（批次 41.1/41.2）。"""
import importlib.util
import os

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_run_eval():
    path = os.path.join(BASE, "tools", "run_eval.py")
    spec = importlib.util.spec_from_file_location("x6_run_eval", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_eval = _load_run_eval()


def test_load_all_domains():
    cases = run_eval._load_cases(run_eval.DOMAINS)
    assert len(cases) == 140
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    assert {"safe", "chat", "nl", "code"} == {c["domain"] for c in cases}


def test_validate_all_cases_pass():
    cases = run_eval._load_cases(run_eval.DOMAINS)
    assert run_eval._validate(cases) == []


def test_validate_catches_bad_case():
    errors = run_eval._validate([
        {"id": "x", "kind": "nl_intent", "input": "你好"},
        {"id": "x", "kind": "code_fixture", "fixture": "tests/fixtures/nope",
         "expect_initial": "maybe"},
    ])
    joined = "；".join(errors)
    assert "id 重复" in joined
    assert "缺少 desired" in joined
    assert "fixture 不存在" in joined
    assert "expect_initial" in joined


def test_nl_case_non_strict_records_match():
    out = run_eval._run_case(
        {"id": "t1", "kind": "nl_intent", "input": "/chat 帮我看看这个报错",
         "desired": "chat"}, strict=False, with_model=False)
    assert out["ok"] is True
    assert out["match"] is True
    assert "kind=chat" in out["detail"]


def test_nl_case_strict_fails_on_mismatch():
    out = run_eval._run_case(
        {"id": "t2", "kind": "nl_intent", "input": "你好", "desired": "code"},
        strict=True, with_model=False)
    assert out["ok"] is False
    assert out["match"] is False


def test_code_fixture_runs_and_matches_initial_state():
    out = run_eval._run_case(
        {"id": "t3", "kind": "code_fixture",
         "fixture": "tests/fixtures/code/snake", "expect_initial": "failing"},
        strict=False, with_model=False)
    assert out["ok"] is True, out
    assert "actual=failing" in out["detail"]


def test_chat_case_skipped_without_model():
    with pytest.raises(run_eval.Skipped):
        run_eval._run_case(
            {"id": "t4", "kind": "chat_case", "input": "你好"}, strict=False,
            with_model=False)


def test_summarize_separates_skip_and_match():
    stats = run_eval._summarize([
        {"domain": "nl", "ok": True, "match": True, "has_desired": True},
        {"domain": "nl", "ok": True, "match": False, "has_desired": True},
        {"domain": "chat", "skipped": True, "ok": False},
    ])
    assert stats["nl"]["total"] == 2
    assert stats["nl"]["desired_match"] == 1
    assert stats["nl"]["desired_total"] == 2
    assert stats["nl"]["rate"] == 1.0
    assert stats["chat"]["skipped"] == 1
    assert stats["chat"]["rate"] == 0.0


def test_chat_case_with_model_generates_and_scores(monkeypatch):
    class FakeTrunk:
        def reply(self, text, force_chat=False):
            assert force_chat is True
            return "先看报错。参数没传。"

    monkeypatch.setattr(run_eval, "_chat_trunk", lambda: FakeTrunk())
    out = run_eval._run_case(
        {"id": "t5", "kind": "chat_case", "input": "为什么报错",
         "expect": {"max_sentences": 2, "max_chars": 40}},
        strict=False, with_model=True)
    assert out["ok"] is True
    assert out["text"] == "先看报错。参数没传。"
    assert out["metrics"]["sentences"] == 2


def test_chat_case_with_model_marks_overlong(monkeypatch):
    class FakeTrunk:
        def reply(self, text, force_chat=False):
            return "第一句。第二句。第三句。"

    monkeypatch.setattr(run_eval, "_chat_trunk", lambda: FakeTrunk())
    out = run_eval._run_case(
        {"id": "t6", "kind": "chat_case", "input": "你好",
         "expect": {"max_sentences": 1}}, strict=False, with_model=True)
    assert out["ok"] is False
    assert "句子过多" in out["detail"]


def test_markdown_reports_chat_summary():
    md = run_eval._markdown({
        "total": 1, "passed": 1, "rate": 1.0, "skipped": 0,
        "results": [{"id": "c1", "domain": "chat", "ok": True,
                     "elapsed": 0.1, "detail": ""}],
        "chat_summary": {"count": 2, "avg_chars": 12.5, "repeat_rate": 0.125},
    }, "v-test")
    assert "聊天真实生成：2 条" in md
    assert "8-gram 重复率 0.125" in md
