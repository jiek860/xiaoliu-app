# -*- coding: utf-8 -*-
"""结构假设检查（tools/check_shapes.py）的回归测试

这里守的是「共享数据的结构变了、调用方没跟上」这一类 bug。
已经踩过 8 次，形态都一样：不是语法错误，编译和 import 全过，
只有用户点开某个界面时才炸。

本文件有两类用例：
  A. 自证 —— 往临时目录里注入一个**已知错误的**模式，检查器必须抓到。
     没有这类用例，下面那些"项目当前没问题"的断言就只是摆设，
     检查器本身坏掉了也不会有人知道。
  B. 现状 —— 真实项目当前必须干净。
"""
import json
import os
import sys
import unittest.mock as mock

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))

from tools.check_shapes import (  # noqa: E402
    SNAPSHOT, _shape_of_json, check_call_targets, check_manifest,
    check_module_attrs, check_unpack, load_module_api, runtime_data_schema,
    runtime_shapes, scan_call_sites, scan_unpack_sites,
)


# =============================================================== A. 自证

def test_unpack_scanner_flags_wrong_width(tmp_path):
    """注入 `for k, (a, b) in LAZY_MAP.items()`，检查器必须报错

    这正是 plugin_market.list_all() 当初的写法：LAZY_MAP 的值是 3 元组，
    按 2 个解包必然抛 too many values to unpack，整个插件市场扫描失败。
    """
    (tmp_path / "bad.py").write_text(
        "for k, (a, b) in LAZY_MAP.items():\n    pass\n", encoding="utf-8")

    sites = scan_unpack_sites(roots=[str(tmp_path)])
    assert len(sites) == 1, "扫描器没找到这个解包点"
    assert sites[0][2] == 2, "扫描器没读出解包宽度"

    checked, probs = check_unpack(3, roots=[str(tmp_path)])
    assert checked == 1
    assert probs, "检查器没能发现「按 2 个解包 3 元组的值」"


def test_unpack_scanner_accepts_correct_width(tmp_path):
    """宽度对得上就不该报"""
    (tmp_path / "ok.py").write_text(
        "for k, (a, b, c) in LAZY_MAP.items():\n    pass\n", encoding="utf-8")
    checked, probs = check_unpack(3, roots=[str(tmp_path)])
    assert checked == 1 and not probs


def test_unpack_scanner_ignores_opaque_value(tmp_path):
    """`for k, v in ...` 第二项是单个名字，不构成形状假设，不该报"""
    (tmp_path / "opaque.py").write_text(
        "for k, v in LAZY_MAP.items():\n    pass\n", encoding="utf-8")
    checked, probs = check_unpack(3, roots=[str(tmp_path)])
    assert checked == 0 and not probs


def test_call_scanner_flags_missing_method(tmp_path):
    """注入一个不存在的方法调用，检查器必须抓到"""
    (tmp_path / "bad2.py").write_text(
        'x = t.call("vector_store", "definitely_not_a_method")\n', encoding="utf-8")

    sites = scan_call_sites(roots=[str(tmp_path)])
    assert len(sites) == 1
    assert sites[0][2] == "vector_store"
    assert sites[0][3] == "definitely_not_a_method"

    api = {"vector_store": {"search", "add", "run"}}
    checked, probs, unknown, probes = check_call_targets(api, roots=[str(tmp_path)])
    assert checked == 1
    assert probs, "检查器没能发现「调用了不存在的方法」"


def test_call_scanner_accepts_existing_method(tmp_path):
    (tmp_path / "ok2.py").write_text(
        'x = t.call("vector_store", "search", "q")\n', encoding="utf-8")
    api = {"vector_store": {"search", "add", "run"}}
    checked, probs, unknown, probes = check_call_targets(api, roots=[str(tmp_path)])
    assert checked == 1 and not probs


def test_call_scanner_skips_probe_idiom(tmp_path):
    """call("模块", "__no__") 是故意的探针，不该算成 bug"""
    (tmp_path / "probe.py").write_text(
        't.call("task_loop", "__no__")\n', encoding="utf-8")
    api = {"task_loop": {"run"}}
    checked, probs, unknown, probes = check_call_targets(api, roots=[str(tmp_path)])
    assert not probs
    assert len(probes) == 1
    assert checked == 0


