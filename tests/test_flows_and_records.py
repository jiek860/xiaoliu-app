# -*- coding: utf-8 -*-
"""B6：录放 / 流程 / 日志三个"记录类"模块

守住的都是**记录类最容易犯的错**：
    ① 没在录制/没在记的时候"看起来成功了"（动作静默丢）
    ② 空数据把旧文件覆盖成空（比报错更糟）
    ③ 单个动作/单个模型/单行数据坏了就整份读不出来（应该跳过并报数）
    ④ 只活在内存在，重启就没（必须落盘）
"""
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))


class _T:
    """最小 Trunk 替身：base + data_dir（真实 Trunk 两个都有）"""

    def __init__(self, base, modules=None, config=None):
        self.base = str(base)
        self.data_dir = os.path.join(str(base), "data")
        self.modules = modules or {}
        self.config = config or {}


class _FakeCC:
    """假电脑控制模块：只记调用，不真操作"""

    def __init__(self, boom=None):
        self.calls = []
        self.boom = boom

    def open_app(self, app=""):
        self.calls.append(("open_app", app))
        if self.boom == "open_app":
            raise RuntimeError("打不开")

    def type_text(self, text=""):
        self.calls.append(("type_text", text))

    def hotkey(self, keys=""):
        self.calls.append(("hotkey", keys))


def _tmp():
    return tempfile.mkdtemp(prefix="x6b6_")


# ══════════════════════════════════════════════════════════════
# action_recorder
# ══════════════════════════════════════════════════════════════
def _recorder(base, cc=None):
    from core.action_recorder import ActionRecorder
    up = _T(base, modules={"computer_controller": cc} if cc else None)
    return ActionRecorder(up)


def test_recorder_action_without_recording_is_reported():
    ar = _recorder(_tmp())
    r = ar.add_action("open_app", app="记事本")
    assert r["ok"] is False and "没有在录制" in r["msg"], r
    assert ar.actions == []


def test_recorder_rejects_double_start_and_bad_name():
    ar = _recorder(_tmp())
    assert ar.start("第一次")["ok"] is True
    r2 = ar.start("第二次")
    assert r2["ok"] is False and "已经在录制" in r2["msg"], r2
    ar.stop()
    assert ar.start("..")["ok"] is False


def test_recorder_empty_stop_does_not_clobber_existing_file():
    """空录制不能用空文件覆盖同名旧录制"""
    base = _tmp()
    ar = _recorder(base)
    ar.start("同名")
    ar.stop()                       # 空录制（不生成文件）
    ar.start("同名")
    ar.add_action("type_text", text="hello")
    got = ar.stop()
    assert got["ok"] is True and got["count"] == 1, got

    ar.start("同名")                # 同名已存在 → 拒绝
    assert ar.start("同名")["ok"] is False


def test_recorder_roundtrip_and_markdown():
    base = _tmp()
    ar = _recorder(base)
    ar.start("演示")
    ar.add_action("open_app", app="记事本")
    ar.add_action("wait", seconds=0)
    stopped = ar.stop()
    assert os.path.isfile(stopped["path"])
    assert "演示" in ar.list_recordings()

    got = ar.get_recording("演示")
    assert got["ok"] and got["动作数"] == 2, got
    md = ar.to_markdown()
    assert "演示" in md and "2 个动作" in md
    out = ar.export_md()
    assert out["ok"] and os.path.isfile(out["文件"])
    assert ar.delete("演示")["ok"] is True
    assert "演示" not in ar.list_recordings()


def test_recorder_play_reports_failures_and_skips():
    base = _tmp()
    cc = _FakeCC(boom="open_app")
    ar = _recorder(base, cc=cc)
    ar.start("回放")
    ar.add_action("open_app", app="记事本")
    ar.add_action("wait", seconds=0)
    ar.add_action("screenshot")            # 不支持的动作
    ar.stop()

    r = ar.play("回放", speed=0)            # speed=0 不能除零
    assert r["总数"] == 3, r
    assert r["失败"] == 1 and r["跳过"] == 1, r
    assert r["ok"] is False
    assert "明细" in r
    assert ("type_text", "") not in cc.calls        # 只执行了能执行的


def test_recorder_play_missing_module_and_missing_file():
    base = _tmp()
    ar = _recorder(base)
    assert ar.play("不存在")["ok"] is False
    ar.start("x")
    ar.add_action("open_app", app="x")
    ar.stop()
    r = _recorder(base).play("x")          # 没有 computer_controller
    assert r["ok"] is False and "电脑控制" in r["error"], r


def test_recorder_run_shape():
    ar = _recorder(_tmp())
    r = ar.run()
    assert r["录制数"] == 0 and r["录制中"] is False


