# -*- coding: utf-8 -*-
"""第 8 批 B2 + 深度⑤⑥⑦：跨文件引用、符号地图、相关片段、预算裁剪。"""
import os

import pytest

from core.code_context import CodeContextMixin
from core.context_budget import estimate_tokens, fit_text
from core.workspace_index import WorkspaceIndex, module_name


def _write(root, rel, text):
    p = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


@pytest.fixture()
def repo(tmp_path):
    _write(tmp_path, "core/alpha.py",
           "class Alpha:\n    def run(self):\n        return 1\n\n"
           "def alpha_func():\n    return 'alpha'\n")
    _write(tmp_path, "core/beta.py",
           "from core.alpha import alpha_func\n\n"
           "def beta():\n    return alpha_func()\n")
    _write(tmp_path, "gui/ui.py",
           "from core.alpha import Alpha\n\n"
           "def draw():\n    return Alpha()\n")
    _write(tmp_path, "tests/test_alpha.py",
           "from core.alpha import alpha_func\n\n"
           "def test_x():\n    assert alpha_func()\n")
    # 只有文件名对上、内容没引用：深度⑥ 才算弱关联
    _write(tmp_path, "tests/test_alpha_ui.py",
           "def test_ui():\n    assert True\n")
    return tmp_path


@pytest.fixture()
def index(repo):
    idx = WorkspaceIndex(str(repo), str(repo))
    idx.rebuild()
    return idx


class Host(CodeContextMixin):
    def __init__(self, root, index):
        self.root = str(root)
        self.index = index
        self.open_files = ["core/alpha.py"]
        self.selection = ""


def test_module_name_from_rel_path():
    assert module_name("core/lsp_client.py") == "core.lsp_client"
    assert module_name("core/lsp_client/client.py") == "core.lsp_client.client"
    assert module_name("") == ""


def test_importers_of_finds_files_that_import_it(index):
    assert "core/beta.py" in index.importers_of("core/alpha.py")
    assert "gui/ui.py" in index.importers_of("core/alpha.py")
    assert "core/alpha.py" not in index.importers_of("core/alpha.py")


def test_references_of_skips_definition_lines(index):
    hits = index.references_of("alpha_func")
    assert hits, "应能找到 alpha_func 的引用"
    files = {h["file"] for h in hits}
    assert "core/beta.py" in files
    for hit in hits:
        assert not hit["text"].startswith("def alpha_func"), hit   # 定义行不算引用
    # import 行与调用行都算引用（前者没有"所属符号"，后者能定位到函数体）
    assert any("return alpha_func()" in h["text"] for h in hits)


def test_references_of_is_cached_between_calls(index):
    first = index.references_of("alpha_func")
    again = index.references_of("alpha_func")
    assert first == again
    # 返回的是拷贝：调用方改结果不能污染缓存
    again.append({"file": "x.py", "line": 1, "text": "junk"})
    assert index.references_of("alpha_func") == first


def test_related_symbols_marks_reason_and_weight(index):
    rows = index.related_symbols("core/alpha.py", "alpha_func")
    assert rows
    reasons = {r["reason"] for r in rows}
    assert "同文件" in reasons
    assert all(int(r["weight"]) >= 2 for r in rows)
    # 权重降序：引用了该符号的排在同文件之后也照样在列表里
    weights = [int(r["weight"]) for r in rows]
    assert weights == sorted(weights, reverse=True)


def test_repo_map_orders_files_by_import_heat(index):
    text = index.repo_map()
    assert "core/alpha.py (被" in text
    assert "Alpha" in text and "alpha_func" in text
    # alpha 被两个文件 import，热度高于只被一个文件 import 的
    assert text.splitlines()[0].startswith("core/alpha.py")


def test_repo_map_respects_budget(index):
    text = index.repo_map(max_chars=30)
    assert "地图已到字数上限" in text
    assert len(text) < 200


def test_tests_for_adds_filename_only_matches(index):
    shallow = index.related_tests("core/alpha.py", deep=False)
    deep = index.tests_for("core/alpha.py")
    assert "tests/test_alpha.py" in deep
    assert "tests/test_alpha_ui.py" in deep, "深度⑥：文件名对上也应带出来"
    assert len(deep) >= len(shallow)


def test_fit_text_keeps_whole_lines():
    text = "".join("line %d\n" % i for i in range(40))
    fitted = fit_text(text, 60)
    assert "（已按预算截断）" in fitted
    body = fitted.split("（已按预算截断）")[0]
    assert "line 0" in body
    assert estimate_tokens(fitted) <= 200      # 预算是粗估，别差一个数量级


def test_fit_text_returns_original_when_small():
    text = "print(1)\n"
    assert fit_text(text, 100) == text
    # 预算小到一行都放不下：至少给一小段，不能返回空串
    assert fit_text("x" * 400, 8).strip()


def test_related_snippets_has_headers_and_files(repo, index):
    built = Host(repo, index).related_snippets(symbol="alpha_func",
                                               rel="core/alpha.py")
    assert built["text"]
    assert "--- " in built["text"]
    assert "core/beta.py" in built["text"] or "core/alpha.py" in built["text"]
    assert built["files"]


def test_related_context_guesses_symbol_from_goal(repo, index):
    built = Host(repo, index).related_context("帮我把 alpha_func 改稳一点")
    assert built["symbol"] == "alpha_func" or built["text"]
    assert built["text"]


def test_related_context_without_index_is_empty(repo):
    class NoIndex(Host):
        def __init__(self, root):
            super().__init__(root, None)
    assert NoIndex(repo).related_context("随便改改")["text"] == ""
