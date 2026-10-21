# -*- coding: utf-8 -*-
"""模块级标准落地组件的测试：结构化错误 / 生命周期 / 工具契约 / 质量门禁。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import plugin_errors as pe  # noqa: E402
from core import tool_contract as tc  # noqa: E402
from core.module_lifecycle import (  # noqa: E402
    LifecycleMixin, ModuleLifecycle, STAGE_NEW, STAGE_STARTED, STAGE_STOPPED,
)


# ---------------- 结构化错误（标准 6.1 / 6.2） ----------------
def test_error_catalog_has_retryable_flags():
    assert pe.ERROR_CATALOG
    for code, meta in pe.ERROR_CATALOG.items():
        assert isinstance(meta.get("retryable"), bool), code
        assert meta.get("zh"), code


def test_make_error_is_json_serializable():
    e = pe.make_error("PLUGIN_TIMEOUT", "超时了", module="weather",
                      context={"upstream": "wttr.in", "obj": object()})
    json.dumps(e)          # 不抛异常即通过
    assert e["error"]["code"] == "PLUGIN_TIMEOUT"
    assert e["error"]["retryable"] is True
    assert e["error"]["context"]["module"] == "weather"


def test_unknown_code_degrades_but_keeps_original():
    e = pe.make_error("SOME_RANDOM", "x")
    assert e["error"]["code"] == "PLUGIN_UNKNOWN"
    assert e["error"]["context"]["original_code"] == "SOME_RANDOM"


def test_retryable_classification():
    assert pe.is_retryable("PLUGIN_TIMEOUT") is True
    assert pe.is_retryable("PLUGIN_BAD_INPUT") is False
    assert pe.is_retryable("PLUGIN_PERMISSION_DENIED") is False


def test_normalize_legacy_chinese_error():
    out = pe.normalize_error({"错误": "缺少依赖 pandas"}, module="plugin_market")
    assert out["error"]["code"] == "PLUGIN_MISSING_DEPENDENCY"
    assert out["error"]["context"]["module"] == "plugin_market"


def test_normalize_timeout_text():
    out = pe.normalize_error({"error": "request timeout after 5s"})
    assert out["error"]["code"] == "PLUGIN_TIMEOUT"
    assert out["error"]["retryable"] is True


def test_normalize_exception_and_empty():
    out = pe.normalize_error(TimeoutError("slow"))
    assert out["error"]["code"] == "PLUGIN_TIMEOUT"
    assert pe.normalize_error(None)["error"]["code"] == "PLUGIN_BAD_OUTPUT"


def test_ok_result_and_helpers():
    r = pe.ok_result({"a": 1}, extra="x")
    assert r["ok"] is True and r["data"] == {"a": 1}
    assert pe.is_error(pe.make_error("PLUGIN_BUSY"))
    assert pe.error_code(pe.make_error("PLUGIN_BUSY")) == "PLUGIN_BUSY"
    assert "PLUGIN_BUSY" in pe.describe({"error": "busy"})


# ---------------- 生命周期（标准 4.1 / 4.2 / 6.4） ----------------
def test_lifecycle_transitions_are_idempotent():
    lc = ModuleLifecycle("m")
    assert lc.stage == STAGE_NEW
    assert lc.transition(STAGE_STARTED)[0] is True
    assert lc.transition(STAGE_STARTED)[1]["already"] is True
    assert lc.transition(STAGE_STOPPED)[0] is True
    ok, info = lc.transition(STAGE_STOPPED)
    assert ok is True and info["already"] is True


def test_lifecycle_rejects_unknown_stage():
    ok, info = ModuleLifecycle("m").transition("bogus")
    assert ok is False
    assert info["error"]["code"] == "PLUGIN_BAD_INPUT"


def test_lifecycle_health_shape():
    lc = ModuleLifecycle("m")
    h = lc.health()
    for key in ("ok", "stage", "uptime_s", "start_count", "stop_count"):
        assert key in h


def test_mixin_start_stop_hooks_and_already_stopped():
    calls = []

    class M(LifecycleMixin):
        NAME = "demo"

        def _on_start(self):
            calls.append("start")

        def _on_stop(self):
            calls.append("stop")

    m = M()
    assert m.start()["ok"] is True
    assert m.stop()["ok"] is True
    assert m.stop()["already_stopped"] is True
    assert calls == ["start", "stop"]
    assert m.health()["stage"] == STAGE_STOPPED


def test_start_failure_rolls_back_stage():
    class M(LifecycleMixin):
        NAME = "bad"

        def _on_start(self):
            raise RuntimeError("boom")

    m = M()
    r = m.start()
    assert r["error"]["code"] == "PLUGIN_INTERNAL_ERROR"
    assert m.health()["stage"] == STAGE_STOPPED


def test_stop_failure_reports_structured_error():
    class M(LifecycleMixin):
        NAME = "bad"

        def _on_stop(self):
            raise RuntimeError("cannot close")

    m = M()
    m.start()
    r = m.stop()
    assert r["ok"] is False
    assert r["error"]["code"] == "PLUGIN_INTERNAL_ERROR"


def test_close_and_shutdown_aliases():
    class M(LifecycleMixin):
        NAME = "demo"

    m = M()
    assert m.close()["stage"] == STAGE_STOPPED
    assert m.shutdown()["ok"] is True


# ---------------- 工具契约（标准 1.3 / 1.5） ----------------
def _tool(**contract):
    return {"name": "t", "method": "m", "desc": "d", "contract": contract}


def test_contract_missing_is_flagged_but_tolerated():
    r = tc.validate_contract({"name": "t"})
    assert r["ok"] is True and r["missing_contract"] is True


def test_contract_valid_passes():
    r = tc.validate_contract(_tool(
        params={"city": {"type": "string", "required": True}},
        returns={"type": "object"},
        errors=["PLUGIN_BAD_INPUT"],
        side_effects=["network:GET wttr.in"],
        idempotent=True, timeout_ms=8000, concurrency_safe=True,
        description="查天气", not_responsible=["写文件"]))
    assert r["ok"] is True, r["errors"]


def test_contract_rejects_bad_types_and_codes():
    r = tc.validate_contract(_tool(
        params={"x": {"type": "pyobject"}},
        returns={"type": "weird"},
        errors=["NOT_A_CODE"],
        side_effects=["magic"]))
    assert r["ok"] is False
    joined = " ".join(r["errors"])
    assert "type must be one of" in joined
    assert "unknown code" in joined
    assert "unknown kind" in joined


def test_contract_timeout_must_be_positive_int():
    r = tc.validate_contract(_tool(timeout_ms="8s"))
    assert r["ok"] is False


def test_validate_tools_detects_duplicate_names():
    r = tc.validate_tools([{"name": "a"}, {"name": "a"}])
    assert r["ok"] is False
    assert any("重复" in e for e in r["errors"])


def test_json_serializable_helper():
    assert tc.is_json_serializable({"a": [1, "b", None, True]}) is True
    assert tc.is_json_serializable({"a": object()}) is False


# ---------------- 质量门禁（标准第十节） ----------------
def test_quality_gate_passes_on_official_modules():
    sys.path.insert(0, os.path.join(BASE, "tools"))
    import check_plugin_quality as q  # noqa: E402
    report = q.check_all()
    assert report["modules"] >= 40
    assert report["errors"] == 0, [r["errors"] for r in report["results"]
                                   if r["errors"]][:3]
    assert report["ok"] is True


def test_base_module_exposes_lifecycle_and_describe():
    from modules.base import BaseModule

    class M(BaseModule):
        NAME = "demo"
        NOT_RESPONSIBLE = ("写文件",)

    m = M()
    assert m.start()["ok"] is True
    assert m.health()["stage"] == STAGE_STARTED
    assert m.describe()["not_responsible"] == ["写文件"]
    assert m.stop()["ok"] is True
    assert "stage" in m.stats()
