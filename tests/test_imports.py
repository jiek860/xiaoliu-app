# -*- coding: utf-8 -*-
import os, sys, importlib
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
def test_core_imports():
    for m in ["core.trunk", "core.llm_client", "core.config", "core.vector_store"]:
        importlib.import_module(m)
