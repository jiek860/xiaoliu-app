# -*- coding: utf-8 -*-
"""代码 Agent 的轮次策略与终止条件。

讨论过的问题
------------
原来 `CodeAgent.run(max_rounds=3)` 写死 3 轮，而且只有"测试通过"和
"用完轮次"两种出口。模型连续两轮改同一个地方、报同一个错时，剩下的轮次
只是重复烧 token —— 用户也看不出为什么停。

这里把策略独立出来，便于测试，也便于以后接配置页：
* 轮次上限可配置（显式参数 > 环境变量 > trunk.config > 默认 12），
  并夹在 1~15 之间；
* 终止条件显式化：测试全绿 / 两轮没有新错误（错误指纹相同）/ 轮次用尽；
* 每次终止都给出 `reason`，调用方可以原样展示给用户。
"""
from __future__ import annotations

import hashlib
import os
import re

DEFAULT_MAX_ROUNDS = 12
MIN_MAX_ROUNDS = 1
MAX_MAX_ROUNDS = 15
ENV_KEY = "X6_CODE_AGENT_MAX_ROUNDS"


def _config_number(trunk):
    cfg = getattr(trunk, "config", None) or {}
    if not isinstance(cfg, dict):
        return None
    for key in ("code_max_rounds", "code_agent_max_rounds"):
        if cfg.get(key) not in (None, ""):
            return cfg.get(key)
    section = cfg.get("code_agent")
    if isinstance(section, dict) and section.get("max_rounds") not in (None, ""):
        return section.get("max_rounds")
    return None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_max_rounds(value=None, trunk=None):
    """解析轮次上限：显式参数 > 环境变量 > 配置 > 默认值，并夹取范围。"""
    raw = value
    if raw in (None, ""):
        raw = os.environ.get(ENV_KEY)
    if raw in (None, ""):
        raw = _config_number(trunk)
    n = _as_int(raw)
    if n is None:
        n = DEFAULT_MAX_ROUNDS
    return max(MIN_MAX_ROUNDS, min(MAX_MAX_ROUNDS, n))


_NOISE_RE = re.compile(
    r"(?:0x[0-9a-fA-F]+|[/\\][\w./\\-]+\.py[:\s]\d*|"
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?|"
    r"\b\d+(?:\.\d+)?\s*(?:s|ms|sec|seconds)\b)")


def normalize_output(text):
    """把测试输出归一化，去掉路径/时间/耗时这类每轮都会变的噪声。"""
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = _NOISE_RE.sub("<x>", s)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def failure_fingerprint(*outputs):
    """失败错误指纹：同样的错误 -> 同样的指纹。"""
    raw = normalize_output("\n".join(str(x or "") for x in outputs))
    if not raw:
        return ""
    return hashlib.sha1(raw.encode("utf-8", "replace"),
                        usedforsecurity=False).hexdigest()[:16]


def failure_text(tests=None, lint=None):
    parts = []
    for item in (tests or {}).get("results") or []:
        if item.get("ok") is False or item.get("exit_code") not in (0, None):
            parts.append(str(item.get("output") or ""))
    for item in (lint or {}).get("results") or []:
        if item.get("ok") is False or item.get("exit_code") not in (0, None):
            parts.append(str(item.get("output") or ""))
    return "\n".join(parts)


def evaluate_round(*, round_no, max_rounds, tests, lint,
                   fingerprint_history=None, patch_history=None,
                   patch_id=""):
    """判断这一轮之后是否继续。

    返回 dict：
        stop        是否终止
        reason      tests_green / no_progress / max_rounds / continue
        message     给用户看的一句话
        fingerprint 本轮错误指纹
    """
    fingerprints = list(fingerprint_history or [])
    patches = list(patch_history or [])
    quality_ok = bool((tests or {}).get("ok") and (lint or {}).get("ok"))
    if quality_ok:
        return {"stop": True, "reason": "tests_green",
                "message": "测试与 lint 全绿，任务完成", "fingerprint": ""}

    fp = failure_fingerprint(failure_text(tests, lint))
    same_patch = bool(patch_id and patches and patches[-1] == patch_id)
    # 连续两轮错误指纹相同 = 这一轮没有带来新信息；同一 patch 再试也没意义。
    repeated = bool(fp and fingerprints and (
        (same_patch and fp in fingerprints) or fingerprints[-1] == fp))
    if repeated:
        return {"stop": True, "reason": "no_progress",
                "message": "连续两轮没有产生新错误/新改动，提前停止避免重复消耗",
                "fingerprint": fp}
    if int(round_no) >= int(max_rounds):
        return {"stop": True, "reason": "max_rounds",
                "message": "已用尽 %d 轮修改上限" % int(max_rounds),
                "fingerprint": fp}
    return {"stop": False, "reason": "continue",
            "message": "错误有变化，继续回修", "fingerprint": fp}


def describe(max_rounds):
    return "轮次上限 %d（可配置，范围 %d~%d）" % (
        int(max_rounds), MIN_MAX_ROUNDS, MAX_MAX_ROUNDS)
