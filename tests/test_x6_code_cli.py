# -*- coding: utf-8 -*-
"""无头代码 CLI 测试：假模型生成 patch，不落盘、不碰 GUI。"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core.patch_engine import PatchError  # noqa: E402
from tools.x6_code_cli import _git_diff, check, generate  # noqa: E402


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.config = {"model_mode": "云端模型", "cloud_model": "fake"}

    def chat(self, messages):
        self.calls.append(messages)
        return self.reply


def _repo(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8")
    return tmp_path


def _reply():
    return json.dumps({
        "files": [{
            "op": "update",
            "path": "pkg/calc.py",
            "hunks": [{"old": "    return a - b",
                       "new": "    return a + b"}],
        }]
    }, ensure_ascii=False)


def test_generate_patch_without_touching_repo(tmp_path):
    repo = _repo(tmp_path)
    fake = FakeLLM(_reply())
    result = generate(str(repo), "修复 add 的减号", llm=fake,
                      max_rounds=2, two_role=False)

    assert result["ok"] is True
    assert result["model_patch"].startswith(
        "diff --git a/pkg/calc.py b/pkg/calc.py")
    assert "--- a/pkg/calc.py" in result["model_patch"]
    assert "+++ b/pkg/calc.py" in result["model_patch"]
    assert "+    return a + b" in result["model_patch"]
    assert result["patch"]["files"][0]["path"] == "pkg/calc.py"
    # 只生成补丁，不落盘
    assert "return a - b" in (repo / "pkg" / "calc.py").read_text(
        encoding="utf-8")
    # 不往目标仓库写 trace
    assert not (repo / "data" / "agent_runs").exists()
    assert fake.calls


def test_generate_rejects_missing_repo(tmp_path):
    with pytest.raises(ValueError):
        generate(str(tmp_path / "nope"), "x", llm=FakeLLM(_reply()),
                 two_role=False)


def test_generate_rejects_empty_patch(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(PatchError):
        generate(str(repo), "x", llm=FakeLLM(json.dumps({"files": []})),
                 two_role=False)


def test_check_reports_missing_repo(tmp_path):
    result = check(str(tmp_path / "nope"), config_path=tmp_path / "cfg.json")
    assert result["ok"] is False
    names = [x["name"] for x in result["checks"] if not x["ok"]]
    assert "仓库目录" in names
    assert "配置文件" in names


def test_check_reads_config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "model_mode": "云端模型",
        "cloud_provider": "deepseek",
        "cloud_model": "deepseek-chat",
    }), encoding="utf-8")
    result = check(config_path=cfg)
    assert result["ok"] is True
    detail = [x["detail"] for x in result["checks"]
              if x["name"] == "模型配置"][0]
    assert "deepseek" in detail


def test_model_patch_applies_with_git(tmp_path):
    git = shutil.which("git")
    if not git:
        pytest.skip("没有 git，跳过 apply 校验")
    repo = _repo(tmp_path)
    for cmd in (["git", "init"], ["git", "config", "user.email", "x6@example.com"],
                ["git", "config", "user.name", "x6"], ["git", "add", "."],
                ["git", "commit", "-m", "init"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)

    result = generate(str(repo), "修复 add", llm=FakeLLM(_reply()),
                      two_role=False)
    patch_file = tmp_path / "model.patch"
    patch_file.write_text(result["model_patch"], encoding="utf-8")
    proc = subprocess.run([git, "apply", "--check", str(patch_file)],
                          cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_git_diff_create_file(tmp_path):
    patch = {
        "files": [{
            "op": "create",
            "path": "pkg/new.py",
            "content": "x = 1\n",
        }]
    }
    out = _git_diff(str(tmp_path), patch)
    assert out.startswith("diff --git a/pkg/new.py b/pkg/new.py")
    assert "new file mode 100644" in out
    assert "--- /dev/null" in out
    assert "+++ b/pkg/new.py" in out


# ══════════════════════════════════════════════════════════════
# SWE-bench Verified 驱动（B7/B11）：离线能验的部分
# ══════════════════════════════════════════════════════════════
import tools.swebench_verified as sb  # noqa: E402


def test_swebench_plan_is_offline_and_states_metric():
    data = sb.plan()
    assert data["count"] == 10
    assert len(set(data["ids"])) == 10
    assert "resolve_rate" in data["metric"]
    assert any("patch 为空" in n for n in data["notes"])


def test_swebench_reads_jsonl_and_requires_known_ids(tmp_path):
    ds = tmp_path / "ds.jsonl"
    ds.write_text(json.dumps({
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "修一下",
        "FAIL_TO_PASS": '["tests/test_a.py::test_x"]',
        "PASS_TO_PASS": "[]",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    got = sb.read_instances(str(ds))
    assert got[0]["instance_id"] == "django__django-11099"
    assert got[0]["FAIL_TO_PASS"] == ["tests/test_a.py::test_x"]
    assert sb.pick_instances(got, ["django__django-11099"])[0]["repo"] == \
        "django/django"
    with pytest.raises(SystemExit):
        sb.pick_instances(got, ["not__a-real-1"])


def test_swebench_predictions_keep_empty_patch_as_not_fixed(tmp_path,
                                                           monkeypatch):
    """没有 patch 也要写进 predictions（官方口径：没修好），并记进报告。"""
    inst = {"instance_id": "django__django-11099", "repo": "django/django",
            "base_commit": "abc", "problem_statement": "x",
            "FAIL_TO_PASS": [], "PASS_TO_PASS": []}
    monkeypatch.setattr(sb, "clone_at",
                        lambda repo, base, dest, timeout=0: Path(dest))
    monkeypatch.setattr(sb, "generate_patch",
                        lambda *a, **k: ("", "patch 为空"))
    out = tmp_path / "pred.jsonl"
    rows, records = sb.run_predictions([inst], tmp_path / "work", str(out),
                                       log=lambda *_: None)
    assert rows[0]["model_patch"] == ""
    assert records[0]["status"] == "empty_patch"
    saved = json.loads(out.read_text(encoding="utf-8").strip())
    assert saved["instance_id"] == "django__django-11099"
    assert saved["model_patch"] == ""
    md = sb.write_report(records, tmp_path / "r.md")
    assert "empty_patch" in md.read_text(encoding="utf-8")


def test_swebench_repo_error_is_recorded_not_skipped(tmp_path, monkeypatch):
    inst = {"instance_id": "sympy__sympy-20590", "repo": "sympy/sympy",
            "base_commit": "abc", "problem_statement": "x",
            "FAIL_TO_PASS": [], "PASS_TO_PASS": []}

    def _boom(*_a, **_k):
        raise RuntimeError("网络不通")

    monkeypatch.setattr(sb, "clone_at", _boom)
    rows, records = sb.run_predictions([inst], tmp_path / "work",
                                       str(tmp_path / "p.jsonl"),
                                       log=lambda *_: None)
    assert records[0]["status"] == "repo_error"
    assert "网络不通" in records[0]["error"]
    assert rows == []


def test_swebench_check_flags_missing_dataset():
    result = sb.check(dataset=None)
    assert result["ok"] is False
    bad = [x["name"] for x in result["checks"] if not x["ok"]]
    assert "数据集" in bad


def test_swebench_check_flags_low_disk(monkeypatch, tmp_path):
    """镜像很吃磁盘：剩余 < 20 GB 要直接报出来，而不是等构建时爆盘。"""
    monkeypatch.setattr(sb, "_docker_daemon", lambda: (True, "daemon 27.0"))
    monkeypatch.setattr(sb, "_tcp_ok", lambda *a, **k: True)

    class _Usage:
        total = 100 * 1024 ** 3
        used = 96 * 1024 ** 3
        free = 4 * 1024 ** 3

    monkeypatch.setattr(sb.shutil, "disk_usage", lambda _p: _Usage)
    result = sb.check(dataset=None, workdir=str(tmp_path / "w"))
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["磁盘"]["ok"] is False
    assert "4.0 GB" in by_name["磁盘"]["detail"]


def test_swebench_check_names_reachable_docker_mirrors(monkeypatch, tmp_path):
    """Hub 直连不通时，要说出哪个加速器可用（否则装了 Docker 也拉不到镜像）。"""
    monkeypatch.setattr(sb, "_docker_daemon", lambda: (False, "未安装"))

    def fake_tcp(host, port=443, timeout=2.0):
        return host == "docker.1ms.run"

    monkeypatch.setattr(sb, "_tcp_ok", fake_tcp)

    class _Usage:
        total = 100 * 1024 ** 3
        used = 40 * 1024 ** 3
        free = 60 * 1024 ** 3

    monkeypatch.setattr(sb.shutil, "disk_usage", lambda _p: _Usage)
    ds = tmp_path / "ds.jsonl"
    ds.write_text("{}\n", encoding="utf-8")
    result = sb.check(dataset=str(ds), workdir=str(tmp_path / "w"))
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["镜像加速"]["ok"] is True
    assert "docker.1ms.run" in by_name["镜像加速"]["detail"]
    assert "docker.nju.edu.cn" not in by_name["镜像加速"]["detail"]
    assert result["ok"] is False      # Docker 仍未装


def test_docker_daemon_reports_three_states(monkeypatch):
    """没 CLI / CLI 在但 daemon 没起 / daemon 正常，三种状态要能区分。"""
    monkeypatch.setattr(sb.shutil, "which", lambda _n: None)
    ok, detail = sb._docker_daemon()
    assert ok is False and "Docker" in detail

    monkeypatch.setattr(sb.shutil, "which", lambda _n: "docker")

    class _Down:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(sb.subprocess, "run", lambda *a, **k: _Down())
    ok, detail = sb._docker_daemon()
    assert ok is False and "daemon" in detail

    class _Up:
        returncode = 0
        stdout = "27.0.3\n"

    monkeypatch.setattr(sb.subprocess, "run", lambda *a, **k: _Up())
    ok, detail = sb._docker_daemon()
    assert ok is True and "27.0.3" in detail


def test_tcp_probe_swallows_network_errors(monkeypatch):
    """离线时探测要返回 False，不能把异常抛给自检。"""
    def boom(*_a, **_k):
        raise OSError("network unreachable")

    monkeypatch.setattr(sb.socket, "create_connection", boom)
    assert sb._tcp_ok("registry-1.docker.io") is False


def test_swebench_final_sample_is_reproducible_and_excludes_pilot():
    insts = [{"instance_id": "repo__x-%03d" % i} for i in range(120)]
    a = sb.sample_final(insts, 50)
    b = sb.sample_final(insts, 50)
    assert a == b
    assert len(a) == 50
    assert not set(a) & set(sb.PILOT_IDS)


def test_mirror_url_rewrites_github_and_can_be_disabled(monkeypatch):
    """GitHub 直连被重置时，clone 要能自动退到镜像。"""
    monkeypatch.setenv("X6_GIT_MIRROR", "https://ghfast.top/")
    assert sb.mirror_url("https://github.com/a/b.git") == \
        "https://ghfast.top/https://github.com/a/b.git"
    assert sb.mirror_url("https://gitlab.com/a/b.git") == \
        "https://gitlab.com/a/b.git"
    monkeypatch.setenv("X6_GIT_MIRROR", "")
    assert sb.mirror_url("https://github.com/a/b.git") == \
        "https://github.com/a/b.git"


def test_pilot_ids_all_exist_in_verified_dataset():
    """试跑清单里的 id 必须真在 Verified 子集里。

    B7 第一版有 4 个 id 是从别的榜单抄的，数据集里根本没有 ——
    实跑第一步就报"这些实例不在数据集里"。没有这条，错误要等跑起来才发现。
    """
    ds = BASE / "data" / "swebench" / "swebench_verified.jsonl"
    if not ds.exists():
        pytest.skip("本机没有下载 Verified 数据集")
    ids = set()
    for line in ds.read_text(encoding="utf-8").splitlines():
        try:
            ids.add(json.loads(line)["instance_id"])
        except Exception:
            continue
    missing = [x for x in sb.PILOT_IDS if x not in ids]
    assert not missing, "这些试跑 id 不在 Verified 数据集里：%s" % missing

