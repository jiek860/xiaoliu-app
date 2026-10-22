# -*- coding: utf-8 -*-
"""界面与后台小 bug 的回归测试（2026-10-22 巡检）。"""

import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


# ---------------- 本地模型请求被网络守卫误拒 ----------------
def test_is_local_target_variants():
    from core.llm_cloud import _is_local_target
    # 127.0.0.1 / localhost / ::1 之间写法不同，都必须判为本地
    assert _is_local_target("http://127.0.0.1:11434/v1/chat",
                            "http://localhost:11434") is True
    assert _is_local_target("http://localhost:11434/v1/chat",
                            "http://127.0.0.1:11434") is True
    assert _is_local_target("http://[::1]:11434/v1/chat",
                            "http://127.0.0.1:11434") is True
    # 公网地址不能误判为本地
    assert _is_local_target("https://api.deepseek.com/v1/chat",
                            "http://127.0.0.1:11434") is False
    # 云端 base_url 自身仍应被识别（用于 purpose 选择）
    assert _is_local_target("https://dashscope.aliyuncs.com/x",
                            "https://dashscope.aliyuncs.com") is True


def test_local_model_passes_net_guard():
    """回归：本地 Ollama 的 purpose 必须是 local_model，否则回环被拒。"""
    from core.net_guard import get_net_guard
    g = get_net_guard(None)
    for url in ("http://127.0.0.1:11434/api/tags",
                "http://localhost:11434/api/tags"):
        d = g.check(url, module="llm_client", purpose="local_model")
        assert d.get("allow") is True, "%s 被拒绝: %s" % (url, d.get("reason"))


def test_loopback_rejected_for_plain_network_purpose():
    """非本地用途访问回环仍然拒绝（安全边界不能被放开）。"""
    from core.net_guard import get_net_guard
    d = get_net_guard(None).check("http://127.0.0.1:11434/api/tags",
                                  module="x", purpose="network")
    assert d.get("allow") is False


