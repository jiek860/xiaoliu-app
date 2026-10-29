# -*- coding: utf-8 -*-
"""实体解析（批次 44.2）：文件/符号/测试/分支落地与候选。

全部用临时项目 + 真实 WorkspaceIndex，避免 mock 掉索引后测不到边界。
"""
import os

from core.nl.entities import (branches, build_index, resolve_target,
                              resolve_targets, resolve_text)


def _write(root, rel, text):
    path = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return path


def _project(tmp):
    _write(tmp, "core/agent_router.py",
           "def route_goal(goal):\n    return goal\n\n\n"
           "class Router:\n    pass\n")
    _write(tmp, "core/chat/state.py",
           "def classify_intent(text):\n    return 'chat'\n")
    _write(tmp, "core/chat/planner.py",
           "def plan_reply(state):\n    return {}\n")
    _write(tmp, "tests/test_agent_router.py",
           "from core.agent_router import route_goal\n")
    _write(tmp, "docs/readme.md", "# hi\n")
    return build_index(str(tmp), rebuild=True)


def test_index_is_reused_without_rebuild(tmp_path):
    index = _project(tmp_path)
    again = build_index(str(tmp_path))
    assert "core/agent_router.py" in again.data["files"]
    assert index.data["files"].keys() == again.data["files"].keys()


def test_file_exact_path(tmp_path):
    index = _project(tmp_path)
    out = resolve_target({"type": "file",
                          "value": "core/agent_router.py"},
                         root=str(tmp_path), index=index)
    assert out["ok"] is True
    assert out["path"] == "core/agent_router.py"


def test_file_suffix_and_basename(tmp_path):
    index = _project(tmp_path)
    suffix = resolve_target({"type": "file", "value": "chat/state.py"},
                            root=str(tmp_path), index=index)
    assert suffix["ok"] is True and suffix["path"] == "core/chat/state.py"
    base = resolve_target({"type": "file", "value": "planner.py"},
                          root=str(tmp_path), index=index)
    assert base["ok"] is True and base["path"] == "core/chat/planner.py"


def test_file_prefix_returns_candidates_not_ok(tmp_path):
    index = _project(tmp_path)
    out = resolve_target({"type": "file", "value": "state"},
                         root=str(tmp_path), index=index)
    assert out["ok"] is False
    assert "core/chat/state.py" in out["candidates"]


def test_unknown_file_has_no_candidates(tmp_path):
    index = _project(tmp_path)
    out = resolve_target({"type": "file", "value": "nope.py"},
                         root=str(tmp_path), index=index)
    assert out["ok"] is False and out["candidates"] == []


def test_symbol_resolves_file_and_line(tmp_path):
    index = _project(tmp_path)
    out = resolve_target({"type": "symbol", "value": "classify_intent"},
                         root=str(tmp_path), index=index)
    assert out["ok"] is True
    hit = out["symbols"][0]
    assert hit["file"] == "core/chat/state.py"
    assert hit["line"] == 1


def test_symbol_prefix_is_candidate_only(tmp_path):
    index = _project(tmp_path)
    out = resolve_target({"type": "symbol", "value": "classify"},
                         root=str(tmp_path), index=index)
    assert out["ok"] is False
    assert "classify_intent" in out["candidates"]


def test_test_name_resolution(tmp_path):
    index = _project(tmp_path)
    out = resolve_target({"type": "test", "value": "test_agent_router"},
                         root=str(tmp_path), index=index)
    assert out["ok"] is True
    assert out["path"] == "tests/test_agent_router.py"


def test_unknown_test_offers_test_candidates(tmp_path):
    index = _project(tmp_path)
    out = resolve_target({"type": "test", "value": "test_none"},
                         root=str(tmp_path), index=index)
    assert out["ok"] is False
    assert out["candidates"] and len(out["candidates"]) <= 5


def test_branches_from_refs_and_packed(tmp_path):
    _write(tmp_path, ".git/refs/heads/main", "abc\n")
    _write(tmp_path, ".git/refs/heads/feat/x", "def\n")
    _write(tmp_path, ".git/packed-refs",
           "# pack-refs\nghi refs/heads/release\n")
    assert branches(str(tmp_path)) == ["feat/x", "main", "release"]
    out = resolve_target({"type": "branch", "value": "ma"},
                         root=str(tmp_path))
    assert out["ok"] is False
    assert out["candidates"][0] == "main"
    exact = resolve_target({"type": "branch", "value": "feat/x"},
                           root=str(tmp_path))
    assert exact["ok"] is True


def test_non_git_has_no_branches(tmp_path):
    assert branches(str(tmp_path)) == []


def test_candidates_respect_limit(tmp_path):
    for i in range(8):
        _write(tmp_path, "core/mod%d.py" % i, "x = %d\n" % i)
    index = build_index(str(tmp_path), rebuild=True)
    out = resolve_target({"type": "file", "value": "mod"},
                         root=str(tmp_path), index=index, limit=3)
    assert len(out["candidates"]) == 3


def test_resolve_text_integrates_intent_and_entities(tmp_path):
    index = _project(tmp_path)
    info = resolve_text("修复 core/agent_router.py 里 route_goal 的报错",
                        root=str(tmp_path), index=index)
    assert info["intent"] == "fix_error"
    assert info["entities_ok"] is True
    kinds = [r["type"] for r in info["resolved"]]
    assert "file" in kinds and "symbol" in kinds


def test_resolve_text_reports_unresolved(tmp_path):
    index = _project(tmp_path)
    info = resolve_text("修复 core/agent_router.py 里 no_such_symbol 的报错",
                        root=str(tmp_path), index=index)
    assert info["entities_ok"] is False
    assert info["unresolved"]
    assert info["unresolved"][0]["type"] == "symbol"


def test_disk_fallback_without_index(tmp_path):
    _write(tmp_path, "core/only.py", "x = 1\n")
    out = resolve_target({"type": "file", "value": "core/only.py"},
                         root=str(tmp_path), index=None)
    assert out["ok"] is True and out["path"] == "core/only.py"
    many = resolve_targets([{"type": "file", "value": "only.py"}],
                           root=str(tmp_path), index=None)
    assert many[0]["ok"] is True
