# -*- coding: utf-8 -*-
"""反馈日志摘要（core/log_digest）单元测试

要钉住三件事：
  1. 只发「系统信息 + 错误行 + 崩溃现场 + 日志路径」
  2. 密钥必须脱敏
  3. 截断时**日志路径不能被截掉**（用户要靠它定位）
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import log_digest  # noqa: E402


def _mk_logs(tmp_path, app_log="", faulthandler=""):
    d = tmp_path / "data" / "logs"
    d.mkdir(parents=True)
    (d / "app.log").write_text(app_log, encoding="utf-8")
    (d / "faulthandler.log").write_text(faulthandler, encoding="utf-8")
    return str(tmp_path)


def test_redact_masks_secrets():
    s = ("webhook=https://open.feishu.cn/open-apis/bot/v2/hook/fake-hook-123456\n"
         "key=abcd1234efgh5678\n"
         "Bearer abcdefghijklmnop\n"
         "sk-1234567890abcdef\n"
         "token: 40d0f4d2c8e64e0a9b7c5d3e1f2a6b8c")
    out = log_digest.redact(s)
    assert "fake-hook" not in out, out
    assert "abcd1234efgh5678" not in out, out
    assert "abcdefghijklmnop" not in out, out
    assert "1234567890abcdef" not in out, out
    assert "40d0f4d2c8e64e0a9b7c5d3e1f2a6b8c" not in out, out


def test_collect_only_error_lines(tmp_path):
    base = _mk_logs(
        tmp_path,
        app_log="[2026-10-18 22:00:00] [INFO] 一切正常\n"
                "[2026-10-18 22:00:01] [ERROR] [安全] 出错了: boom\n",
        faulthandler="Thread 0x0001 (most recent call first):\n"
                     "  File \"a.py\", line 1 in f\n")
    d = log_digest.collect(base)
    assert "boom" in d["text"]
    assert "一切正常" not in d["text"], "INFO 行不该被发出去"
    assert "Thread 0x0001" in d["text"], "崩溃现场没带上"
    assert d["logs_dir"] in d["text"], "日志路径没带上"
    assert any(f["name"] == "app.log" for f in d["files"])


def test_faulthandler_ignores_old_test_stack_after_latest_start(tmp_path):
    faulthandler = (
        "Current thread 0x0001 (most recent call first):\n"
        "  File \"tests/test_old.py\", line 1 in pytest_old\n"
        "\n" + "=" * 70 + "\n"
        "启动 2026-10-19 19:52:36  pid=17960  python=3.12.10\n"
        "工作目录 E:\\xiaoliu\n" + "=" * 70 + "\n"
    )
    base = _mk_logs(tmp_path, app_log="", faulthandler=faulthandler)
    text = log_digest.collect(base)["text"]
    assert "pytest_old" not in text, "旧测试栈不该被当成最近一次启动的崩溃现场"
    assert "最近没有错误" in text or "没有崩溃" in text


def test_collect_has_system_info(tmp_path):
    base = _mk_logs(tmp_path, app_log="")
    t = log_digest.collect(base)["text"]
    for k in ("系统:", "Python:", "小6版本:", "线程数:", "日志目录:"):
        assert k in t, "缺少系统信息: %s" % k


def test_truncate_keeps_paths(tmp_path):
    big = "".join("[ERROR] error line %d %s\n" % (i, "x" * 200)
                  for i in range(200))
    base = _mk_logs(tmp_path, app_log=big)
    d = log_digest.collect(base, max_chars=800)
    assert d["truncated"] is True
    assert "日志位置" in d["text"], "截断后日志位置丢了"
    assert d["logs_dir"] in d["text"]
    assert len(d["text"]) <= 1200, len(d["text"])
