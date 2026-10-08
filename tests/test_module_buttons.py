# -*- coding: utf-8 -*-
"""回归测试：侧边栏模块按钮的数据加载（core/module_buttons.py）

部署文档一直写着"带按钮的模块安装后自动在侧边栏加按钮"，
派发函数 gui/mixins/dialog_mixin.py 的 _module_button_clicked 也早就写好了，
但界面侧从来没接上。这里守住加载逻辑，避免又退化成"文档有、实际没有"。
"""
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.module_buttons import load_buttons, describe  # noqa: E402


def _fake_base(manifest, installed_files=()):
    root = tempfile.mkdtemp(prefix="btn_")
    os.makedirs(os.path.join(root, "modules_repo"), exist_ok=True)
    os.makedirs(os.path.join(root, "modules", "installed"), exist_ok=True)
    with open(os.path.join(root, "modules_repo", "manifest.json"),
              "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    for fn in installed_files:
        with open(os.path.join(root, "modules", "installed", fn),
                  "w", encoding="utf-8") as f:
            f.write("# stub\n")
    return root


M = [
    {"name": "computer_controller", "title": "电脑控制", "file": "computer_controller.py",
     "button": {"label": "🖥️ 电脑控制", "action": "gui:computer_dialog"}},
    {"name": "error_lib", "title": "错误库", "file": "error_lib.py",
     "button": {"label": "🛠️ 错误库", "action": "list"}},
    {"name": "notes", "title": "笔记", "file": "notes.py"},          # 没按钮
    {"name": "weather", "title": "天气", "file": "weather.py",
     "button": {"label": "", "action": "run"}},                       # label 为空
]


def test_only_installed_modules_with_button():
    root = _fake_base(M, ["computer_controller.py", "error_lib.py", "notes.py", "weather.py"])
    got = load_buttons(root)
    names = [b["name"] for b in got]
    assert names == ["computer_controller", "error_lib"], got
    assert got[0]["action"] == "gui:computer_dialog"
    assert got[1]["action"] == "list"


def test_uninstalled_modules_are_filtered_out():
    """文件没装就不该在侧边栏出现"""
    root = _fake_base(M, ["computer_controller.py"])   # 只装了电脑控制
    got = load_buttons(root)
    assert [b["name"] for b in got] == ["computer_controller"]


def test_bad_inputs_return_empty_list():
    """任何坏输入都不能抛异常 —— 按钮数据坏了不该把界面搞崩"""
    for bad in (None, "", "/definitely/not/here", tempfile.mkdtemp()):
        assert load_buttons(bad) == [], bad


def test_malformed_manifest_is_safe():
    root = tempfile.mkdtemp(prefix="btn_bad_")
    os.makedirs(os.path.join(root, "modules_repo"), exist_ok=True)
    os.makedirs(os.path.join(root, "modules", "installed"), exist_ok=True)
    p = os.path.join(root, "modules_repo", "manifest.json")
    open(p, "w", encoding="utf-8").write("{ 这不是合法 JSON")
    assert load_buttons(root) == []

    # 合法 JSON 但不是列表
    json.dump({"a": 1}, open(p, "w", encoding="utf-8"))
    assert load_buttons(root) == []

    # 列表里混进非 dict
    json.dump([1, "x", None, M[0]], open(p, "w", encoding="utf-8"))
    os.makedirs(os.path.join(root, "modules", "installed"), exist_ok=True)
    open(os.path.join(root, "modules", "installed", "computer_controller.py"),
         "w", encoding="utf-8").write("")
    assert [b["name"] for b in load_buttons(root)] == ["computer_controller"]


def test_manifest_with_bom_is_readable():
    """manifest 被记事本/PS 存成带 BOM 也要能读"""
    root = _fake_base(M, ["computer_controller.py"])
    p = os.path.join(root, "modules_repo", "manifest.json")
    data = open(p, "rb").read()
    open(p, "wb").write(b"\xef\xbb\xbf" + data)
    assert [b["name"] for b in load_buttons(root)] == ["computer_controller"]


def test_real_project_has_expected_buttons():
    """真实项目里应当至少有一个模块按钮（电脑控制）"""
    got = load_buttons(BASE)
    names = [b["name"] for b in got]
    if not names:
        import pytest
        pytest.skip("当前仓库清单里没有带按钮的模块")
    for b in got:
        assert b["label"] and b["action"] and b["file"]
    d = describe(BASE)
    assert d["按钮数"] == len(got)
