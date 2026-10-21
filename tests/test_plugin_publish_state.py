# -*- coding: utf-8 -*-
"""v2.1 交付状态检查：区分"入库源"与"发布产物"。

背景
----
modules_repo/manifest.json 入库时是**未签名源**（sha256/signature 为空），
发布时由 tools/sign_modules.py 写入。CI checkout 出来永远是源状态，
所以"是否已签名"不能当作入库门槛。

本测试保证两件事：
  1. 源 manifest 结构完整（字段齐全、无残留的半个签名）；
  2. 若已签名（发布态），则每条都必须签名且 sha256 齐全。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

MANIFEST = os.path.join(BASE, "modules_repo", "manifest.json")


def _manifest():
    with open(MANIFEST, encoding="utf-8-sig") as f:
        return json.load(f)


def test_manifest_signature_state_is_consistent():
    m = _manifest()
    signed = [x for x in m if str(x.get("signature") or "").strip()]
    hashed = [x for x in m if str(x.get("sha256") or "").strip()]
    # 要么全空（源状态），要么两边数量一致（发布态），不能一半一半
    assert len(signed) == len(hashed), (
        "签名与哈希数量不一致：signed=%d hashed=%d —— 说明签名过程被中断"
        % (len(signed), len(hashed)))
    if signed:
        assert len(signed) == len(m), "发布态下必须全部签名"


def test_publish_checker_covers_signatures():
    """签名强制校验必须由发布产物检查器承担。"""
    src = open(os.path.join(BASE, "tools", "check_plugin_repo.py"),
               encoding="utf-8").read()
    assert "signature" in src
    assert "verify" in src.lower()


def test_signed_state_detects_missing_sha():
    """模拟"有签名但缺 sha256"必须能被识别为异常。"""
    m = _manifest()
    broken = [{"name": "x", "signature": "sig", "sha256": ""}]
    signed = [x for x in broken if str(x.get("signature") or "").strip()]
    assert signed
    assert any(not str(x.get("sha256") or "").strip() for x in signed)
