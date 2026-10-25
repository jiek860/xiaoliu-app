# -*- coding: utf-8 -*-
"""core/code_context.py 的同名测试：仓库地图与上下文拼装。"""
import os

import pytest

from core.code_context import CodeContextMixin
from core.workspace_index import WorkspaceIndex


class Host(CodeContextMixin):
    def __init__(self, root):
        self.root = str(root)
        self.index = WorkspaceIndex(self.root)
        self.open_files = []
        self.selection = ""


def _write(root, rel, text):
    p = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


@pytest.fixture()
def repo(tmp_path):
    _write(tmp_path, "core/alpha.py",
           "def alpha_func():\n    return 'alpha'\n")
    _write(tmp_path, "core/beta.py", "class Beta:\n    pass\n")
    _write(tmp_path, "gui/ui.py", "def draw():\n    pass\n")
    _write(tmp_path, "tests/test_alpha.py",
           "from core.alpha import alpha_func\n\ndef test_x():\n    assert alpha_func()\n")
    _write(tmp_path, "data/secret.py", "SECRET = 1\n")
    _write(tmp_path, "__pycache__/junk.py", "x = 1\n")
    return tmp_path


def test_repo_map_groups_by_directory(repo):
    map_text = Host(repo).repo_map()
    assert "core/ (2): alpha.py, beta.py" in map_text
    assert "gui/ (1): ui.py" in map_text
    assert "tests/ (1): test_alpha.py" in map_text


def test_repo_map_skips_data_and_pycache(repo):
    map_text = Host(repo).repo_map()
    assert "secret.py" not in map_text
    assert "junk.py" not in map_text


def test_repo_map_is_cached(repo):
    h = Host(repo)
    first = h.repo_map()
    _write(repo, "core/gamma.py", "x = 1\n")
    assert h.repo_map() == first          # 实例内缓存，避免每轮重复遍历


def test_repo_map_respects_char_budget(repo):
    text = Host(repo).repo_map(max_chars=40)
    assert "地图已截断" in text


def test_build_context_adds_map_for_vague_goal(repo):
    ctx = Host(repo).build_context("帮我优化一下")
    assert "=== REPO MAP" in ctx["text"]
    assert "core/" in ctx["text"]


def test_build_context_skips_map_when_many_hits(repo):
    for i in range(6):
        _write(repo, "core/mod%d.py" % i,
               "def alphafunc_%d():\n    return 'alphafunc'\n" % i)
    ctx = Host(repo).build_context("alphafunc")
    assert "=== REPO MAP" not in ctx["text"]
    assert ctx["files"]


def test_goal_terms_extracts_english_and_chinese(repo):
    h = Host(repo)
    terms = h._goal_terms("修复 patch_engine 里的回滚问题")
    assert "patch_engine" in terms
    assert any("回滚" in t for t in terms)


def test_llm_messages_declare_json_contract(repo):
    h = Host(repo)
    msgs = h._llm_messages("改个东西", {"text": "ctx"})
    assert msgs[0]["role"] == "system"
    assert "read_file" in msgs[0]["content"]
    assert "改个东西" in msgs[1]["content"]


def test_build_context_includes_user_selection(repo):
    h = Host(repo)
    h.selection = "选中的一段代码"
    ctx = h.build_context("随便改改")
    assert "USER SELECTION" in ctx["text"]
