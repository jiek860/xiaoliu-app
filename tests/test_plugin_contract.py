# -*- coding: utf-8 -*-
"""插件级契约测试（小6插件标准 v2.1 N8.2(b)）。

框架级测试（tests/test_plugin_standard.py）只验证 manifest 与能力声明是否合规；
本文件验证**每个插件是否真正实现了它声明的东西**：

  * manifest 里的 file/cls 能真正导入并实例化
  * tools 里声明的方法在类上真实存在且可调用
  * 生命周期接口齐备（start/stop/health 由 BaseModule 提供）
  * 返回结果可 JSON 序列化（N1.5）
  * 公开接口在无 trunk 时也不会抛未捕获异常（N6.5 的轻量版）

新增插件时把名字加到 PLUGIN_CASES 即可纳入。
"""
import importlib.util
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))

MANIFEST = os.path.join(BASE, "modules_repo", "manifest.json")
SRC_DIR = os.path.join(BASE, "modules_repo")

# 显式列出的核心用例；其余模块走通用契约检查
PLUGIN_CASES = ("weather", "notes", "todo", "translate", "cache")


def _manifest():
    with open(MANIFEST, encoding="utf-8-sig") as f:
        return json.load(f)


def _by_name():
    return {m.get("name"): m for m in _manifest()}


def _load_module(meta):
    """按 manifest 的 file 导入模块对象（不通过 trunk，不执行副作用）。"""
    path = os.path.join(SRC_DIR, meta.get("file") or "")
    assert os.path.isfile(path), "源码不存在: %s" % path
    spec = importlib.util.spec_from_file_location(
        "contract_" + str(meta.get("name")), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _instantiate(meta):
    mod = _load_module(meta)
    cls = getattr(mod, meta.get("cls") or "", None)
    assert cls is not None, "manifest.cls 指名的类不存在: %s" % meta.get("cls")
    try:
        return cls()
    except TypeError:
        return cls(None)


@pytest.mark.parametrize("name", PLUGIN_CASES)
def test_manifest_entry_is_importable(name):
    meta = _by_name().get(name)
    assert meta is not None, "manifest 里没有 %s" % name
    obj = _instantiate(meta)
    assert obj is not None


@pytest.mark.parametrize("name", PLUGIN_CASES)
def test_declared_tools_exist_on_class(name):
    meta = _by_name()[name]
    obj = _instantiate(meta)
    missing = []
    for tool in meta.get("tools") or []:
        method = tool.get("method")
        if method and not callable(getattr(obj, method, None)):
            missing.append(method)
    assert not missing, "%s 声明的工具方法不存在: %s" % (name, missing)


@pytest.mark.parametrize("name", PLUGIN_CASES)
def test_lifecycle_interface_present(name):
    meta = _by_name()[name]
    obj = _instantiate(meta)
    for method in ("start", "stop", "health"):
        assert callable(getattr(obj, method, None)), \
            "%s 缺少生命周期方法 %s（N4）" % (name, method)


@pytest.mark.parametrize("name", PLUGIN_CASES)
def test_lifecycle_is_idempotent(name):
    meta = _by_name()[name]
    obj = _instantiate(meta)
    first = obj.stop()
    second = obj.stop()
    assert first.get("ok") is True
    assert second.get("already_stopped") is True


@pytest.mark.parametrize("name", PLUGIN_CASES)
def test_stats_is_json_serializable(name):
    meta = _by_name()[name]
    obj = _instantiate(meta)
    data = obj.stats()
    json.dumps(data, ensure_ascii=False)   # 不抛即通过（N1.5）


def test_all_modules_declare_cls_and_file():
    bad = [m.get("name") for m in _manifest()
           if not m.get("file") or not m.get("cls")]
    assert not bad, "manifest 缺 file/cls: %s" % bad


def test_all_modules_instantiate_without_trunk():
    """全部 42 个模块在无 trunk 时也能构造（标准 N1.2 入口可实例化）。"""
    failures = []
    for meta in _manifest():
        try:
            _instantiate(meta)
        except Exception as e:
            failures.append((meta.get("name"), type(e).__name__, str(e)[:60]))
    assert not failures, "无法实例化: %s" % failures[:5]


def test_all_modules_have_lifecycle_methods():
    failures = []
    for meta in _manifest():
        try:
            obj = _instantiate(meta)
        except Exception:
            continue
        if not all(callable(getattr(obj, m, None))
                   for m in ("start", "stop", "health")):
            failures.append(meta.get("name"))
    assert not failures, "缺生命周期方法: %s" % failures[:8]


def test_contract_template_exists():
    """N8.2 要求提供插件级契约测试模板。"""
    tpl = os.path.join(BASE, "templates", "plugin_contract_test.py")
    assert os.path.isfile(tpl), "缺少 templates/plugin_contract_test.py"
