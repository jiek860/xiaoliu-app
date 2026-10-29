# -*- coding: utf-8 -*-
"""批次 46.4：影响面选测、失败定位、flake 隔离。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code import verify  # noqa: E402


class FakeIndex:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def tests_for(self, rel):
        return self.mapping.get(rel, [])

    def outline(self, rel):
        return [{"symbol": "helper", "start_line": 1, "end_line": 9}]


class RelatedIndex:
    def related_tests(self, rel):
        return ["tests/test_other.py"]


class FakeTrunk:
    def __init__(self, rules=None):
        self.rules = rules or {}

    def rule(self, name, default=None):
        return self.rules.get(name, default)


class FakeAgent:
    def __init__(self, root, index=None, rules=None):
        self.root = root
        self.trunk = FakeTrunk(rules)
        self.test_commands = ["py -3 -m pytest -q"]
        self._code_index_v2 = index
        self.events = []

    def detect_test_commands(self):
        return self.test_commands

    def _emit(self, event, data=None):
        self.events.append((event, data or {}))


def test_select_tests_dedupes_and_caps():
    mapping = {"core/a.py": ["tests/test_a.py", "tests/test_a.py"],
               "core/b.py": ["tests/test_b.py"]}
    tests = verify.select_tests(FakeIndex(mapping), ["core/a.py", "core/b.py"])
    assert tests == ["tests/test_a.py", "tests/test_b.py"]


def test_select_tests_supports_related_tests():
    assert verify.select_tests(RelatedIndex(), ["core/a.py"]) == \
        ["tests/test_other.py"]


def test_select_tests_ignores_non_test_paths():
    mapping = {"core/a.py": ["core/a.py", "docs/readme.md"]}
    assert verify.select_tests(FakeIndex(mapping), ["core/a.py"]) == []


def test_build_test_command_only_pytest():
    cmd = verify.build_test_command(["npm test", "py -3 -m pytest -q"],
                                    ["tests/test_a.py"])
    assert cmd.startswith("py -3 -m pytest") and "tests/test_a.py" in cmd
    assert verify.build_test_command(["npm test"], ["tests/test_a.py"]) == ""


def test_selected_commands_off_by_default():
    agent = FakeAgent(".", index=FakeIndex())
    assert verify.selected_commands(agent, ["core/a.py"]) == []


def test_selected_commands_on(tmp_path):
    index = FakeIndex({"core/a.py": ["tests/test_a.py"]})
    agent = FakeAgent(str(tmp_path), index=index,
                      rules={"code.verify_select": "on"})
    cmds = verify.selected_commands(agent, ["core/a.py"])
    assert cmds and "tests/test_a.py" in cmds[0]
    assert agent.events and agent.events[0][0] == "verify_select"


def test_locate_failures_parses_two_formats(tmp_path):
    mod = tmp_path / "core"
    mod.mkdir()
    (mod / "m.py").write_text(
        "def outer():\n    pass\n\n\ndef helper():\n    raise ValueError\n",
        encoding="utf-8")
    out = ('Traceback (most recent call last):\n'
           '  File "' + str(mod / "m.py") + '", line 6, in helper\n'
           "core/m.py:2:1: E501 boom\n")
    found = verify.locate_failures(out, root=str(tmp_path))
    files = {(x["file"], x["line"]) for x in found}
    assert ("core/m.py", 6) in files
    assert ("core/m.py", 2) in files
    helper = [x for x in found if x["line"] == 6][0]
    assert helper["symbol"] == "helper"


def test_locate_failures_uses_index_symbol():
    out = 'File "core/m.py", line 3, in foo'
    found = verify.locate_failures(out, index=FakeIndex())
    assert found[0]["symbol"] == "helper"


def test_locate_digest_formats_lines():
    text = verify.locate_digest([{"file": "a.py", "line": 3,
                                  "symbol": "foo"}])
    assert text == "  - a.py:3 (foo)"


def test_retry_flakes_splits_real_and_flaky():
    state = {"tests/test_a.py::test_a": [False, True]}

    def run_case(test_id):
        seq = state.get(test_id) or [False, False]
        return {"ok": seq.pop(0) if len(seq) > 1 else seq[0]}

    result = verify.retry_flakes(run_case, list(state), retries=1)
    assert result["flakes"] == ["tests/test_a.py::test_a"]
    assert result["real"] == []
    assert result["attempts"] == 2


def test_failed_test_ids_parsed():
    out = ("FAILED tests/test_a.py::test_a - AssertionError\n"
           "FAILED tests/test_b.py::test_b\n")
    ids = verify.failed_test_ids(out)
    assert ids == ["tests/test_a.py::test_a", "tests/test_b.py::test_b"]
