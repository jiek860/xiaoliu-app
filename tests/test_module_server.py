# -*- coding: utf-8 -*-
"""模块仓库 HTTP 服务（core/module_server.py）

为什么补这个文件
----------------
工程化方案实测它 **0% 覆盖**（155 条语句）。它对外开一个 HTTP 端口
（8899），GUI 启动时自动内嵌启动 —— 也就是说：

    **用户机器上一直有个本地服务在跑，而它从没被验证过。**

它错了的后果不是"某个功能不好用"，而是"端口被占 / 请求打不开 /
路径能穿出去"。所以这个文件的重点是**真的起一个服务、真的发请求**
（用临时端口，不占 8899）。

本文件覆盖：
    · 清单读取（含被 BOM 破坏的清单、清单不存在）
    · 六个 HTTP 端点各自的行为（含 404）
    · **路径穿越**（`/modules/../../x.py`）能不能穿出去
    · 端口被占用时的报错
    · 启停幂等
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.module_server import ModuleServer        # noqa: E402


def _free_port():
    """要一个空闲端口 —— 测试不许占 8899（用户可能正开着程序）"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _make_repo(tmp_path, n=3):
    """造一个假模块仓库"""
    repo = tmp_path / "modules_repo"
    repo.mkdir(parents=True, exist_ok=True)
    mods = []
    for i in range(n):
        name = "mod%d" % i
        f = repo / ("%s.py" % name)
        f.write_text("# %s\nx = %d\n" % (name, i) + "# 填充\n" * 200,
                     encoding="utf-8")
        mods.append({
            "name": name, "file": "%s.py" % name,
            "class": "M%d" % i, "desc": "测试模块%d" % i,
            "group": "测试组", "version": "1.0",
            "needs_model": i % 2 == 0,
        })
    (repo / "manifest.json").write_text(
        json.dumps(mods, ensure_ascii=False), encoding="utf-8")
    return str(repo), mods


@pytest.fixture
def srv(tmp_path):
    """起一个真服务（临时端口），用完关掉"""
    repo, mods = _make_repo(tmp_path)
    s = ModuleServer(port=_free_port())
    s.repo_dir = repo
    s.manifest_path = os.path.join(repo, "manifest.json")
    msg = s.start()
    assert "已启动" in msg, "服务没起来：%s" % msg
    # 等它真的能接受连接（serve_forever 在后台线程里）
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:%d/api/health" % s.port, timeout=1).read()
            break
        except Exception:
            time.sleep(0.05)
    yield s, repo, mods
    s.stop()


def _get(s, path, timeout=5):
    """发一个 GET

    ⚠️ 路径里的中文必须先 percent-encode。`urlopen` 要求请求行是 ASCII，
    直接传中文会在**客户端**就抛 UnicodeEncodeError ——
    跟服务器一点关系都没有。第一版就是这么错的，看着像服务器崩了。
    """
    safe = urllib.parse.quote(path, safe="/%?&=:.")
    return urllib.request.urlopen(
        "http://127.0.0.1:%d%s" % (s.port, safe), timeout=timeout)


# ══════════════════════════════════════════════════════════════
# ① 清单
# ══════════════════════════════════════════════════════════════
def test_manifest_missing_returns_empty(tmp_path):
    s = ModuleServer(port=_free_port())
    s.repo_dir = str(tmp_path / "没有这个目录")
    s.manifest_path = os.path.join(s.repo_dir, "manifest.json")
    assert s.list_modules() == []


def test_manifest_broken_json_returns_empty(tmp_path):
    """清单坏了不能崩 —— 它只是"列个表"，不该把启动拦住"""
    repo = tmp_path / "modules_repo"
    repo.mkdir(parents=True)
    (repo / "manifest.json").write_text("{ 这不是 json", encoding="utf-8")
    s = ModuleServer(port=_free_port())
    s.repo_dir = str(repo)
    s.manifest_path = str(repo / "manifest.json")
    assert s.list_modules() == []


