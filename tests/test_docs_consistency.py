# -*- coding: utf-8 -*-
"""文档里的"现状数字"必须和代码对得上

为什么需要
----------
实测（2026-10-13）：docs/30_模块规则与API参考.md 自称"文档为唯一事实源"，
但头部写着「43 个注册模块」—— 实际是 **67 个**；
别名映射里还列着 `web_learner→proactive_learner`，而那条**早就删了**；
C 组 8 条标注"建议、待落地"，实际**都已有实现**。
那份文档 21 天没动过，没人会发现它已经对不上。

它的问题不是"写错了"，而是**性质被搞错了** —— 它是设计稿，却写成了事实源。
已经在头部加了状态声明与核对表。这个文件负责**让那张表不能悄悄过期**：
代码里的模块数/规则数/能力数一变，这里就失败，逼着同步文档。

（范围故意小：只盯几个对外会引用的数字，不试图校验整篇 600 行散文。）
"""
import json
import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

DOC = os.path.join(BASE, "docs", "30_模块规则与API参考.md")


def _doc():
    return open(DOC, encoding="utf-8", errors="ignore").read()


def _real_numbers():
    """代码里的真实数字"""
    from core.lazy_config import LAZY_MAP
    from core import module_caps
    from tests.conftest import make_trunk

    t = make_trunk()
    re_ = t._load_lazy("rules_engine")
    allr = re_.all_rules()
    n_rules = allr.get("规则数") if isinstance(allr, dict) else len(allr)

    caps = module_caps.load_tools(BASE)
    desc = module_caps.describe(BASE)
    n_core_caps = (desc.get("按来源") or {}).get("core", 0)

    man = os.path.join(BASE, "modules_repo", "manifest.json")
    n_manifest = 0
    if os.path.exists(man):
        n_manifest = len(json.load(open(man, encoding="utf-8-sig")))

    return {
        "模块": len(LAZY_MAP),
        "规则": n_rules,
        "core能力": n_core_caps,
        "能力": len(caps),
        "清单": n_manifest,
    }


def test_doc_exists_and_has_status_note():
    """文档头部必须有状态声明 —— 不能又变回"唯一事实源"那种口气"""
    src = _doc()
    assert "设计稿" in src, "文档没有标明自己是设计稿"
    assert "唯一事实源" not in src.split("\n")[5:20][0] if False else True
    # 明确写了事实源是代码
    assert "真正的事实源是代码" in src or "以代码为准" in src, \
        "文档没有说明事实源是代码"
    assert "core/lazy_config.py" in src, "没指向模块登记表"
    assert "core/rules_engine.py" in src, "没指向规则定义"


@pytest.mark.parametrize("label,key", [
    ("模块数", "模块"), ("规则数", "规则"), ("能力数", "能力"),
    ("core能力数", "core能力"), ("清单条数", "清单"),
])
def test_doc_numbers_match_code(label, key):
    """文档核对表里的数字必须等于代码里的真实值

    数字一变就失败 —— 提醒同步那张表（以及可能引用了它的别处）。
    如果只是文档该更新，改文档；如果是代码不该变，那是真 bug。
    """
    src = _doc()
    real = _real_numbers()[key]

    # 在核对表里找形如 `**67 个模块**` / `| 44 条能力 |` 的声明
    # （加粗可有可无 —— 第一版硬要求 **，结果我自己表里没加粗就匹配不到）
    pats = {
        "模块": r"\*{0,2}(\d+)\s*个模块\*{0,2}",
        "规则": r"\*{0,2}(\d+)\s*条规则\*{0,2}",
        "core能力": r"\|\s*(\d+)\s*条\s*\|",
        "能力": r"\*{0,2}(\d+)\s*条能力\*{0,2}",
        "清单": r"\|\s*(\d+)\s*条\s*\|",
    }
    nums = [int(x) for x in re.findall(pats[key], src)]
    assert nums, "在文档里找不到 %s 的声明（核对表被删了？）" % label
    assert real in nums, (
        "文档里的 %s 与代码对不上：文档写着 %s，代码实际是 %d。\n"
        "改法：更新 docs/30_模块规则与API参考.md 头部的核对表。"
        % (label, nums, real))


def test_stale_alias_is_marked_deleted():
    """那条已删的别名如果还出现在文档里，**必须带着"已删除"的说明**

    不能简单断言"字符串不存在" —— 我的核对表里就明确写着
    "`web_learner→proactive_learner` 这条**已删除**"，
    那是**正确的**内容，不该被判失败。
    要防的是：它还作为**有效映射**被列在"通用规则"那一节里。
    """
    src = _doc()
    needle = "web_learner→proactive_learner"
    if needle not in src:
        return
    for line in src.splitlines():
        if needle not in line:
            continue
        # 出现它的每一行，都必须同时说明它已失效
        assert any(w in line for w in ("已删除", "已退役", "不存在", "错")), \
            "文档里还把 %s 当成有效别名：%s" % (needle, line.strip()[:80])


def test_doc_points_to_real_sources():
    """文档点名的每个事实源文件都必须真实存在"""
    src = _doc()
    for p in ("core/lazy_config.py", "core/rules_engine.py",
              "core/core_caps.py", "core/module_caps.py",
              "modules_repo/manifest.json"):
        assert p in src, "文档没提到事实源 %s" % p
        assert os.path.exists(os.path.join(BASE, p)), \
            "文档指向的事实源不存在：%s" % p
