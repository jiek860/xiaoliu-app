# -*- coding: utf-8 -*-
"""Child-process environment, cwd, Job Object and MCP output caps."""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.child_process import minimal_child_env, sandbox_cwd  # noqa: E402
from core.mcp_stdio import StdioMCPServer  # noqa: E402
from core.windows_job import WindowsJob, available as job_available  # noqa: E402


def test_minimal_env_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "also-secret")
    env = minimal_child_env()
    assert "OPENAI_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_mcp_cwd_is_contained(tmp_path):
    cwd = sandbox_cwd(tmp_path, "server")
    assert os.path.isdir(cwd)
    assert os.path.realpath(cwd).startswith(
        os.path.realpath(str(tmp_path / "data" / "mcp")))
    assert sandbox_cwd(tmp_path, "server", cwd) == cwd
    try:
        sandbox_cwd(tmp_path, "server", str(tmp_path))
        assert False, "project root must be rejected"
    except ValueError:
        pass


def test_job_object_can_attach_and_terminate():
    if not job_available():
        return
    import subprocess
    job = WindowsJob(max_memory_mb=128, max_cpu_seconds=10,
                     max_processes=2, kill_on_close=True)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        result = job.attach(p.pid)
        assert result["ok"], result
        assert job.terminate()
        p.wait(timeout=5)
    finally:
        try:
            p.kill()
        except Exception:
            pass
        job.close()


def test_mcp_stdout_line_limit_terminates_child():
    script = os.path.join(BASE, "tests", "fake_flood_mcp.py")
    cmd = '"%s" "%s"' % (sys.executable, script)
    s = StdioMCPServer("flood", cmd, timeout=3, max_line_bytes=1024,
                       max_total_bytes=4096)
    try:
        assert s.start() is False
        assert "单行" in s.last_error or "总量" in s.last_error
    finally:
        s.stop()