def test_manifest_with_bom_is_read(tmp_path):
    """⚠️ 带 BOM 的清单要能读

    这个清单是**要提交到 git、可能被记事本/PowerShell 编辑**的文件 ——
    那两个工具都爱加 BOM。原来用 utf-8 读会直接抛，
    表现是"模块列表空了"，很难查。
    """
    repo = tmp_path / "modules_repo"
    repo.mkdir(parents=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    data = json.dumps([{"name": "a", "file": "a.py"}], ensure_ascii=False)
    (repo / "manifest.json").write_bytes(b"\xef\xbb\xbf" + data.encode("utf-8"))
    s = ModuleServer(port=_free_port())
    s.repo_dir = str(repo)
    s.manifest_path = str(repo / "manifest.json")
    mods = s.list_modules()
    assert len(mods) == 1, "带 BOM 的清单没读出来：%s" % mods


def test_size_filled_from_disk(tmp_path):
    """size 要按**磁盘上的真实文件**算（清单里不存 size，省得对不上）"""
    repo, mods = _make_repo(tmp_path)
    s = ModuleServer(port=_free_port())
    s.repo_dir = repo
    s.manifest_path = os.path.join(repo, "manifest.json")
    for m in s.list_modules():
        assert m["size"] > 0, "%s 的 size 没填" % m["name"]


def test_missing_file_gives_zero_size(tmp_path):
    """清单里登记了但文件不在 -> size=0（不是崩）"""
    repo, mods = _make_repo(tmp_path)
    os.remove(os.path.join(repo, "mod0.py"))
    s = ModuleServer(port=_free_port())
    s.repo_dir = repo
    s.manifest_path = os.path.join(repo, "manifest.json")
    m = s.get_module("mod0")
    assert m is not None and m["size"] == 0, m


def test_get_module_not_found():
    s = ModuleServer(port=_free_port())
    s._manifest = []
    assert s.get_module("不存在的模块") is None


def test_refresh_rereads_manifest(tmp_path):
    """refresh 要真的重读（加装模块后不刷新列表就是旧的）"""
    repo, mods = _make_repo(tmp_path, n=2)
    s = ModuleServer(port=_free_port())
    s.repo_dir = repo
    s.manifest_path = os.path.join(repo, "manifest.json")
    assert len(s.list_modules()) == 2
    # 往清单里加一个
    data = json.load(open(s.manifest_path, encoding="utf-8"))
    data.append({"name": "新的", "file": "mod0.py"})
    open(s.manifest_path, "w", encoding="utf-8").write(
        json.dumps(data, ensure_ascii=False))
    assert len(s.list_modules()) == 2, "没刷新就读到了新的？缓存没生效"
    assert len(s.refresh()) == 3, "refresh 之后还是旧的"


# ══════════════════════════════════════════════════════════════
# ② HTTP 端点（真发请求）
# ══════════════════════════════════════════════════════════════
def test_health_endpoint(srv):
    s, repo, mods = srv
    d = json.loads(_get(s, "/api/health").read().decode("utf-8"))
    assert d["ok"] is True
    assert d["port"] == s.port


def test_api_modules_lists_all(srv):
    s, repo, mods = srv
    d = json.loads(_get(s, "/api/modules").read().decode("utf-8"))
    assert d["server"] == "ok"
    assert len(d["modules"]) == len(mods)
    assert {m["name"] for m in d["modules"]} == {m["name"] for m in mods}


def test_api_module_detail(srv):
    s, repo, mods = srv
    d = json.loads(_get(s, "/api/modules/mod0").read().decode("utf-8"))
    assert d["name"] == "mod0"
    assert d["class"] == "M0"


def test_api_module_404(srv):
    s, repo, mods = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(s, "/api/modules/没有这个")
    assert e.value.code == 404
    body = json.loads(e.value.read().decode("utf-8"))
    assert "不存在" in body["error"], body


def test_download_module_file(srv):
    """下载端点要真的把文件内容发出来"""
    s, repo, mods = srv
    body = _get(s, "/modules/mod0.py").read().decode("utf-8")
    assert "mod0" in body, body
    assert body.startswith("# mod0"), body


def test_download_unknown_module_404(srv):
    s, repo, mods = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(s, "/modules/不存在.py")
    assert e.value.code == 404


def test_index_page_renders(srv):
    """首页要出 HTML 且带上模块名（用户是拿浏览器打开它的）"""
    s, repo, mods = srv
    r = _get(s, "/")
    html = r.read().decode("utf-8")
    assert "html" in html.lower()
    assert "mod0" in html, "首页没列模块"
    assert "charset=utf-8" in r.headers.get("Content-Type", "").lower()


def test_unknown_path_404(srv):
    s, repo, mods = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(s, "/完全不知道的路径")
    assert e.value.code == 404


def test_json_is_utf8_not_escaped(srv):
    """中文描述不能被转成 \\uXXXX（用户和前端都直接读它）"""
    s, repo, mods = srv
    raw = _get(s, "/api/modules").read().decode("utf-8")
    assert "测试模块" in raw, "中文被转义了：%s" % raw[:200]


# ══════════════════════════════════════════════════════════════
# ③ 安全：路径穿越
# ══════════════════════════════════════════════════════════════
def test_path_traversal_is_refused(srv, tmp_path):
    """⚠️ **路径穿越必须挡住**

    这个服务对 127.0.0.1 开放 —— 本机任何程序（包括浏览器里的网页，
    通过 CSRF/DNS rebinding）都能请求它。如果 `/modules/../../某个文件.py`
    能读到仓库外的文件，那就是**任意文件读取**。

    现在的实现是"先查清单、清单里没有就 404"，所以穿越名天然查不到。
    这条测试钉住这个性质 —— 哪天有人改成"直接拼路径"，它会立刻红。
    """
    s, repo, mods = srv
    secret = tmp_path / "secret.py"
    secret.write_text("TOPSECRET = 1\n", encoding="utf-8")
    for evil in ("/modules/../secret.py",
                 "/modules/../../secret.py",
                 "/modules/..%2fsecret.py",
                 "/modules/%2e%2e%2fsecret.py",
                 "/api/modules/..%2f..%2fsecret.py"):
        try:
            body = _get(s, evil).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            assert e.code in (400, 404), "%s -> %s" % (evil, e.code)
            continue
        assert "TOPSECRET" not in body, \
            "**路径穿越成功了**：%s 读到了仓库外的文件" % evil


def test_only_localhost(monkeypatch, tmp_path):
    """服务只绑 127.0.0.1（不能听 0.0.0.0 —— 那等于对局域网开放）"""
    src = open(os.path.join(BASE, "core", "module_server.py"),
               encoding="utf-8").read()
    assert '("127.0.0.1"' in src or "('127.0.0.1'" in src, \
        "服务没绑 127.0.0.1 —— 检查一下是不是听所有网卡了"
    assert "0.0.0.0" not in src, "绑了 0.0.0.0（对局域网开放）"


# ══════════════════════════════════════════════════════════════
# ④ 启停
# ══════════════════════════════════════════════════════════════
def test_start_twice_is_refused(srv):
    s, repo, mods = srv
    assert "已在运行" in s.start()


def test_stop_is_idempotent(srv):
    s, repo, mods = srv
    s.stop()
    s.stop()                                   # 不许抛
    assert s.server is None


def test_port_in_use_reports_readably(tmp_path, monkeypatch):
    """⚠️ 端口被占时要给**能看懂**的话，不是抛异常

    8899 被占是很常见的（开了两个小6、或者别的程序占了）——
    用户看到"模块服务器启动失败: ..."至少知道怎么回事，
    而抛异常会让整个启动流程挂掉（它是启动时自动起的）。

    ⚠️ 为什么不用"起两个同端口服务"来造这个场景：
    **Windows 上 SO_REUSEADDR 允许重复绑同一个端口**，
    第二个也能起来 —— 那条路测不出来。（这是 Windows 和 Unix 的
    真实差异，不是 bug。）
    所以直接让 HTTPServer 构造时抛 OSError，模拟"端口被别的程序占了"。
    """
    import core.module_server as ms
    repo, mods = _make_repo(tmp_path)

    class Boom:
        def __init__(self, *a, **k):
            raise OSError(10048, "通常每个套接字地址只允许使用一次")

    monkeypatch.setattr(ms, "HTTPServer", Boom)
    s = ModuleServer(port=_free_port())
    s.repo_dir = repo
    s.manifest_path = os.path.join(repo, "manifest.json")
    msg = s.start()
    assert "已启动" not in msg, "绑不上竟然还报成功：%s" % msg
    assert "失败" in msg, msg
    assert s.server is None, "失败了却把 server 设上了"


def test_is_running(srv):
    s, repo, mods = srv
    assert s.is_running() is True
    s.stop()
    assert s.is_running() is False


def test_search_modules(srv):
    s, repo, mods = srv
    r = s.search_modules("mod1")
    assert r["找到"] == 1, r
    assert r["结果"][0]["name"] == "mod1"
    assert s.search_modules("完全不相干")["找到"] == 0


def test_module_stats(srv):
    s, repo, mods = srv
    st = s.get_module_stats()
    assert st["模块总数"] == len(mods), st
    assert st["总大小KB"] > 0, st
