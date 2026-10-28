# -*- coding: utf-8 -*-
"""运行时依赖对账门禁的测试（tools/check_runtime_imports.py）。

背景：2026-10-27 一天里 openpyxl / python-pptx / pypdf / python-docx 四连踩，
都是"代码里 import、exe 依赖集里没有、CI 全绿"。这里把对账逻辑锁住。
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from tools import check_runtime_imports as gate  # noqa: E402


def _repo(tmp_path, files, lock="", policy=None):
    """造一个最小仓库：core/ + requirements-runtime.lock + tools/policy.json"""
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (tmp_path / "requirements-runtime.lock").write_text(lock, encoding="utf-8")
    pol = tmp_path / "tools" / "runtime_import_policy.json"
    pol.parent.mkdir(parents=True, exist_ok=True)
    pol.write_text(__import__("json").dumps(
        policy or {"skip_dirs": [], "local_packages": ["core"],
                   "module_to_dist": {}, "external_optional": {}},
        ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_load_lock_strips_versions_markers_and_comments(tmp_path):
    lock = tmp_path / "lock.txt"
    lock.write_text("\ufeff# 注释\n\nPillow==13.0.0\n"
                    "python-docx==1.2.0 ; python_version >= '3.9'\n"
                    "-r other.lock\nurllib3[secure]==2.8.0\n",
                    encoding="utf-8")
    names = gate.load_lock(str(lock))
    assert names == {"pillow", "python-docx", "urllib3"}


def test_scan_file_finds_nested_and_from_imports(tmp_path):
    src = tmp_path / "a.py"
    src.write_text(
        "import os\n"
        "try:\n"
        "    from docx import Document\n"
        "except ImportError:\n"
        "    Document = None\n"
        "def f():\n"
        "    import openpyxl\n",
        encoding="utf-8")
    mods = {m for m, _ in gate.scan_file(str(src))}
    assert {"os", "docx", "openpyxl"} <= mods


def test_classify_missing_when_not_in_lock(tmp_path):
    base = _repo(tmp_path, {"core/a.py": "import docx\n"}, lock="lxml==6.1.3\n")
    res = gate.check(base=str(base))
    assert not res["ok"]
    assert [m["模块"] for m in res["缺件"]] == ["docx"]
    assert res["缺件"][0]["发行名"] == "docx"


def test_classify_maps_module_to_distribution(tmp_path):
    base = _repo(tmp_path,
                 {"core/a.py": "import PIL\nimport win32gui\n"},
                 lock="pillow==13.0.0\npywin32==312\n",
                 policy={"skip_dirs": [], "local_packages": ["core"],
                         "module_to_dist": {"PIL": "pillow",
                                            "win32gui": "pywin32"},
                         "external_optional": {}})
    res = gate.check(base=str(base))
    assert res["ok"], res["缺件"]
    assert res["在依赖集"] == ["PIL", "win32gui"]


def test_external_optional_is_allowed_but_reported(tmp_path):
    base = _repo(tmp_path, {"core/a.py": "import chromadb\n"},
                 lock="", policy={"skip_dirs": [], "local_packages": ["core"],
                                  "module_to_dist": {},
                                  "external_optional": {"chromadb": "有兜底"}})
    res = gate.check(base=str(base))
    assert res["ok"]
    assert [x["模块"] for x in res["已声明可选"]] == ["chromadb"]


def test_local_packages_and_skip_dirs_are_ignored(tmp_path):
    base = _repo(tmp_path,
                 {"core/a.py": "import core\nimport guidish\n",
                  "core/_deprecated/old.py": "import torch\n"},
                 lock="", policy={"skip_dirs": ["core/_deprecated"],
                                  "local_packages": ["core", "guidish"],
                                  "module_to_dist": {}, "external_optional": {}})
    res = gate.check(base=str(base))
    assert res["ok"], res["缺件"]
    assert res["在依赖集"] == []


def test_stdlib_is_not_reported(tmp_path):
    base = _repo(tmp_path,
                 {"core/a.py": "import json\nimport pathlib\nimport ctypes\n"},
                 lock="")
    res = gate.check(base=str(base))
    assert res["ok"]
    assert res["扫描模块数"] == 0


def test_real_repo_has_no_missing_runtime_deps():
    """真实仓库必须干净 —— 以后谁新 import 一个没进锁的库，这里先红"""
    res = gate.check()
    missing = [m["模块"] for m in res["缺件"]]
    assert res["ok"], "缺件: %s" % missing
    # 关键能力对应的包必须真的在锁里（防止有人"顺手"删锁行）
    lock = gate.load_lock()
    for dist in ("pillow", "pywin32", "pyautogui", "pyperclip", "uiautomation",
                 "python-docx", "python-pptx", "openpyxl", "pypdf"):
        assert dist in lock, dist in lock


def test_cli_exit_code_reflects_problems(tmp_path, capsys):
    base = _repo(tmp_path, {"core/a.py": "import 没进锁的库\n"})
    rc = gate.main(["--base", str(base)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "缺件" in out


def test_cli_json_output(tmp_path, capsys):
    base = _repo(tmp_path, {"core/a.py": "import docx\n"},
                 lock="python-docx==1.2.0\n",
                 policy={"skip_dirs": [], "local_packages": ["core"],
                         "module_to_dist": {"docx": "python-docx"},
                         "external_optional": {}})
    rc = gate.main(["--base", str(base), "--json"])
    assert rc == 0
    assert '"ok": true' in capsys.readouterr().out
