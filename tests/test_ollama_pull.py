# -*- coding: utf-8 -*-
"""模型下载（Ollama /api/pull）的测试 —— 用**模拟服务**验解析

为什么用 mock 而不是连着真 Ollama
--------------------------------
① 本机 Ollama 装了没、在不在跑都不确定（实测这条机器上**没装**，
   但 Downloads 里躺着一个 1497.5 MB 的安装包）—— 测试不该依赖它。
② 真拉一个模型要 2GB、几分钟，放进测试套件不现实。
③ 这里要验的是**我的解析逻辑**（NDJSON 逐行读、进度算得对不对、
   取消能不能中断、错误能不能报出来），这些用 mock 能验得更彻底 ——
   可以精确构造"校验阶段没有 total""中途返回 error"这些真实环境
   很难复现的情况。

NDJSON 的格式依据是官方文档（不是猜的）：
    {"status":"pulling manifest"}
    {"status":"downloading","digest":"sha256:…","total":N,"completed":M}
    {"status":"verifying sha256 digest"}
    {"status":"writing manifest"}
    {"status":"success"}
出错时 {"error":"…"}
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core import ollama_installer as oi          # noqa: E402


class _FakeOllama(BaseHTTPRequestHandler):
    """按官方 NDJSON 格式吐数据的假 Ollama"""

    script = []           # [(延迟秒, 字典), ...]
    got_body = {}

    def do_POST(self):                                # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            _FakeOllama.got_body = json.loads(raw.decode("utf-8"))
        except Exception:
            _FakeOllama.got_body = {"_raw": raw[:80].decode("utf-8", "replace")}
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for delay, obj in self.script:
            if delay:
                time.sleep(delay)
            self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
            self.wfile.flush()

    def log_message(self, *a):
        pass                                          # 别刷屏


@pytest.fixture
def fake():
    """起一个假 Ollama，返回 (url, 设置脚本的函数)"""
    srv = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()

    def set_script(script):
        _FakeOllama.script = script

    yield "http://127.0.0.1:%d" % srv.server_address[1], set_script
    srv.shutdown()
    srv.server_close()


DL = {"status": "downloading", "digest": "sha256:abc",
      "total": 100 * 1048576, "completed": 0}


def test_pull_parses_progress_and_success(fake):
    """正常流程：能读到进度、能认到 success"""
    url, set_script = fake
    set_script([
        (0, {"status": "pulling manifest"}),
        (0, DL),
        (0, {"status": "downloading", "digest": "sha256:abc",
             "total": 100 * 1048576, "completed": 50 * 1048576}),
        (0, {"status": "downloading", "digest": "sha256:abc",
             "total": 100 * 1048576, "completed": 100 * 1048576}),
        (0, {"status": "verifying sha256 digest"}),
        (0, {"status": "writing manifest"}),
        (0, {"status": "success"}),
    ])
    calls = []
    r = oi.pull_model(url, "test:1b",
                      progress=lambda *a: calls.append(a))
    assert r.get("ok") is True, r
    assert r.get("模型") == "test:1b"
    assert calls, "一次进度回调都没有"
    # 状态文字要翻译成中文，别把英文原文甩给用户
    statuses = [c[0] for c in calls]
    assert any("正在读取清单" in s for s in statuses), statuses
    assert any("正在校验" in s for s in statuses), statuses
    # 有 total 的那几帧要算出百分比
    pcts = [c[3] for c in calls if c[3]]
    assert 100 in pcts, pcts


def test_pull_sends_correct_request_body(fake):
    """请求体必须是 {"name": 模型名, "stream": true}"""
    url, set_script = fake
    set_script([(0, {"status": "success"})])
    oi.pull_model(url, "qwen2.5:3b")
    assert _FakeOllama.got_body.get("name") == "qwen2.5:3b", _FakeOllama.got_body
    assert _FakeOllama.got_body.get("stream") is True, _FakeOllama.got_body


def test_pull_reports_error_field(fake):
    """Ollama 返回 {"error": ...} 时要如实报出来"""
    url, set_script = fake
    set_script([
        (0, {"status": "pulling manifest"}),
        (0, {"error": "model 'xxx' not found"}),
    ])
    r = oi.pull_model(url, "xxx")
    assert r.get("ok") is False, r
    assert "not found" in r.get("错误", ""), r


def test_pull_can_be_cancelled(fake):
    """取消要能真的中断（2GB 的下载不给取消就是个陷阱）"""
    url, set_script = fake
    set_script([
        (0, {"status": "pulling manifest"}),
        (0.05, DL),
        (0.05, {"status": "downloading", "digest": "x",
                "total": 100 * 1048576, "completed": 10 * 1048576}),
        (0.05, {"status": "success"}),
    ])
    flag = {"n": 0}

    def stop():
        flag["n"] += 1
        return flag["n"] > 2          # 读两行之后就取消

    r = oi.pull_model(url, "m", should_stop=stop)
    assert r.get("取消") is True, r
    assert r.get("ok") is False


def test_pull_survives_garbage_lines(fake):
    """中间夹了坏行/半行不能让整次下载失败"""
    url, set_script = fake
    set_script([
        (0, {"status": "pulling manifest"}),
        (0, "这不是 JSON"),                     # 字符串而不是 dict
        (0, {"status": "success"}),
    ])
    r = oi.pull_model(url, "m")
    assert r.get("ok") is True, r


def test_pull_handles_server_down():
    """Ollama 没在跑时要返回可读错误，不能抛"""
    r = oi.pull_model("http://127.0.0.1:1", "m", timeout=2)
    assert r.get("ok") is False
    assert r.get("错误"), r


def test_pull_without_success_status_is_flagged(fake):
    """流正常结束但没收到 success -> 不能说"完成"，要提示去重新检测

    （真环境里网络中断就会这样：连接断了但没报错，
      如果直接算成功，用户会以为下好了。）
    """
    url, set_script = fake
    set_script([
        (0, {"status": "pulling manifest"}),
        (0, DL),
    ])
    r = oi.pull_model(url, "m")
    assert "提示" in r, "没收到 success 却没给提示：%s" % r
    assert "重新检测" in r["提示"]


def test_status_translations_cover_documented_states():
    """官方文档里那几个状态都要有中文 —— 漏了就会把英文甩给用户"""
    for st in ("pulling manifest", "verifying sha256 digest",
               "writing manifest", "success"):
        assert st in oi.PULL_STATUS_CN, "缺状态翻译：%s" % st
        assert oi.PULL_STATUS_CN[st], st