# ══════════════════════════════════════════════════════════════
# agent_flow
# ══════════════════════════════════════════════════════════════
def _flow(base):
    from core.agent_flow import AgentFlow
    return AgentFlow(_T(base))


def test_flow_records_and_persists_steps():
    base = _tmp()
    af = _flow(base)
    r = af.record_step("理解意图", "ok", "识别为闲聊")
    assert r["ok"] and r["步骤数"] == 1, r
    af.record_step("调用模型", "running")
    path = os.path.join(base, "data", "agent_flow", af.flow_id + ".jsonl")
    assert os.path.isfile(path), path
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 2, lines


def test_flow_normalises_status_and_rejects_empty_name():
    af = _flow(_tmp())
    af.record_step("步骤", "不知道什么状态")
    assert af.steps[-1]["status"] == "info"
    assert af.record_step("  ", "ok")["ok"] is False


def test_flow_clear_starts_new_flow_and_keeps_history():
    base = _tmp()
    af = _flow(base)
    af.record_step("一", "ok")
    first = af.flow_id
    af.clear()                          # reply_pipeline 每轮回复前会调
    af.record_step("二", "ok")
    assert af.flow_id and af.flow_id != first
    flows = af.list_flows()
    assert first in [f["流程"] for f in flows]
    assert af.get_flow(first)[0]["name"] == "一"


def test_flow_reports_bad_lines_and_exports_markdown():
    base = _tmp()
    af = _flow(base)
    af.start("历史流程", flow_id="old")
    path = os.path.join(base, "data", "agent_flow", "old.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"name": "好步骤", "status": "ok"},
                           ensure_ascii=False) + "\n")
        f.write("坏行\n")
    got = af._read("old")
    assert got["跳过"] == 1 and "读不出来" in got["说明"], got

    md = af.to_markdown("old")
    assert "好步骤" in md
    out = af.export_md(flow_id="old")
    assert out["ok"] and os.path.isfile(out["文件"])
    assert af.delete_flow("old")["ok"] is True


def test_flow_run_shape():
    af = _flow(_tmp())
    assert af.run()["步骤数"] == 0


# ══════════════════════════════════════════════════════════════
# tool_call_logger
# ══════════════════════════════════════════════════════════════
def _logger(base):
    from core.tool_call_logger import ToolCallLogger
    return ToolCallLogger(_T(base))


def test_tool_logger_persists_and_infers_failure():
    base = _tmp()
    tcl = _logger(base)
    assert tcl.log_call("weather", {"city": "北京"}, "晴")["ok"] is True
    bad = tcl.log_call("weather", {}, ValueError("接口 500"), 1.5)
    assert bad["ok"] is True                     # 记日志本身成功
    rows = [c for c in tcl.calls]
    assert rows[-1]["ok"] is False, rows[-1]     # 但这次调用标成失败

    path = os.path.join(base, "data", "tool_calls.jsonl")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 2


def test_tool_logger_rejects_empty_tool_name():
    tcl = _logger(_tmp())
    assert tcl.log_call("", {}, "x")["ok"] is False


def test_tool_logger_stats_aggregate_per_tool():
    base = _tmp()
    tcl = _logger(base)
    tcl.log_call("weather", {}, "晴", 0.5)
    tcl.log_call("weather", {}, RuntimeError("超时"), 1.5)
    tcl.log_call("notes", {}, "好", 0.0)
    st = tcl.stats()
    assert st["总调用"] == 3 and st["总失败"] == 1, st
    w = st["按工具"]["weather"]
    assert w["次数"] == 2 and w["失败"] == 1
    assert w["平均耗时"] == 1.0 and w["最慢"] == 1.5
    md = tcl.to_markdown()
    assert "weather" in md and "按工具" in md
    out = tcl.export_md()
    assert out["ok"] and os.path.isfile(out["文件"])


def test_tool_logger_reports_bad_lines():
    base = _tmp()
    tcl = _logger(base)
    os.makedirs(os.path.join(base, "data"), exist_ok=True)
    with open(tcl.path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"tool": "x", "ok": True}, ensure_ascii=False) + "\n")
        f.write("坏行\n")
    st = tcl.stats()
    assert st["总调用"] == 1
    assert "读不出来" in str(st.get("说明", "")), st


def test_tool_logger_run_and_clear():
    tcl = _logger(_tmp())
    tcl.log_call("t", {}, "ok")
    r = tcl.run()
    assert r["调用数"] == 1 and r["日志总数"] == 1
    tcl.clear()
    assert tcl.calls == [] and tcl.get_calls() == []
