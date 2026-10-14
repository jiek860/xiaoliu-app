# -*- coding: utf-8 -*-
"""可选依赖映射与登记的测试（#6：省 1 GB 的那一条）

背景
----
小6 的"按需安装"机制**早就有**了：
    requirements.txt           5 个核心依赖
    requirements-optional.txt  可选依赖（按功能分组，注释里记着硬坑）
    scripts/install_optional.bat + 设置里的「功能扩展组件」
    run.py 把 optional_libs/ 加进 sys.path

缺的是"按需**知道**"：optional_libs/ 里装着 1050 MB，
却没有地方记录装了什么、什么版本，也不知道分发时该不该带。
本文件守住 core/optional_deps.py 的那个映射与登记。
"""
import json
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core import optional_deps as od                # noqa: E402


def test_features_cover_the_optional_requirements():
    """映射必须覆盖 requirements-optional.txt 里列出的包

    两边脱节就会出现"装了但状态里显示没有"或反过来。
    """
    req = os.path.join(BASE, "requirements-optional.txt")
    if not os.path.exists(req):
        pytest.skip("没有 requirements-optional.txt")
    listed = set()
    for ln in open(req, encoding="utf-8", errors="ignore"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        name = s.split(">=")[0].split("==")[0].split("<")[0].split(";")[0].strip()
        if name:
            listed.add(name)
    mapped = {p for pkgs in od.FEATURES.values() for p in pkgs}
    # 注释掉的（openai-whisper/torch）不在 listed 里，正好
    missing = listed - mapped
    assert not missing, \
        "这些包在 requirements-optional.txt 里有、但没进功能映射：%s" % missing


def test_import_names_are_right():
    """pip 名和 import 名不一致的必须写对，否则扫描永远报"缺"

    实测：Pillow->PIL、pywin32->win32api、opencv-python->cv2、
    edge-tts->edge_tts、faster-whisper->faster_whisper。
    """
    assert od._import_name("Pillow") == "PIL"
    assert od._import_name("pywin32") == "win32api"
    assert od._import_name("opencv-python") == "cv2"
    assert od._import_name("edge-tts") == "edge_tts"
    assert od._import_name("faster-whisper") == "faster_whisper"
    # 名字一致的不能被改坏
    assert od._import_name("jedi") == "jedi"
    assert od._import_name("playwright") == "playwright"


def test_scan_shape_is_stable():
    s = od.scan(BASE, with_version=False)
    assert set(s) == set(od.FEATURES), "扫出来的功能集合和映射对不上"
    for feat, v in s.items():
        assert set(v) >= {"可用", "缺", "位置", "版本", "装法"}, (feat, v)
        assert isinstance(v["可用"], bool)
        assert isinstance(v["缺"], list)
        if v["可用"]:
            assert not v["缺"], "%s 标了可用却还有缺项" % feat
        else:
            assert v["缺"], "%s 标了不可用却没列出缺什么" % feat
            assert v["装法"], "%s 缺依赖但没给装法" % feat


def test_missing_package_is_reported_with_install_hint():
    """造一个必然缺失的包，确认报得出来且带装法"""
    saved = dict(od.FEATURES)
    try:
        od.FEATURES["测试用不存在功能"] = ["zzz_这个包一定不存在_zzz"]
        s = od.scan(BASE, with_version=False)
        v = s["测试用不存在功能"]
        assert v["可用"] is False
        assert "zzz_这个包一定不存在_zzz" in v["缺"]
        assert "pip install" in v["装法"]
    finally:
        od.FEATURES.clear()
        od.FEATURES.update(saved)


def test_scan_does_not_import_heavy_packages():
    """扫描不能把 torch/cv2 这些重包真的 import 进来

    否则"查一下状态"就要等十几秒、吃几百 MB 内存。
    做法是 find_spec + importlib.metadata，不 import 包本体。
    """
    before = set(sys.modules)
    od.scan(BASE)
    after = set(sys.modules)
    newly = after - before
    for heavy in ("torch", "cv2", "numpy", "faster_whisper", "playwright"):
        assert heavy not in newly, "扫描把 %s import 进来了" % heavy


def test_record_writes_manifest_and_is_atomic():
    d = tempfile.mkdtemp(prefix="x6od_")
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    r = od.record(d)
    assert r.get("ok") is True, r
    p = r["文件"]
    assert os.path.exists(p)
    assert not os.path.exists(p + ".tmp"), "留下了 .tmp"
    data = json.load(open(p, encoding="utf-8"))
    assert "功能" in data and data["功能"], data
    assert "已知版本约束" in data, "没记下踩过的版本坑"
    assert "av" in data["已知版本约束"], "av<19 那个坑没记"


def test_record_to_bad_path_returns_error():
    r = od.record("Z:\\不存在的盘\\x")
    assert isinstance(r, dict) and r.get("ok") is False, r


def test_distribution_hint_quantifies_the_saving():
    """分发建议必须给出**具体能省多少** —— 这是这条建议的全部价值"""
    h = od.distribution_hint(BASE)
    assert "可省" in h, h
    assert "optional_libs" in json.dumps(h, ensure_ascii=False), \
        "建议里没说 optional_libs 不用拷"
    # 真实项目上应当能省很多
    if os.path.isdir(os.path.join(BASE, "optional_libs")):
        mb = float(h["可省"].replace(" MB", ""))
        assert mb > 100, "只省 %.1f MB，建议没意义" % mb


def test_status_summary_is_one_line():
    st = od.status(BASE)
    assert "\n" not in st["摘要"]
    assert "/" in st["摘要"], st["摘要"]
    assert set(st) == {"可用功能", "缺依赖", "摘要"}