def test_call_scanner_ignores_non_literal(tmp_path):
    """变量形式的调用抓不到也不该乱报"""
    (tmp_path / "var.py").write_text(
        't.call(mod_name, method_name)\n', encoding="utf-8")
    assert scan_call_sites(roots=[str(tmp_path)]) == []


# ------------------------------------------------- 2b 属性访问的自证

def test_attr_scanner_flags_missing_attr(tmp_path):
    """注入 `vs = _load_lazy("vector_store")` 之后读不存在的属性，必须抓到

    这正是自检读 vs.embeddings 的那个 bug：属性早没了，
    getattr 的默认值兜住不报错，但逻辑是错的。
    """
    (tmp_path / "bad3.py").write_text(
        'def f(self):\n'
        '    vs = self.trunk._load_lazy("vector_store")\n'
        '    return vs.embeddings\n', encoding="utf-8")
    api = {"vector_store": {"search", "add", "run"}}
    checked, probs, guarded = check_module_attrs(api, roots=[str(tmp_path)])
    assert checked == 1, "扫描器没找到这个属性访问"
    assert probs, "检查器没能发现「访问了不存在的属性」"


def test_attr_scanner_accepts_existing_attr(tmp_path):
    (tmp_path / "ok3.py").write_text(
        'def f(self):\n'
        '    vs = self.trunk._load_lazy("vector_store")\n'
        '    return vs.search("q")\n', encoding="utf-8")
    api = {"vector_store": {"search", "add", "run"}}
    checked, probs, _ = check_module_attrs(api, roots=[str(tmp_path)])
    assert checked == 1 and not probs


def test_attr_scanner_does_not_leak_across_functions(tmp_path):
    """一个函数里的模块绑定不能泄漏到另一个函数

    这是个真实踩过的坑：模块级作用域如果直接 walk 整棵树，
    函数 a 里的 `gc = self._load_lazy("group_chat")` 会泄漏到函数 b，
    把标准库的 gc.collect() 误判成「group_chat 没有 collect 方法」。
    """
    (tmp_path / "leak.py").write_text(
        'import gc\n'
        '\n'
        'def a(self):\n'
        '    gc = self.trunk._load_lazy("group_chat")\n'
        '    return gc.compose("hi")\n'
        '\n'
        'def b(self):\n'
        '    gc.collect()\n', encoding="utf-8")
    api = {"group_chat": {"compose"}}
    checked, probs, _ = check_module_attrs(api, roots=[str(tmp_path)])
    assert not probs, "作用域泄漏了: %s" % probs


def test_attr_scanner_skips_hasattr_guarded(tmp_path):
    """被 hasattr 保护过的属性访问不算 bug（那是防御性写法）"""
    (tmp_path / "g.py").write_text(
        'def f(self):\n'
        '    m = self.trunk.modules.get("memory_loop")\n'
        '    if m and hasattr(m, "recall"):\n'
        '        return m.recall("q")\n', encoding="utf-8")
    api = {"memory_loop": {"run"}}          # 故意不给 recall
    checked, probs, guarded = check_module_attrs(api, roots=[str(tmp_path)])
    assert not probs
    assert guarded == 1


def test_attr_scanner_ignores_attribute_assignment(tmp_path):
    """给模块对象挂属性是合法的，不该算成「访问了不存在的属性」"""
    (tmp_path / "set.py").write_text(
        'def f(self):\n'
        '    m = self.trunk._load_lazy("llm")\n'
        '    m.something_new = 1\n', encoding="utf-8")
    api = {"llm": {"chat"}}
    checked, probs, _ = check_module_attrs(api, roots=[str(tmp_path)])
    assert not probs


# ------------------------------------------------- 数据存储结构

def test_data_shape_helper_hides_user_keys():
    """用户主键的文件只记值的形状，不把用户名写进快照（快照要进 git）"""
    s = _shape_of_json({"xiao6": [{"u": "a", "a": "b"}], "admin": [{"u": "c"}]},
                       hide_keys=True)
    assert s["kind"] == "map-of"
    dumped = json.dumps(s, ensure_ascii=False)
    assert "xiao6" not in dumped and "admin" not in dumped
    assert set(s["value"]["item_keys"]) == {"u", "a"}


