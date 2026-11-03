# -*- coding: utf-8 -*-
"""第 7 批：格式化（B4 + 深度④⑤⑥）。

用**真的子进程**跑一个假格式化器，验证：挑工具 / 选区参数 / 落盘快照 /
格式化把 hunk 打散时自动回退 / 规则开关。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core import code_format as cf     # noqa: E402


def _fake_formatter(tmp_path, body):
    """写一个假格式化器：读 stdin、按 body 变换、写 stdout。"""
    script = tmp_path / "fake_fmt.py"
    script.write_text(
        "import sys\ntext = sys.stdin.read()\n" + body, encoding="utf-8")
    return [sys.executable, str(script)]


def _patch_formatter(monkeypatch, argv):
    monkeypatch.setattr(cf, "_exe", lambda _fmt: list(argv))


def test_formatter_names_and_routing():
    assert "black" in cf.FORMATTER_NAMES and "prettier" in cf.FORMATTER_NAMES
    assert isinstance(cf.available_formatters("a.py"), list)
    fmt = cf.formatter_for("a.py")
    assert fmt is None or fmt["name"] in cf.FORMATTER_NAMES
    assert cf.formatter_for("a.unknown") is None


def test_formatter_for_prefers_requested(monkeypatch):
    monkeypatch.setattr(cf, "_exe", lambda fmt: ["x"])
    assert cf.formatter_for("a.py", "black")["name"] == "black"
    assert cf.formatter_for("a.ts", "prettier")["name"] == "prettier"
    # 指定的工具跟扩展名不搭时，退回能用的那个，而不是报错
    assert cf.formatter_for("a.ts", "black")["name"] == "prettier"


def test_range_args_per_tool():
    text = "a\nb\nc\n"
    black = [f for f in cf._FORMATTERS if f["name"] == "black"][0]
    args = cf._range_args(black, text, (2, 3))
    assert args == ["--line-ranges", "2-3"]
    ruff = [f for f in cf._FORMATTERS if f["name"] == "ruff"][0]
    assert cf._range_args(ruff, text, (2, 3)) is None, "ruff 不支持选区格式化"
    assert cf._range_args(ruff, text, None) == []
    pretty = [f for f in cf._FORMATTERS if f["name"] == "prettier"][0]
    args = cf._range_args(pretty, text, (2, 3))
    assert args[0] == "--range-start" and args[2] == "--range-end"


def test_format_text_without_formatter(monkeypatch):
    monkeypatch.setattr(cf, "formatter_for", lambda path, preferred="auto": None)
    r = cf.format_text("x = 1\n", "a.py")
    assert r["ok"] is False and "格式化工具" in r["reason"]
    assert r["text"] == "x = 1\n"


def test_format_text_runs_subprocess(tmp_path, monkeypatch):
    argv = _fake_formatter(
        tmp_path, 'sys.stdout.write(text.replace("x = 1", "x=1"))')
    _patch_formatter(monkeypatch, argv)
    r = cf.format_text("x = 1\n", "a.py", preferred="ruff")
    assert r["ok"] is True and r["changed"] is True
    assert r["text"] == "x=1\n" and r["formatter"] == "ruff"


def test_format_text_rejects_broken_output(tmp_path, monkeypatch):
    argv = _fake_formatter(tmp_path, 'sys.stdout.write("def f(:\\n")')
    _patch_formatter(monkeypatch, argv)
    r = cf.format_text("def f():\n    return 1\n", "a.py", preferred="ruff")
    assert r["ok"] is False
    assert "语法校验" in r["reason"] and r["text"].startswith("def f():")


def test_format_text_unsupported_range_is_reported(tmp_path, monkeypatch):
    argv = _fake_formatter(tmp_path, "sys.stdout.write(text)")
    _patch_formatter(monkeypatch, argv)
    r = cf.format_text("x = 1\n", "a.py", line_range=(1, 2), preferred="ruff")
    assert r["ok"] is False and "不支持" in r["reason"]


def test_format_file_writes_and_snapshots(tmp_path, monkeypatch):
    argv = _fake_formatter(
        tmp_path, 'sys.stdout.write(text.replace("x = 1", "x=1"))')
    _patch_formatter(monkeypatch, argv)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    r = cf.format_file(str(tmp_path), "a.py", preferred="ruff")
    assert r["ok"] and r["changed"] and r["snapshot"]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x=1\n"
    assert os.path.isfile(r["snapshot"])
    back = cf.restore_snapshot(r["snapshot"], str(tmp_path / "a.py"))
    assert back["ok"] and (tmp_path / "a.py").read_text(
        encoding="utf-8") == "x = 1\n"


def test_format_file_missing(tmp_path):
    r = cf.format_file(str(tmp_path), "nope.py")
    assert r["ok"] is False and "读不到" in r["reason"]


def test_format_patch_files_keeps_when_hunk_survives(tmp_path, monkeypatch):
    argv = _fake_formatter(
        tmp_path, 'sys.stdout.write(text.replace("\\t", "    "))')
    _patch_formatter(monkeypatch, argv)
    (tmp_path / "a.py").write_text("x = 1\ny\t= 2\n", encoding="utf-8")
    patch = {"goal": "改 x", "files": [{"path": "a.py", "hunks": [
        {"old": "x = 1", "new": "x = 9"}]}]}
    r = cf.format_patch_files(str(tmp_path), patch, preferred="ruff")
    assert r["ok"] is True and r["formatted"] == ["a.py"]
    assert (tmp_path / "a.py").read_text(
        encoding="utf-8").startswith("x = 1\n")


def test_format_patch_files_reverts_when_hunk_lost(tmp_path, monkeypatch):
    argv = _fake_formatter(
        tmp_path, 'sys.stdout.write(text.replace("x = 1", "x=1"))')
    _patch_formatter(monkeypatch, argv)
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    patch = {"goal": "改 x", "files": [{"path": "a.py", "hunks": [
        {"old": "x = 1", "new": "x = 9"}]}]}
    r = cf.format_patch_files(str(tmp_path), patch, preferred="ruff")
    assert r["ok"] is False and "定位失败" in r["reason"]
    assert (tmp_path / "a.py").read_text(
        encoding="utf-8") == "x = 1\ny = 2\n", "必须原样回退，不留半成品"


def test_format_patch_files_skips_created_files(tmp_path):
    patch = {"files": [{"op": "create", "path": "new.py",
                        "content": "print(1)\n"}]}
    r = cf.format_patch_files(str(tmp_path), patch, preferred="ruff")
    assert r["ok"] is True and r["formatted"] == []


def test_rules_gate_formatting(monkeypatch):
    class _Trunk:
        def __init__(self, values):
            self.values = values

        def rule(self, name, default=None):
            return self.values.get(name, default)

    off = _Trunk({})
    assert cf.format_on_save_enabled(off, "a.py") is False
    assert cf.format_first_enabled(off, "a.py") is False
    on = _Trunk({"编辑.保存格式化": "on", "编辑.格式先行": True})
    assert cf.format_on_save_enabled(on, "a.py") is True
    assert cf.format_first_enabled(on, "a.py") is True
    assert cf.format_preferred(_Trunk({"编辑.格式化工具": "black"})) == "black"
    assert cf.format_preferred(_Trunk({"编辑.格式化工具": "乱写"})) == "auto"
    # 没有 trunk 也不能抛异常
    assert cf.format_on_save_enabled(None, "a.py") is False


def test_format_report_shape():
    r = cf.format_report(None, "a.py")
    assert set(r) >= {"可用", "偏好", "摘要"}
