# -*- coding: utf-8 -*-
"""Model price estimation and usage tracking tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.model_pricing import estimate_cost, format_cost, price_for  # noqa: E402
from core.usage_tracker import UsageTracker  # noqa: E402


def test_price_lookup_and_override():
    assert price_for("gpt-4o-mini-2026") == (0.15, 0.60)
    assert price_for("private-model") == (0.0, 0.0)
    assert price_for("private-model", {"private": [1.0, 2.0]}) == (1.0, 2.0)


def test_cost_estimate_and_format():
    c = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert c == 0.75
    assert format_cost(c) == "$0.75"
    assert format_cost(0) == "$0"


def test_tracking_records_estimated_cost(tmp_path):
    from core.llm_usage import LLMUsageMixin
    class T(LLMUsageMixin):
        def __init__(self):
            self.base = str(tmp_path)
            self.config = {"model_prices": {"cheap": [1.0, 2.0]}}
        def _extract_user_text(self, messages):
            return "hello world"
    t = T()
    t._track_usage("cheap-model", "hello", "world" * 4, elapsed=0.1)
    s = UsageTracker(str(tmp_path)).summary(days=1)
    assert s["calls"] == 1
    assert s["cost"] > 0
    assert s["by_model"]["cheap-model"]["cost"] > 0
