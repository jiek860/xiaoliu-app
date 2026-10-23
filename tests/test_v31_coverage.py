# -*- coding: utf-8 -*-
"""v3.1 覆盖测试：尽量走真实实现，避免只测复制出来的字符串。"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import zipfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.modules = {}


class _LLM:
    def __init__(self, answer="ok"):
        self.answer = answer
        self.calls = []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        return self.answer


def _mk_skill(base):
    cap = os.path.join(base, "data", "plugin_data", "skill_capture", "skills")
    os.makedirs(cap, exist_ok=True)
    path = os.path.join(cap, "demo.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\nname: demo\n---\nhello")
    return cap


def test_skill_registry_full_lifecycle(tmp_path):
    from core.skill_registry import SkillRegistry

    _mk_skill(str(tmp_path))
    reg = SkillRegistry(_Trunk(tmp_path))
    all_skills = reg.list_all()
    assert any(s["name"] == "demo" for s in all_skills)
    assert reg.load("demo")
    assert "demo" in reg.get_enabled_prompts()
    reg.disable("demo")
    assert reg.load("demo") is None
    reg.enable("demo")
    out = tmp_path / "demo.x6skill"
    assert reg.export_to_file("demo", str(out))["ok"]
    assert out.exists()
    other = SkillRegistry(_Trunk(tmp_path))
    assert other.install_from_file(str(out))["ok"]
    assert other.delete("demo")["ok"]


def test_skill_registry_integrity_and_bad_install(tmp_path):
    from core.skill_registry import SkillRegistry

    cap = _mk_skill(str(tmp_path))
    reg = SkillRegistry(_Trunk(tmp_path))
    path = os.path.join(cap, "demo.md")
    assert reg.list_all()[0]["verified"] is True
    with open(path, "a", encoding="utf-8") as f:
        f.write("tampered")
    assert reg.list_all()[0]["verified"] is False
    assert reg.install_from_file(str(tmp_path / "missing"))["ok"] is False
    bad = tmp_path / "bad.x6skill"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.txt", "x")
    assert reg.install_from_file(str(bad))["ok"] is False


def test_skills_market_bundled_and_validation(monkeypatch, tmp_path):
    import core.skills_market as sm

    assert sm._valid_catalog([{"name": "x", "title": "x", "desc": "x",
                               "sha256": "a", "local_path": "x"}])
    assert not sm._valid_catalog([{"name": "x"}])
    monkeypatch.setattr(sm.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    r = sm.fetch_remote_catalog()
    assert r["ok"] and r["source"] == "bundled"
    item = r["skills"][0]
    d = sm.download_skill(item["name"], str(tmp_path))
    assert d["ok"]
    assert sm.download_skill("does-not-exist", str(tmp_path))["ok"] is False


def test_web_agent_real_dom_action_loop(tmp_path):
    from modules.installed.web_agent import WebAgent

    img = tmp_path / "p.png"
    img.write_bytes(b"x")

    class Browser:
        def __init__(self): self.calls = []
        def open(self, url, headless=True): return {"ok": True}
        def screenshot(self, path=None): return {"ok": True, "截图": str(img)}
        def list_interactables(self): return {"ok": True, "元素": [{"tag": "button", "text": "提交"}]}
        def get_text(self): return {"文字": "页面文字"}
        def click(self, sel): self.calls.append(("click", sel)); return {"ok": True}
        def type_text(self, sel, text): self.calls.append(("type", sel, text)); return {"ok": True}
        def scroll(self, *a, **k): return {"ok": True}
        def back(self): return {"ok": True}
        def wait(self, *a, **k): return {"ok": True}

    class VLM:
        def describe_image(self, path): return {"描述": "页面截图"}

    class LLM:
        def __init__(self): self.n = 0
        def chat(self, prompt):
            self.n += 1
            return "ACTION: type('#q', 'hello')\n" if self.n == 1 else "ACTION: done"

    br = Browser()
    t = _Trunk(tmp_path)
    t.modules = {"browser": br, "multimodal": VLM(), "llm": LLM()}
    r = WebAgent(t).browse("https://example.com", "search", max_steps=2)
    assert r["ok"] is True
    assert br.calls == [("type", "#q", "hello")]


def test_web_agent_missing_and_failure(tmp_path):
    from modules.installed.web_agent import WebAgent
    assert WebAgent(_Trunk(tmp_path)).browse("https://x")["ok"] is False

    img = tmp_path / "p.png"; img.write_bytes(b"x")
    class B:
        def open(self, url, headless=True): return {"ok": True}
        def screenshot(self, path=None): return {"ok": True, "截图": str(img)}
        def click(self, sel): return {"错误": "missing"}
        def list_interactables(self): return {}
        def get_text(self): return {}
    class V:
        def describe_image(self, path): return {"描述": "page"}
    class L:
        def chat(self, prompt): return "ACTION: click('#bad')"
    t = _Trunk(tmp_path); t.modules = {"browser": B(), "multimodal": V(), "llm": L()}
    r = WebAgent(t).browse("https://x", "click", max_steps=1)
    assert r["ok"] is False and "动作执行失败" in r["error"]


def test_coder_pro_plan_and_reject(monkeypatch, tmp_path):
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
        modules = {"llm": _LLM("plan")}
        def confirm_plan(self, plan, goal): return True, "edited plan"
    r = CoderPro(T()).run_task("fix", plan_mode=True)
    assert r["ok"] and "edited plan" in seen["goal"]

    class Reject(T):
        def confirm_plan(self, plan, goal): return False, plan
    assert CoderPro(Reject()).run_task("fix", plan_mode=True)["ok"] is False
    assert CoderPro(T()).run_task("fix", project_path="no-such-dir")["ok"] is False


def test_api_server_http_contract(monkeypatch):
    from modules.installed.api_server import ApiServer

    class Tasks:
        def create(self, goal): return {"id": "t1", "status": "pending"}
        def start(self, tid): return {"ok": True}
        def get_task(self, tid):
            return {"id": tid, "status": "done"} if tid == "t1" else None
        def list_tasks(self): return [{"id": "t1", "status": "done"}]
    class T:
        def get_task_runtime(self): return Tasks()
        def reply(self, msg): return "reply:" + msg

    monkeypatch.setattr(ApiServer, "_run_websocket", lambda self: None)
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    srv = ApiServer(T(), port=port)
    info = srv.start(); token = srv.auth_token
    try:
        def call(path, data=None):
            req = urllib.request.Request(
                "http://127.0.0.1:%d%s" % (port, path),
                data=data, headers={"Authorization": "Bearer " + token,
                                    "Content-Type": "application/json"},
                method="POST" if data is not None else "GET")
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, r.read()
        assert call("/v1/health")[0] == 200
        assert call("/?token=" + token)[0] == 200
        assert call("/tasks?token=" + token)[0] == 200
        st, body = call("/v1/chat", b'{"message":"hi"}')
        assert st == 200 and b"reply:hi" in body
        st, body = call("/v1/tasks", b'{"goal":"x"}')
        assert st == 200 and b"t1" in body
        assert call("/v1/tasks/t1")[0] == 200
        try:
            call("/v1/tasks/nope")
            assert False, "missing task should be 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def test_mcp_catalog_validation():
    from gui.mcp_dialog import _valid_presets, DEFAULT_PRESETS
    assert _valid_presets(DEFAULT_PRESETS)
    assert not _valid_presets([{"name": "x", "cmd": "rm -rf /", "desc": "bad"}])
    assert not _valid_presets([{"name": "x", "desc": "missing cmd"}])


def test_multimodal_and_llm_chat_with_image(monkeypatch, tmp_path):
    from core.llm_client import LLMClient
    from core.llm_providers import _anthropic_messages, _gemini_contents
    from core.llm_local import LLMLocalMixin
    from modules.installed.multimodal import Multimodal

    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
    assert _anthropic_messages(msgs)[1][0]["content"][1]["type"] == "image"
    assert _gemini_contents(msgs)[1][0]["parts"][1]["inline_data"]["data"] == "AAAA"
    assert LLMLocalMixin._normalize_ollama_messages(msgs)[0]["images"] == ["AAAA"]

    class FakeLLM:
        def chat(self, messages, **kw):
            return "seen"
        def chat_with_image(self, prompt, image_base64=None):
            return "image:" + str(bool(image_base64))
    t = _Trunk(tmp_path); t.modules = {"llm": FakeLLM()}
    path = tmp_path / "a.png"; path.write_bytes(b"x")
    r = Multimodal(t).describe_image(str(path))
    assert r["描述"] == "image:True"
    obj = object.__new__(LLMClient)
    obj.chat = lambda messages: "ok"
    assert obj.chat_with_image("x", image_base64="AAAA") == "ok"
