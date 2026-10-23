# -*- coding: utf-8 -*-
"""v3.1 新功能集成测试：直接调用真实实现，不用复制逻辑。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _LLM:
    def __init__(self, answer="ok"):
        self.answer = answer
        self.calls = []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        return self.answer


def test_skill_registry_disable_blocks_load(tmp_path):
    from core.skill_registry import SkillRegistry

    class T:
        base = str(tmp_path)

    cap = tmp_path / "data" / "plugin_data" / "skill_capture" / "skills"
    cap.mkdir(parents=True)
    (cap / "demo.md").write_text("hello", encoding="utf-8")
    reg = SkillRegistry(T())
    reg.disable("demo")
    assert reg.load("demo") is None
    assert reg.get_enabled_prompts() == ""


def test_skill_registry_safe_install_rejects_zip_slip(tmp_path):
    import zipfile
    from core.skill_registry import SkillRegistry

    class T:
        base = str(tmp_path)

    z = tmp_path / "bad.x6skill"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.txt", "x")
    r = SkillRegistry(T()).install_from_file(str(z))
    assert r["ok"] is False
    assert not (tmp_path / "evil.txt").exists()


def test_skills_ui_entry_is_real_and_simplified():
    from core.feature_registry import FEATURES
    from gui.mixins.ui_actions_mixin import UIActionsMixin
    from PyQt5.QtWidgets import QApplication, QPushButton

    assert FEATURES["skills"].action == "open_skills_dialog"
    assert callable(UIActionsMixin.open_skills_dialog)

    from gui.skills_dialog import SkillsDialog

    class T:
        base = BASE
        modules = {}

    app = QApplication.instance() or QApplication([])  # noqa: F841
    d = SkillsDialog(T())
    try:
        buttons = d.findChildren(QPushButton)
        assert len(buttons) <= 4, [b.text() for b in buttons]
    finally:
        d.close()


def test_web_agent_action_failure_is_not_success(tmp_path):
    from modules.installed.web_agent import WebAgent

    img = tmp_path / "page.png"
    img.write_bytes(b"x")

    class Browser:
        def open(self, url, headless=True): return {"ok": True}
        def screenshot(self, path=None): return {"ok": True, "截图": str(img)}
        def click(self, selector): return {"错误": "not found"}
        def type_text(self, selector, text): return {"错误": "not found"}
        def scroll(self, *a, **k): return {"错误": "no"}
        def wait(self, *a, **k): return {"ok": True}
        def back(self): return {"ok": True}

    class VLM:
        def describe_image(self, path): return {"描述": "page"}

    class T:
        modules = {"browser": Browser(), "multimodal": VLM(),
                   "llm": _LLM("ACTION: click('#missing')")}

    r = WebAgent(T()).browse("https://example.com", "click", max_steps=1)
    assert r["ok"] is False
    assert "动作执行失败" in r["error"]


def test_coder_pro_uses_approved_plan(monkeypatch, tmp_path):
    import core.code_agent as ca
    from modules.installed.coder_pro import CoderPro

    seen = {}

    class FakeAgent:
        def __init__(self, *a, **k): pass
        def run(self, goal, max_rounds=3):
            seen["goal"] = goal
            return {"ok": True}

    monkeypatch.setattr(ca, "CodeAgent", FakeAgent)

    class T:
        base = str(tmp_path)
        modules = {"llm": _LLM("计划原文")}
        def confirm_plan(self, plan, goal):
            return True, "用户编辑后的计划"

    r = CoderPro(T()).run_task("修 bug", plan_mode=True)
    assert r["ok"] is True
    assert "用户编辑后的计划" in seen["goal"]
    assert "修 bug" in seen["goal"]


def test_api_server_query_token_and_real_tasks(monkeypatch):
    import socket, time, urllib.request
    from modules.installed.api_server import ApiServer

    class Tasks:
        def create(self, goal): return {"id": "task_real_1", "status": "pending"}
        def start(self, task_id): return {"ok": True}
        def get_task(self, task_id): return {"id": task_id, "status": "completed"} if task_id == "task_real_1" else None

    class T:
        def get_task_runtime(self): return Tasks()
        def reply(self, msg): return "reply:" + msg

    monkeypatch.setattr(ApiServer, "_run_websocket", lambda self: None)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    a = ApiServer(T(), port=port)
    a.start()
    try:
        token = a.auth_token
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/?token=%s" % (port, token), timeout=3) as r:
            assert r.status == 200
        req = urllib.request.Request(
            "http://127.0.0.1:%d/v1/tasks?token=%s" % (port, token),
            data=b'{"goal":"do it"}', method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            import json
            body = json.loads(r.read())
            assert body["task_id"] == "task_real_1"
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/v1/tasks/task_real_1?token=%s" % (port, token),
                timeout=3) as r:
            import json
            assert json.loads(r.read())["status"] == "completed"
    finally:
        a.stop()


def test_multimodal_provider_shapes_keep_image():
    from core.llm_providers import _anthropic_messages, _gemini_contents
    from core.llm_local import LLMLocalMixin
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
    ]}]
    _, anth = _anthropic_messages(msgs)
    assert anth[0]["content"][1]["type"] == "image"
    _, gem = _gemini_contents(msgs)
    assert gem[0]["parts"][1]["inline_data"]["data"] == "AAAA"
    local = LLMLocalMixin._normalize_ollama_messages(msgs)
    assert local[0]["images"] == ["AAAA"]


def test_skills_market_bundled_catalog_and_hash():
    from core.skills_market import fetch_remote_catalog, download_skill
    r = fetch_remote_catalog()
    assert r["ok"] and r["skills"]
    d = download_skill(r["skills"][0]["name"])
    assert d["ok"] and os.path.isfile(d["zip_path"])


def test_mcp_catalog_validator_rejects_arbitrary_command():
    from gui.mcp_dialog import _valid_presets, DEFAULT_PRESETS
    assert _valid_presets(DEFAULT_PRESETS)
    assert not _valid_presets([{"name": "x", "cmd": "rm -rf /", "desc": "bad"}])
    assert not _valid_presets([{"name": "x", "desc": "missing cmd"}])


def test_swe_bench_missing_commit_is_skipped_not_false_pass():
    from tests.eval.swe_bench.runner import BenchmarkRunner, SAMPLE_CASES
    r = BenchmarkRunner(None).run_case(dict(SAMPLE_CASES[0]))
    assert r["passed"] is False
    assert r["status"] == "skipped"
    assert "commit_hash" in r["note"]


def test_skills_market_download_installs_into_registry(tmp_path):
    from core.skills_market import fetch_remote_catalog, download_skill
    from core.skill_registry import SkillRegistry

    class T:
        base = str(tmp_path)

    item = fetch_remote_catalog()["skills"][0]
    d = download_skill(item["name"], str(tmp_path))
    assert d["ok"]
    reg = SkillRegistry(T())
    r = reg.install_from_file(d["zip_path"])
    assert r["ok"]
    assert any(s["name"] == item["name"] for s in reg.list_all())


def test_web_console_entry_is_wired():
    from core.feature_registry import FEATURES
    from gui.mixins.ui_actions_mixin import UIActionsMixin
    assert FEATURES["web_console"].action == "open_web_console"
    assert callable(UIActionsMixin.open_web_console)
