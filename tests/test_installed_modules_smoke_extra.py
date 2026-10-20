# -*- coding: utf-8 -*-
"""已安装模块批量烟测：构造 + 安全 run() 路径。

目的不是替代业务测试，而是把大量从未 import / 从未构造的模块先拉进
覆盖范围，再用后续专项测试补关键行为。
"""
import importlib
import json
import os
import sys
import threading

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.lazy_config import LAZY_MAP  # noqa: E402

# 这些模块的 run() 无参数时只返回状态/空结果，不发起危险动作。
SAFE_RUN = {
    "plugin_market.py", "browser.py", "memory_cards.py", "knowledge_qa.py",
    "hot_reload.py", "group_chat.py", "scheduler.py", "multimodal.py",
    "task_loop.py", "task_planner.py", "self_reflect.py", "smart_router.py",
    "file_upload.py", "cache.py", "forgetting_curve.py", "skill_capture.py",
    "image_ocr.py", "notes.py", "calendar.py", "todo.py", "translate.py",
    "tts.py", "weather.py", "personality.py", "anomaly_detector.py",
    "auto_updater.py", "error_lib.py", "group_parallel.py", "group_loop.py",
    "realtime_chat.py", "voice.py",
}


class _FakeTrunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = json.loads(
            (open(os.path.join(BASE, "config.default.json"),
                  encoding="utf-8")).read())
        self.modules = {}
        self.confirm_cb = None

    def _log(self, *_a, **_k):
        return None

    def _load_lazy(self, _name):
        return None

    def call(self, *_a, **_k):
        return {"ok": False, "error": "fake trunk"}

    def rule(self, _name, default=False):
        return default

    def confirm(self, *_a, **_k):
        return False

    def get_task_runtime(self):
        class RT:
            def subscribe(self, *_a, **_k):
                return None

            def list_tasks(self):
                return []

            def get_task(self, _task_id):
                return None

        return RT()


def _cases():
    seen = set()
    out = []
    for _name, val in LAZY_MAP.items():
        if not isinstance(val, (list, tuple)) or len(val) < 2:
            continue
        fname, cls = val[0], val[1]
        if fname in seen:
            continue
        seen.add(fname)
        # mcp_client 构造会连接默认 localhost MCP 服务，已有专门测试覆盖，
        # 不放进批量烟测，避免无网络环境等待超时。
        if fname in {"mcp_client"}:
            continue
        if os.path.isfile(os.path.join(BASE, "modules", "installed",
                                       fname + ".py")):
            out.append((fname, cls))
    return out


@pytest.mark.parametrize("fname,cls", _cases(), ids=lambda x: str(x))
def test_installed_module_constructs_and_safe_run(tmp_path, monkeypatch, fname, cls):
    # 禁止后台线程和真实网络；批量烟测只验证代码路径
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.setattr("requests.get",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("requests.post",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("http.client.HTTPConnection.connect",
                        lambda self: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("socket.create_connection",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("socket.socket.connect",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))

    mod = importlib.import_module("modules.installed." + fname)
    klass = getattr(mod, cls)
    if fname == "mcp_client.py":
        # 构造器默认会连 localhost:3742；烟测只验证构造和本地字段
        monkeypatch.setattr(klass, "reload_servers",
                            lambda self: {"ok": True, "servers": 0,
                                          "tools": 0, "errors": []})
    trunk = _FakeTrunk(tmp_path)
    obj = klass(trunk)
    assert obj is not None
    if fname in SAFE_RUN and hasattr(obj, "run"):
        result = obj.run()
        assert result is not None