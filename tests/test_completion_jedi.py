# -*- coding: utf-8 -*-
"""批次 47.1/47.2：jedi 可选补全与候选排序（逻辑层）。

jedi 是可选依赖：没装的环境跳过 jedi 相关用例，排序/回退用例照样跑。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code import completion as cp  # noqa: E402

_JEDI_OK = cp.jedi_available()
need_jedi = pytest.mark.skipif(not _JEDI_OK, reason="没装 jedi（可选依赖）")


class FakeTrunk:
    """只实现补全需要的两个入口：base 与 rule。"""

    base = BASE

    def __init__(self, rules=None):
        self.rules = dict(rules or {})

    def rule(self, key, default=None):
        return self.rules.get(key, default)


# ---------------------------------------------------------------- 排序
def test_rank_order_is_local_recent_same_dir_index():
    words = ["z_other", "i_index", "s_same", "r_recent", "l_local"]
    out = cp.rank_words(words, "z", local={"l_local"}, recent={"r_recent"},
                        same_dir={"s_same"}, indexed={"i_index"})
    assert out == ["l_local", "r_recent", "s_same", "i_index", "z_other"]


def test_rank_keeps_jedi_results_right_after_local():
    out = cp.rank_words(["print", "path", "parse"], "pa", local={"parse"},
                        jedi_words={"path"},
                        indexed={"print"})
    assert out[0] == "parse"
    assert out[1] == "path"


def test_rank_prefers_case_sensitive_prefix():
    out = cp.rank_words(["Printer", "print"], "Pr")
    assert out == ["Printer", "print"]


def test_rank_dedup_and_limit():
    out = cp.rank_words(["a", "a", "b", "c"], "", limit=2)
    assert out == ["a", "b"]


def test_tier_falls_back_to_other():
    assert cp._tier("x", set(), set(), set(), set(), set()) == 5


# ---------------------------------------------------------------- 开关
def test_jedi_switch_default_off_and_reads_trunk():
    assert cp.jedi_enabled(None) is False
    assert cp.jedi_enabled(FakeTrunk()) is False
    assert cp.jedi_enabled(FakeTrunk({"code_complete.jedi": True})) is True
    assert cp.jedi_enabled(FakeTrunk({"code_complete.jedi": "on"})) is True
    assert cp.jedi_enabled(FakeTrunk({"code_complete.jedi": "off"})) is False


def test_project_root_and_indexed_words():
    class Idx:
        data = {"symbols": {"foo": [], "bar": []}}

    class FakeIndexTrunk(FakeTrunk):
        base = "C:/proj"

        def get_workspace_index(self):
            return Idx()

    assert cp.project_root(FakeIndexTrunk()) == "C:/proj"
    assert cp.project_root(None, "/a/b/c.py") == os.path.dirname(
        os.path.abspath("/a/b/c.py"))
    assert cp.project_root(None) == ""
    assert cp.indexed_words(FakeIndexTrunk()) == {"foo", "bar"}
    assert cp.indexed_words(None) == set()


# ---------------------------------------------------------------- jedi
@need_jedi
def test_jedi_completions_basic():
    names = cp.jedi_completions("import os\nos.pa", "", 2, 5, limit=5)
    assert "path" in names
    assert all(not n.startswith("__") for n in names)


@need_jedi
def test_jedi_completions_cross_file(tmp_path):
    (tmp_path / "mypkg.py").write_text("def greet(name):\n    return name\n",
                                       encoding="utf-8")
    code = "import mypkg\nmypkg.gr"
    names = cp.jedi_completions(code, str(tmp_path / "main.py"), 2, 8,
                                limit=5, root=str(tmp_path))
    assert "greet" in names
    assert str(tmp_path) not in sys.path, "临时加进 sys.path 的根必须还原"


def test_jedi_completions_unavailable_returns_empty(monkeypatch):
    monkeypatch.setattr(cp, "jedi_available", lambda force=False: False)
    assert cp.jedi_completions("import os\nos.pa", "", 2, 5) == []


@need_jedi
def test_jedi_completions_bad_position_does_not_raise():
    assert cp.jedi_completions("x = 1\n", "", 999, 999) == []


# ---------------------------------------------------------------- 编排
def test_complete_words_falls_back_to_base_words():
    base = ["print", "pathlib", "parse_args"]
    out = cp.complete_words(base, "import pathlib\nparse", "a.py", 2, 5,
                            prefix="par", jedi=False)
    assert out["source"] == "local"
    assert out["words"] and set(out["words"]).issubset(set(base))
    assert out["words"][0] == "parse_args"


def test_complete_words_adds_same_dir_and_index_hits():
    out = cp.complete_words(["print"], "", "a.py", 1, 0, prefix="hel",
                            same_dir={"helper_local"},
                            indexed={"helper_x", "other", "helmet"})
    words = out["words"]
    assert "helper_local" in words
    assert "helper_x" in words and "helmet" in words
    assert "other" not in words
    assert words.index("helper_local") < words.index("helper_x")


def test_complete_words_caps_index_hits():
    names = {"sym_%03d" % i for i in range(80)}
    out = cp.complete_words([], "", "", 1, 0, prefix="sym", indexed=names,
                            index_hits=5)
    assert sum(1 for w in out["words"] if w.startswith("sym_")) == 5


@need_jedi
def test_complete_words_uses_jedi_when_enabled(tmp_path):
    out = cp.complete_words([], "import os\nos.pa", str(tmp_path / "a.py"),
                            2, 5, prefix="pa", jedi=True, root=str(tmp_path))
    assert out["source"] == "jedi"
    assert "path" in out["words"]


def test_same_dir_words_and_cache(tmp_path):
    (tmp_path / "a.py").write_text("def alpha():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("class Beta:\n    pass\n", encoding="utf-8")
    names = cp.same_dir_words(str(tmp_path / "a.py"))
    assert "Beta" in names and "alpha" not in names
    again = cp.same_dir_words(str(tmp_path / "a.py"))
    assert again == names
    assert cp.same_dir_words("") == set()


# ---------------------------------------------------------------- 控件
def test_editor_uses_80ms_debounce_and_local_source():
    pytest.importorskip("PyQt5.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    from gui.code_editor_widget import CodeEditWidget

    app = QApplication.instance() or QApplication([])  # noqa: F841
    w = CodeEditWidget()
    try:
        assert w._complete_timer.interval() == 80
        w.setPlainText("def parse_args():\n    pass\n\nparse")
        cur = w.textCursor()
        cur.movePosition(cur.End)
        w.setTextCursor(cur)
        w.trunk = FakeTrunk()
        w._try_complete(force=True)
        assert w._completion_source == "local"
        assert w._completer.completionPrefix() == "parse"
        assert w._completer.completionCount() >= 1
        w._insert_completion("parse_args")
        assert w._recent_words[0] == "parse_args"
    finally:
        w.deleteLater()
