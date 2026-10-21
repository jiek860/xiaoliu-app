# -*- coding: utf-8 -*-
"""插件分级与风险等级推导（小6插件标准 v2.1 §0.3 / 附录 A.4）。

分级规则（由 capabilities 自动推导，manifest 手写值只作参考）：

    L3 系统型：process.enabled 或 ui_control.enabled 或 config.read_secrets
    L2 IO 型 ：network.enabled 或 filesystem.write 非空
    L1 计算型：其余（无 IO、无状态）

风险等级（v2.1 S3）：

    high   = process / ui_control / config.read_secrets
    medium = network 或 filesystem.write
    low    = 其余

设计原则：**只从 capabilities 推导**，不读 manifest 里手写的
risk_level / plugin_tier 作为输入，避免"自己声明自己安全"。
手写值与推导值不一致时，调用方应告警并以推导值为准。
"""
from __future__ import annotations

TIER_L1 = "L1"
TIER_L2 = "L2"
TIER_L3 = "L3"
TIERS = (TIER_L1, TIER_L2, TIER_L3)

RISK_HIGH = "high"
RISK_MEDIUM = "medium"
RISK_LOW = "low"

# L1 豁免条款（v2.1 §0.3）
L1_EXEMPT_CLAUSES = ("N4.3", "N4.4", "N4.5", "N6.4", "N8.3")


def derive(capabilities):
    """从 capabilities 推导 (tier, risk, reasons)。"""
    caps = capabilities or {}
    net = caps.get("network") or {}
    fs = caps.get("filesystem") or {}
    proc = caps.get("process") or {}
    ui = caps.get("ui_control") or {}
    cfg = caps.get("config") or {}

    high_reasons = []
    if proc.get("enabled"):
        high_reasons.append("process execution")
    if ui.get("enabled"):
        high_reasons.append("UI control")
    if cfg.get("read_secrets"):
        high_reasons.append("secret access")

    medium_reasons = []
    if net.get("enabled"):
        medium_reasons.append("network access")
    if fs.get("write"):
        medium_reasons.append("filesystem write")

    if high_reasons:
        return TIER_L3, RISK_HIGH, high_reasons
    if medium_reasons:
        return TIER_L2, RISK_MEDIUM, medium_reasons
    return TIER_L1, RISK_LOW, ["read-only or no declared capability"]


def derive_tier(capabilities):
    return derive(capabilities)[0]


def derive_risk(capabilities):
    return derive(capabilities)[1]


def check_manifest(meta):
    """校验 manifest 中的 risk_level / plugin_tier 是否与推导一致。

    返回 {ok, tier, risk, reasons, mismatches}。
    mismatches 非空 → 调用方应告警（并按推导值覆盖）。
    """
    caps = (meta or {}).get("capabilities")
    tier, risk, reasons = derive(caps)
    mismatches = []
    declared_tier = (meta or {}).get("plugin_tier")
    if declared_tier and str(declared_tier) != tier:
        mismatches.append({"field": "plugin_tier",
                           "declared": declared_tier, "derived": tier})
    declared_risk = (meta or {}).get("risk_level")
    if declared_risk and str(declared_risk) != risk:
        mismatches.append({"field": "risk_level",
                           "declared": declared_risk, "derived": risk})
    return {"ok": not mismatches, "tier": tier, "risk": risk,
            "reasons": reasons, "mismatches": mismatches}


def requires_strict_review(capabilities):
    """L3 是否成立（需要更严格审查）。"""
    return derive_tier(capabilities) == TIER_L3


def exempted_clauses(capabilities):
    """返回该插件可以豁免的条款列表（目前只有 L1 有豁免）。"""
    return L1_EXEMPT_CLAUSES if derive_tier(capabilities) == TIER_L1 else ()