# ---------------- 窗口重复打开 ----------------
def test_all_dialog_entries_have_reuse_or_modal():
    """所有 _dialog 入口要么走单例，要么是模态（exec_）——不能每次新建。"""
    import ast
    src = open(os.path.join(BASE, "gui", "mixins", "dialog_mixin.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.endswith("_dialog") or node.name.startswith("_"):
            continue
        body = ast.unparse(node)
        if any(k in body for k in ("_singleton", "_dialog_cache",
                                   "_dlg(", "exec_()")):
            continue
        if ".show()" in body:
            bad.append(node.name)
    assert not bad, "这些入口连点会开多个窗口: %s" % bad


# ---------------- 后台线程与定时器 ----------------
def test_trunk_warmup_timer_is_daemon():
    src = open(os.path.join(BASE, "core", "trunk_background.py"),
               encoding="utf-8").read()
    assert "threading.Timer" in src
    assert ".daemon = True" in src, "Timer 必须显式设 daemon"


def test_main_window_close_event_stops_timers():
    src = open(os.path.join(BASE, "gui", "main_window.py"),
               encoding="utf-8").read()
    assert "def closeEvent" in src
    for timer in ("_activity_timer", "_proactive_timer", "_status_timer"):
        assert timer in src
    assert "shutdown" in src, "关闭时应通知 trunk 收尾"


# ---------------- 虚拟机连物理机的大模型 ----------------
class _LanTrunk:
    def __init__(self, hosts):
        self.config = {"security": {"allow_lan_hosts": list(hosts)},
                       "ollama_url": "http://192.168.1.2:11434"}


def test_lan_host_must_be_explicitly_trusted():
    """私有地址默认拒绝；只有写进白名单才放行。"""
    from core.net_guard import get_net_guard

    g_none = get_net_guard(_LanTrunk([]))
    d = g_none.check("http://192.168.1.2:11434/api/tags",
                     module="llm_client", purpose="local_model")
    assert d.get("allow") is False, "未声明的局域网地址不能放行"

    g_ok = get_net_guard(_LanTrunk(["192.168.1.2:11434"]))
    d2 = g_ok.check("http://192.168.1.2:11434/api/tags",
                    module="llm_client", purpose="local_model")
    assert d2.get("allow") is True, "已声明的局域网地址应放行"


def test_lan_whitelist_is_port_sensitive():
    """写了端口就只放行该端口。"""
    from core.net_guard import get_net_guard
    g = get_net_guard(_LanTrunk(["192.168.1.2:11434"]))
    assert g.check("http://192.168.1.2:11434/api/tags",
                   module="x", purpose="local_model").get("allow") is True
    assert g.check("http://192.168.1.2:8080/x",
                   module="x", purpose="local_model").get("allow") is False


def test_lan_whitelist_without_port_allows_any_port():
    from core.net_guard import get_net_guard
    g = get_net_guard(_LanTrunk(["192.168.1.2"]))
    assert g.check("http://192.168.1.2:11434/x",
                   module="x", purpose="local_model").get("allow") is True
    assert g.check("http://192.168.1.2:9000/x",
                   module="x", purpose="local_model").get("allow") is True


def test_lan_host_not_allowed_for_generic_network():
    """白名单只对本地模型/MCP 生效，不能变成"任意访问内网"。"""
    from core.net_guard import get_net_guard
    g = get_net_guard(_LanTrunk(["192.168.1.2:11434"]))
    d = g.check("http://192.168.1.2:11434/api/tags",
                module="x", purpose="network")
    assert d.get("allow") is False


def test_other_lan_ip_still_blocked():
    from core.net_guard import get_net_guard
    g = get_net_guard(_LanTrunk(["192.168.1.2:11434"]))
    d = g.check("http://192.168.1.99:11434/api/tags",
                module="x", purpose="local_model")
    assert d.get("allow") is False


def test_local_model_purpose_detects_configured_host():
    """按配置的 ollama_url 主机判断 purpose，而不是靠字符串前缀。"""
    from core.llm_cloud import local_model_purpose

    class T:
        config = {"ollama_url": "http://192.168.1.2:11434"}

    assert local_model_purpose(T(), "http://192.168.1.2:11434/v1/chat") == "local_model"
    assert local_model_purpose(T(), "http://127.0.0.1:11434/v1/chat") == "local_model"
    assert local_model_purpose(T(), "https://api.deepseek.com/v1/chat") == "cloud_model"


# ---------------- 局域网信任配置 ----------------
def test_entry_of_extracts_host_and_port():
    from core.lan_trust import entry_of
    assert entry_of("http://192.168.1.2:11434") == "192.168.1.2:11434"
    assert entry_of("http://localhost:11434/api") == "localhost:11434"
    assert entry_of("http://192.168.1.2") == "192.168.1.2"
    assert entry_of("") == ""


def test_trust_host_writes_and_reports_failure():
    from core.lan_trust import trust_host, current_hosts

    class Ok:
        def __init__(self):
            self.config = {"ollama_url": "http://192.168.1.2:11434",
                           "security": {}}

        def save_config(self):
            return True

    t = Ok()
    ok, msg = trust_host(t)
    assert ok is True and "192.168.1.2:11434" in msg
    assert "192.168.1.2:11434" in current_hosts(t)

    class Bad(Ok):
        def save_config(self):
            return False          # 写盘失败

    ok2, msg2 = trust_host(Bad())
    assert ok2 is False, "写盘失败必须返回 False，不能假装成功"
    assert "失败" in msg2


def test_trust_then_net_guard_allows():
    """端到端：信任后网络守卫必须放行该主机。"""
    from core.lan_trust import trust_host
    from core.net_guard import get_net_guard

    class T:
        def __init__(self):
            self.config = {"ollama_url": "http://192.168.1.2:11434",
                           "security": {}}

        def save_config(self):
            return True

    t = T()
    g0 = get_net_guard(t)
    assert g0.check("http://192.168.1.2:11434/api/tags",
                    module="x", purpose="local_model").get("allow") is False
    trust_host(t)
    g1 = get_net_guard(t)
    assert g1.check("http://192.168.1.2:11434/api/tags",
                    module="x", purpose="local_model").get("allow") is True


# ---------------- 放行整个局域网 ----------------
class _CidrTrunk:
    def __init__(self, cidrs, hosts=None):
        self.config = {"security": {"allow_lan_cidrs": list(cidrs),
                                    "allow_lan_hosts": list(hosts or [])},
                       "ollama_url": "http://192.168.1.2:11434"}


def test_lan_cidr_allows_whole_subnet():
    from core.net_guard import get_net_guard
    g = get_net_guard(_CidrTrunk(["192.168.0.0/16"]))
    for host in ("192.168.1.2", "192.168.1.50", "192.168.10.5", "192.168.255.1"):
        d = g.check("http://%s:11434/api/tags" % host,
                    module="x", purpose="local_model")
        assert d.get("allow") is True, "%s 应被放行" % host


def test_lan_cidr_covers_common_private_ranges():
    from core.net_guard import get_net_guard
    g = get_net_guard(_CidrTrunk(["10.0.0.0/8", "172.16.0.0/12"]))
    assert g.check("http://10.1.2.3:11434/x", module="x",
                   purpose="local_model").get("allow") is True
    assert g.check("http://172.20.1.1:11434/x", module="x",
                   purpose="local_model").get("allow") is True


def test_public_ip_still_blocked_even_with_cidr():
    """关键安全断言：网段放行不能变成"放行公网"。"""
    from core.net_guard import get_net_guard
    g = get_net_guard(_CidrTrunk(["192.168.0.0/16"]))
    for url in ("http://8.8.8.8:11434/x", "http://1.1.1.1/x"):
        d = g.check(url, module="x", purpose="local_model")
        assert d.get("allow") is False, "%s 是公网，必须拒绝" % url


def test_cidr_does_not_open_generic_network_purpose():
    from core.net_guard import get_net_guard
    g = get_net_guard(_CidrTrunk(["192.168.0.0/16"]))
    d = g.check("http://192.168.1.2:11434/api/tags",
                module="x", purpose="network")
    assert d.get("allow") is False


def test_cidr_and_hosts_are_union():
    """网段与精确主机是或关系。"""
    from core.net_guard import get_net_guard
    g = get_net_guard(_CidrTrunk(["10.0.0.0/8"], ["192.168.1.2:11434"]))
    assert g.check("http://10.1.1.1:11434/x", module="x",
                   purpose="local_model").get("allow") is True
    assert g.check("http://192.168.1.2:11434/x", module="x",
                   purpose="local_model").get("allow") is True


def test_invalid_cidr_is_ignored():
    from core.net_guard import get_net_guard
    g = get_net_guard(_CidrTrunk(["not-a-cidr", "192.168.0.0/16"]))
    assert g.check("http://192.168.1.2:11434/x", module="x",
                   purpose="local_model").get("allow") is True


# ---------------- 覆盖率补充：lan_trust 全分支 ----------------
def test_lan_trust_full_lifecycle(tmp_path):
    from core import lan_trust as lt

    class T:
        def __init__(self):
            self.config = {"ollama_url": "http://192.168.1.2:11434",
                           "security": {}}
            self.saves = 0

        def save_config(self):
            self.saves += 1
            return True

    t = T()
    assert lt.current_hosts(t) == []
    assert "未信任" in lt.describe(t)

    ok, msg = lt.trust_host(t)
    assert ok and "192.168.1.2:11434" in msg
    assert t.saves == 1
    assert lt.current_hosts(t) == ["192.168.1.2:11434"]
    assert "已信任" in lt.describe(t)

    # 重复信任：不重复写
    ok2, msg2 = lt.trust_host(t)
    assert ok2 and "已在" in msg2
    assert t.saves == 1

    ok3, _ = lt.revoke_host(t, "192.168.1.2:11434")
    assert ok3 is True
    assert lt.current_hosts(t) == []


def test_lan_trust_invalid_url_and_no_config():
    from core import lan_trust as lt
    assert lt.entry_of("not-a-url") == ""
    assert lt.entry_of("http://") == ""

    class NoCfg:
        pass

    ok, msg = lt.trust_host(NoCfg())
    assert ok is False and "配置不可用" in msg


def test_lan_trust_entry_of_variants():
    from core.lan_trust import entry_of
    assert entry_of("http://192.168.1.2") == "192.168.1.2"
    assert entry_of("https://host:8443/path") == "host:8443"
    assert entry_of("http://[::1]:11434") == "::1:11434"


def test_lan_trust_exception_path():
    from core import lan_trust as lt

    class Boom:
        @property
        def config(self):
            raise RuntimeError("boom")

    # current_hosts 读不到时返回空，不抛
    assert lt.current_hosts(Boom()) == []


# ---------------- 覆盖率补充：net_guard.check 各分支 ----------------
class _GuardTrunk:
    def __init__(self, mode="standard", domains=None, cidrs=None):
        self.config = {"security": {"network_mode": mode,
                                    "allow_domains": list(domains or []),
                                    "allow_lan_cidrs": list(cidrs or []),
                                    "allow_lan_hosts": []}}


def _guard(**kw):
    from core.net_guard import get_net_guard
    return get_net_guard(_GuardTrunk(**kw))


def test_guard_rejects_non_http_scheme():
    d = _guard().check("ftp://example.com/x", module="x", purpose="network")
    assert d.get("allow") is False
    assert "协议" in str(d.get("reason"))


def test_guard_rejects_missing_host():
    d = _guard().check("http:///path", module="x", purpose="network")
    assert d.get("allow") is False


def test_guard_allows_allowlisted_domain():
    d = _guard(domains=["example.com"]).check(
        "https://example.com/x", module="x", purpose="network")
    assert d.get("allow") is True


def test_guard_rejects_unknown_domain():
    d = _guard().check("https://not-in-list.example/x",
                       module="x", purpose="network")
    assert d.get("allow") is False


def test_guard_rejects_metadata_address():
    d = _guard().check("http://169.254.169.254/latest/meta-data",
                       module="x", purpose="network")
    assert d.get("allow") is False


def test_guard_mode_off_allows_everything():
    d = _guard(mode="off").check("http://8.8.8.8/x", module="x",
                                 purpose="network")
    assert d.get("allow") is True


def test_guard_mode_learning_allows_after_private_check():
    d = _guard(mode="learning").check("https://random.example/x",
                                      module="x", purpose="network")
    assert d.get("allow") is True


def test_guard_default_domain_allowlist_works():
    """内置白名单里的域名应当直接放行。"""
    d = _guard().check("https://api.github.com/", module="x",
                       purpose="network")
    assert d.get("allow") is True


# ---------------- 覆盖率补充：llm_cloud._post 分支 ----------------
def _cloud_obj(config=None):
    from core.llm_cloud import LLMCloudMixin

    class Obj(LLMCloudMixin):
        def __init__(self):
            self.trunk = None
            self.config = config or {}
            self.base_url = "http://127.0.0.1:11434"
            self.logs = []

        def _log(self, m):
            self.logs.append(m)

    return Obj()


def test_post_allows_local_model(monkeypatch):
    import requests
    obj = _cloud_obj({"ollama_url": "http://127.0.0.1:11434"})
    called = {}

    def fake_post(url, **kw):
        called["url"] = url
        return "OK"

    monkeypatch.setattr(requests, "post", fake_post)
    assert obj._post("http://127.0.0.1:11434/v1/chat") == "OK"
    assert "url" in called


def test_post_rejects_unauthorized_public_host(monkeypatch):
    import requests
    obj = _cloud_obj({})
    monkeypatch.setattr(requests, "post", lambda *a, **k: "SHOULD-NOT-CALL")
    try:
        obj._post("https://evil.example.com/x")
        assert False, "应被拒绝"
    except PermissionError as e:
        # 具体理由可能是"域名不在允许列表"/"私有地址"等，统称被策略拦截
        assert str(e), "必须带上拒绝原因"


def test_post_allows_lan_model_after_trust():
    obj = _cloud_obj({"ollama_url": "http://192.168.1.2:11434",
                      "security": {"allow_lan_hosts": ["192.168.1.2:11434"]}})
    import core.net_guard as ng
    ng._CACHE.clear()
    # 只要能通过守卫检查就算成功（不真发请求）
    class T:
        config = obj.config
    obj.trunk = T()
    d = ng.get_net_guard(obj.trunk).check(
        "http://192.168.1.2:11434/v1/chat", module="llm_client",
        purpose="local_model")
    assert d.get("allow") is True
    ng._CACHE.clear()


def test_local_model_purpose_with_no_config():
    from core.llm_cloud import local_model_purpose

    class T:
        config = {}

    assert local_model_purpose(T(), "http://127.0.0.1:11434/x") == "local_model"
    assert local_model_purpose(T(), "https://x.example/y") == "cloud_model"
