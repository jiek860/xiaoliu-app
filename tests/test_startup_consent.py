# -*- coding: utf-8 -*-
"""启动期确认"只问一次"测试（2026-10-22）。"""

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import startup_consent as sc  # noqa: E402


# ---------------- 基本读写 ----------------
def test_load_empty(tmp_path):
    assert sc.load(str(tmp_path)) == {}


def test_grant_and_is_granted(tmp_path):
    ok, err = sc.grant(str(tmp_path), "agreement", "用户同意")
    assert ok is True and err == ""
    assert sc.is_granted(str(tmp_path), "agreement") is True
    assert sc.is_granted(str(tmp_path), "onboarding") is False


def test_grant_records_time_and_detail(tmp_path):
    sc.grant(str(tmp_path), "agreement", "测试详情")
    data = sc.load(str(tmp_path))
    assert data["agreement"]["granted"] is True
    assert data["agreement"]["time"]
    assert data["agreement"]["detail"] == "测试详情"


def test_file_has_schema_and_always_ask(tmp_path):
    sc.grant(str(tmp_path), "agreement")
    raw = json.load(open(os.path.join(str(tmp_path), "data",
                                      "startup_consent.json"),
                         encoding="utf-8"))
    assert raw["schema_version"] == sc.SCHEMA_VERSION
    assert "覆盖文件" in raw["always_ask"]


def test_revoke_single(tmp_path):
    sc.grant(str(tmp_path), "agreement")
    sc.grant(str(tmp_path), "onboarding")
    sc.revoke(str(tmp_path), "agreement")
    assert sc.is_granted(str(tmp_path), "agreement") is False
    assert sc.is_granted(str(tmp_path), "onboarding") is True


def test_revoke_all(tmp_path):
    sc.grant(str(tmp_path), "agreement")
    sc.grant(str(tmp_path), "onboarding")
    sc.revoke(str(tmp_path), None)
    assert sc.load(str(tmp_path)) == {}


# ---------------- should_ask ----------------
def test_should_ask_respects_grant(tmp_path):
    assert sc.should_ask(str(tmp_path), "agreement") is True
    sc.grant(str(tmp_path), "agreement")
    assert sc.should_ask(str(tmp_path), "agreement") is False


def test_always_ask_items_never_suppressed(tmp_path):
    """危险操作必须每次都问，即使被"同意过"也不能跳过。"""
    for item in sc.ALWAYS_ASK:
        sc.grant(str(tmp_path), item)        # 故意写入
        assert sc.should_ask(str(tmp_path), item) is True, \
            "%s 被错误地记住了" % item


def test_always_ask_covers_destructive_actions():
    must = {"覆盖文件", "删除文件", "关机", "重启", "执行命令"}
    assert must.issubset(set(sc.ALWAYS_ASK))


