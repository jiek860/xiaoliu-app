# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
def test_trunk_call_missing():
    from core.trunk import Trunk
    t = Trunk()
    r = t.call("__not_exist__", "run")
    assert isinstance(r, dict)
    assert r.get("ok") is False