def test_data_shape_helper_records_normal_dict_keys():
    """结构键是代码定义的，要照实记下来（别为了藏用户名把有用信息一起藏掉）"""
    s = _shape_of_json({"三元组": [], "实体": {}})
    assert s["kind"] == "dict"
    assert s["keys"] == ["三元组", "实体"]


def test_data_stores_readable_and_expected_kind():
    """核心数据存储必须读得出来，且形态没变

    v5->v6 那次迁移（vectors.json -> vectors.db）就是这里悄悄变的：
    代码还在按 JSON 读，文件早就是 SQLite 了。文件不存在是允许的
    （首次运行），但存在就必须是预期形态。
    """
    sch = runtime_data_schema()
    for k, v in sch.items():
        assert v.get("kind") != "error", "%s 读取失败: %s" % (k, v.get("error"))
    for k in ("data.chats.db", "data.vectors.db"):
        if sch.get(k, {}).get("kind") != "absent":
            assert sch[k]["kind"] == "sqlite", "%s 不再是 sqlite: %s" % (k, sch[k])


# =============================================================== B. 现状

def test_lazy_map_value_arity_is_uniform():
    """LAZY_MAP 的值元数必须一致，否则所有按下标/解包的调用方都得改"""
    from core.lazy_config import LAZY_MAP
    arities = {len(v) for v in LAZY_MAP.values() if isinstance(v, (list, tuple))}
    assert arities == {3}, (
        "LAZY_MAP 的值不是统一的 3 元组: %s\n"
        "改了结构就要去 tools/check_shapes.py 里同步调用方的假设" % arities)


def test_no_bad_unpacking_in_project():
    """项目里不能有按错误宽度解包 LAZY_MAP 的地方"""
    from core.lazy_config import LAZY_MAP
    arity = {len(v) for v in LAZY_MAP.values() if isinstance(v, (list, tuple))}.pop()
    checked, probs = check_unpack(arity)
    assert not probs, "发现解包宽度不对:\n  " + "\n  ".join(probs)


@pytest.fixture(scope="module")
def module_api():
    """真实加载所有模块收集 API（屏蔽后台服务，避免占端口/联网）"""
    from core.trunk import Trunk
    with mock.patch.object(Trunk, "_start_background", lambda self: None), \
         mock.patch.object(Trunk, "_warmup", lambda self: None), \
         mock.patch.object(Trunk, "_auto_unload_loop", lambda self: None), \
         mock.patch.object(Trunk, "_warmup_ollama", lambda self: None):
        api, failed = load_module_api()
    return api, failed


def test_all_call_targets_exist(module_api):
    """每个 call("模块","方法") 的方法都必须真的存在

    这条能抓到「按钮看着有、点了只弹『功能不可用』」——
    历史上 error_lib.auto_fix、file_upload.read、proactive_learner.learn
    都是这么被找出来的。
    """
    api, _failed = module_api
    checked, probs, unknown, probes = check_call_targets(api)
    assert checked > 20, "检查到的调用点太少（%d），扫描器可能坏了" % checked
    assert not probs, "有调用指向不存在的方法:\n  " + "\n  ".join(probs)


def test_manifest_contract():
    """清单条目字段齐全、文件存在、名字在登记表里"""
    probs, n = check_manifest()
    assert n > 0, "清单是空的"
    assert not probs, "清单契约有问题:\n  " + "\n  ".join(probs)


def test_no_shape_drift_from_snapshot():
    """共享结构的形状不能悄悄变

    变了就说明有调用方的假设可能已经失效 —— 先跑
        python tools/check_shapes.py
    看有没有问题，确认无误后再用 --update 更新基准。
    """
    assert os.path.exists(SNAPSHOT), (
        "缺少基准快照，先跑: python tools/check_shapes.py --update")
    old = json.load(open(SNAPSHOT, encoding="utf-8"))
    now = runtime_shapes()
    drift = {k: (old.get(k), now.get(k)) for k in now
             if k in old and old[k] != now[k]}
    assert not drift, (
        "共享结构发生了漂移（旧 -> 新）:\n  %s\n"
        "请确认调用方都改好了，再跑 tools/check_shapes.py --update 更新基准"
        % "\n  ".join("%s: %s -> %s" % (k, a, b) for k, (a, b) in drift.items()))