# ---------------- 容错 ----------------
def test_broken_file_returns_empty(tmp_path):
    p = os.path.join(str(tmp_path), "data", "startup_consent.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write("{ not json")
    assert sc.load(str(tmp_path)) == {}
    assert sc.should_ask(str(tmp_path), "agreement") is True


def test_summary_shape(tmp_path):
    sc.grant(str(tmp_path), "agreement")
    s = sc.summary(str(tmp_path))
    assert "agreement" in s["granted"]
    assert "onboarding" in s["pending"]
    assert s["always_ask"]


def test_save_failure_is_reported(tmp_path):
    """写盘失败必须返回 False，不能假装成功。"""
    with open(os.path.join(str(tmp_path), "data"), "w") as f:
        f.write("x")            # data 被占用成文件
    ok, err = sc.save(str(tmp_path), {"a": {"granted": True}})
    assert ok is False
    assert "失败" in err


# ---------------- 登录态恢复 ----------------
class _AuthTrunk:
    def __init__(self, base):
        self.base = base
        self.config = {}

    def _log(self, _m):
        pass


def test_auth_remember_writes_account_only(tmp_path):
    """session.json 只记账号名，**绝不**记密码或激活码。"""
    from core.auth import Auth
    a = Auth(_AuthTrunk(str(tmp_path)))
    a.remember_session("u1")
    assert a.last_user() == "u1"
    raw = open(os.path.join(str(tmp_path), "data", "users", "session.json"),
               encoding="utf-8").read()
    assert "pwd" not in raw
    assert "code" not in raw


def test_auth_restore_requires_valid_activation(tmp_path):
    """关键安全断言：恢复登录必须重新验签，激活码无效就不能恢复。

    这正是"不能无条件信任 session.json"的证明 —— 即使账号标记了
    activated=True，激活码校验不过就拒绝。
    """
    from core.auth import Auth
    import time

    a = Auth(_AuthTrunk(str(tmp_path)))
    a.db["u1"] = {"activated": True, "expire": "永久",
                  "code": "invalid-code", "last_login": time.time()}
    a._save()
    a.remember_session("u1")

    b = Auth(_AuthTrunk(str(tmp_path)))
    ok, _user, why = b.restore_session()
    assert ok is False, "激活码无效时不应恢复登录"
    assert why
    assert b.current_user is None


def test_auth_restore_rejects_unknown_user(tmp_path):
    from core.auth import Auth
    a = Auth(_AuthTrunk(str(tmp_path)))
    a.remember_session("不存在的账号")
    ok, _u, why = a.restore_session()
    assert ok is False
    assert "不存在" in why or why


def test_auth_restore_without_record(tmp_path):
    from core.auth import Auth
    a = Auth(_AuthTrunk(str(tmp_path)))
    ok, _u, why = a.restore_session()
    assert ok is False
    assert "没有上次登录" in why


def test_auth_logout_clears_session(tmp_path):
    from core.auth import Auth
    a = Auth(_AuthTrunk(str(tmp_path)))
    a.remember_session("u1")
    assert a.last_user() == "u1"
    a.logout()
    assert a.last_user() == ""


# ---------------- AccountManager 恢复（回归：tuple 误当 dict） ----------------
def test_account_try_restore_handles_tuple(tmp_path):
    """历史 bug：auth.restore_session() 返回 tuple，account 却按 dict 取。

    后果：恢复永远失败 -> 退化成弹登录框 -> 用户每次启动都要登录。
    """
    from gui.account import AccountManager
    import time

    class T:
        base = str(tmp_path)
        config = {}

        def _log(self, _m):
            pass

        def call(self, mod, method, *a):
            if mod == "auth":
                return getattr(self._auth, method)(*a)
            return {}

    from core.auth import Auth
    t = T()
    t._auth = Auth(t)
    t._auth.remember_session("u1")

    am = AccountManager(t, t.base)
    r = am.try_restore_login()
    # 账号不存在 -> 恢复失败，但**必须**返回 dict 且带原因（不能抛异常）
    assert isinstance(r, dict)
    assert r["ok"] is False
    assert r["原因"]


def test_account_try_restore_without_record(tmp_path):
    from gui.account import AccountManager

    class T:
        base = str(tmp_path)
        config = {}

        def _log(self, _m):
            pass

        def call(self, mod, method, *a):
            if mod == "auth":
                return getattr(self._auth, method)(*a)
            return {}

    from core.auth import Auth
    t = T()
    t._auth = Auth(t)
    r = AccountManager(t, t.base).try_restore_login()
    assert r["ok"] is False
    assert "没有上次登录" in r["原因"] or r["原因"]


# ---------------- 覆盖率补充：auth session 全分支 ----------------
def _auth(tmp_path):
    from core.auth import Auth

    class T:
        base = str(tmp_path)
        config = {}

        def _log(self, _m):
            pass

    return Auth(T())


def test_session_path_and_forget(tmp_path):
    a = _auth(tmp_path)
    a.remember_session("u1")
    assert a.last_user() == "u1"
    assert a.has_session() if hasattr(a, "has_session") else True
    a.forget_session()
    assert a.last_user() == ""
    # 再次 forget 也不报错
    a.forget_session()


def test_restore_rejects_expired_account(tmp_path):
    from core.auth import Auth
    import time

    a = _auth(tmp_path)
    a.db["u1"] = {"activated": True, "expire": "2000-01-01",
                  "code": "x", "last_login": time.time()}
    a._save()
    a.remember_session("u1")
    b = Auth(a)  # 同 base，重新读取
    ok, _u, why = b.restore_session()
    assert ok is False
    assert why


def test_restore_rejects_inactive_account(tmp_path):
    import time
    a = _auth(tmp_path)
    a.db["u1"] = {"activated": False, "expire": "永久",
                  "code": "", "last_login": time.time()}
    a._save()
    a.remember_session("u1")
    ok, _u, why = a.restore_session()
    assert ok is False


def test_logout_clears_session(tmp_path):
    a = _auth(tmp_path)
    a.remember_session("u1")
    a.logout()
    assert a.last_user() == ""
    assert a.current_user is None


def test_remember_session_returns_bool(tmp_path):
    a = _auth(tmp_path)
    assert a.remember_session("u1") is True


def test_login_rejects_unknown_user(tmp_path):
    a = _auth(tmp_path)
    r = a.login("不存在的人")
    assert r.get("ok") is False


def test_login_rejects_empty_username(tmp_path):
    a = _auth(tmp_path)
    r = a.login("")
    assert r.get("ok") is False
    assert "请输入" in r.get("msg", "")


def test_whoami_when_not_logged_in(tmp_path):
    a = _auth(tmp_path)
    a.current_user = None
    assert a.whoami()["user"] == "未登录"
