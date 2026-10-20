# -*- coding: utf-8 -*-
"""Best-effort token price estimates for the usage dashboard.

Prices are USD per 1M tokens and may go stale. Users can override them with a
``model_prices`` config mapping: {"model-prefix": [input, output]}.
"""
from __future__ import annotations

DEFAULT_PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "qwen-turbo": (0.05, 0.10),
    "qwen-plus": (0.40, 1.20),
    "qwen-max": (1.60, 6.40),
    "glm-4-flash": (0.0, 0.0),
}


def price_for(model, prices=None):
    table = dict(DEFAULT_PRICES)
    if isinstance(prices, dict):
        for k, v in prices.items():
            try:
                table[str(k)] = (float(v[0]), float(v[1]))
            except Exception:  # 静默是故意的
                continue
    name = str(model or "").lower()
    for prefix in sorted(table, key=len, reverse=True):
        if name.startswith(prefix.lower()):
            return table[prefix]
    return (0.0, 0.0)


def estimate_cost(model, tokens_in=0, tokens_out=0, prices=None):
    pin, pout = price_for(model, prices)
    return round((max(0, int(tokens_in)) * pin +
                  max(0, int(tokens_out)) * pout) / 1_000_000.0, 8)


def format_cost(value):
    value = float(value or 0)
    if value <= 0:
        return "$0"
    if value < 0.01:
        return "$%.4f" % value
    return "$%.2f" % value
