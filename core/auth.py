# -*- coding: utf-8 -*-
"""账号系统 v12.0 - 免注册 + 激活码（对接 激活码生成器 v3.x）+ 账号隔离
- 不需要注册：用户自己起一个账号名即可
- 必须凭合法激活码（HMAC 短码 / RSA 长码）激活后才能登录使用
- 去掉了原来的 1/2/3 级权限
- 每个账号独立目录：data/users/<账号>/，聊天记录互相隔离
- 一个激活码只能激活一个账号
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json, time, shutil


class Auth:
    def __init__(self, trunk=None):
        self.trunk = trunk
        base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.base = base
        self.data_dir = os.path.join(base, "data", "users")
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "users.json")
        self.db = self._load()
        self.current_user = None
        try:
            from core.team_policy import TeamStore
            self.team = TeamStore(base)
        except Exception:
            self.team = None
        # 加载激活码校验资产
        self._secret = None
        self._pub = None
        self._app_version = "0.0"
        self._load_license_assets()

    # ---------- 持久化 ----------
    def _load(self):
        if os.path.exists(self.db_path):
            try:
                raw = json.load(open(self.db_path, "r", encoding="utf-8"))
                if isinstance(raw, dict):
                    cleaned = {}
                    for u, d in raw.items():
                        if isinstance(d, dict) and "pwd" not in d:
                            cleaned[u] = d
                    if len(cleaned) != len(raw):
                        try:
                            shutil.copy2(self.db_path, self.db_path + ".legacy_bak")
                        except Exception as e:
                            _x6_swallowed(__name__, e)
                            pass
                    return cleaned
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return {}

    def _save(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.db, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def _load_license_assets(self):
        """加载激活校验资产。

        - HMAC 共享密钥：只读查找（环境变量 → 密钥库 ~/.xiao6-keys → 程序内 core/密钥.key）。
          发布包不应携带 密钥.key，找不到时 HMAC 码不可用，RSA 码仍可用。
        - RSA 验签公钥：core/激活公钥.pem（兼容旧的 core/公钥.pem）。
          注意 core/公钥.pem 是更新包签名公钥，与激活密钥对不是同一把。
        """
        try:
            from core import license_core as lc
        except Exception:
            lc = None
        self._secret = lc.find_license_secret() if lc else None
        self._pub = lc.load_activation_pubkey(self.base) if lc else None
        try:
            from core.version import get_version
            self._app_version = get_version().lstrip("vV")
        except Exception:
            self._app_version = "0.0"

    def _verify_code(self, code):
        """调 license_core 校验激活码。返回 (ok, msg, info_dict)。"""
        try:
            from core import license_core as lc
        except Exception as e:
            return False, "校验模块加载失败: %s" % e, {}
        code = (code or "").strip()
        if not code:
            return False, "请输入激活码/密钥", {}
        try:
            raw = lc.parse_code(code)
        except Exception as e:
            return False, "激活码格式错误: %s" % e, {}
        try:
            mc = lc.get_machine_code()
        except Exception:
            mc = None
        # 根据码长度选 key：HMAC 短码用共享密钥；RSA 长码用激活公钥
        try:
            if len(raw) == lc.PAYLOAD_SIZE + 6:
                if not self._secret:
                    return False, ("本版本不含 HMAC 密钥（共享密钥不随程序分发），"
                                   "请使用 RSA 激活码/授权文件"), {}
                r = lc.verify_license(code, self._secret, machine_code=mc,
                                      app_version=self._app_version)
            elif len(raw) == lc.PAYLOAD_SIZE + 256:
                if not self._pub:
                    return False, ("RSA 公钥缺失（core/%s），或未安装 cryptography"
                                   % lc.ACT_PUB_FILE), {}
                r = lc.verify_license(code, self._pub, machine_code=mc,
                                      app_version=self._app_version)
            else:
                return False, "激活码长度不合法", {}
        except Exception as e:
            return False, "激活码校验异常: %s" % e, {}
        if not r.get("valid"):
            return False, r.get("reason", "激活码无效"), {}
        return True, "ok", r

    def _used_codes(self):
        """所有账号已用过的激活码集合"""
        used = set()
        for _u, d in self.db.items():
            c = d.get("code")
            if c:
                used.add(c.strip().upper())
        return used

    def _ensure_user_dir(self, username):
        user_dir = os.path.join(self.data_dir, username)
        os.makedirs(os.path.join(user_dir, "chat"), exist_ok=True)
        os.makedirs(os.path.join(user_dir, "memory"), exist_ok=True)
        return user_dir

    def _ensure_team_user(self, username):
        """Keep the license account and team RBAC record in sync."""
        if self.team is None:
            return
        try:
            if username not in self.team.users:
                self.team.add_user(username, username, "viewer", requester="local")
        except Exception:  # 静默是故意的
            pass

    # ---------- 对外接口 ----------
    def activate(self, username, code):
        """用激活码激活账号。账号名任意，激活码必须合法且未被用过。"""
        username = (username or "").strip()
        code = (code or "").strip()
        if not username:
            return {"ok": False, "msg": "请输入账号名"}
        if len(username) < 2:
            return {"ok": False, "msg": "账号名至少 2 个字符"}
        if any(ch in username for ch in r'\/:*?"<>|'):
            return {"ok": False, "msg": "账号名不能包含 \\ / : * ? \" < > | 这些字符"}
        if not code:
            return {"ok": False, "msg": "请输入激活码/密钥"}
        # 一个码只能激活一个账号
        if code.upper() in self._used_codes():
            return {"ok": False, "msg": "该激活码已被使用"}
        ok, msg, info = self._verify_code(code)
        if not ok:
            return {"ok": False, "msg": msg}
        now = time.time()
        # BUG-16: 存储激活码时统一大写，避免大小写不一致
        code = code.upper()
        self.db[username] = {
            "activated": True,
            "code": code,
            "level": info.get("level", 0),
            "features": info.get("features", 0),
            "expire": info.get("expire", "永久"),
            "created": now,
            "activated_at": now,
            "last_login": 0,
        }
        self._ensure_user_dir(username)
        self._ensure_team_user(username)
        self._save()
        extra = ""
        if info.get("expire") and info["expire"] != "永久":
            extra = "（到期 %s）" % info["expire"]
        return {"ok": True, "msg": "账号 %s 激活成功%s" % (username, extra), "user": username}

    def login(self, username):
        """登录：只认账号名，且必须已激活、未过期。"""
        username = (username or "").strip()
        if not username:
            return {"ok": False, "msg": "请输入账号名"}
        if username not in self.db:
            return {"ok": False, "msg": "账号不存在，请先激活"}
        d = self.db[username]
        if not d.get("activated"):
            return {"ok": False, "msg": "账号未激活，请先点「激活」输入激活码"}
        # 登录时重新验签，不能只信任 users.json 里可被本地编辑的 activated 布尔值。
        code = str(d.get("code") or "")
        ok, why, _info = self._verify_code(code)
        if not ok:
            return {"ok": False,
                    "msg": "授权校验失败，请重新激活：" + str(why)[:80]}
        # 过期检查
        exp = d.get("expire")
        if exp and exp != "永久":
            try:
                from datetime import date
                if date.today() > date.fromisoformat(str(exp)):
                    return {"ok": False, "msg": "账号已过期（%s）" % exp}
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        self._ensure_team_user(username)
        if self.team is not None:
            team_user = self.team.users.get(username) or {}
            if team_user.get("disabled"):
                return {"ok": False, "msg": "该团队账号已被管理员禁用"}
        self.current_user = username
        d["last_login"] = time.time()
        self._ensure_user_dir(username)
        self._save()
        self.remember_session(username)      # 下次启动自动恢复
        role = (self.team.users.get(username, {}) if self.team else {}).get(
            "role", "viewer")
        return {"ok": True, "user": username, "role": role}

    def logout(self):
        self.current_user = None
        try:
            path = os.path.join(os.path.dirname(self.db_path), "session.json")
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:  # 静默是故意的 - 删不掉也不影响退出
            _x6_swallowed(__name__, e)
        return {"ok": True}

    # ---------------------------------------------------------- 记住登录态
    def _session_path(self):
        return os.path.join(os.path.dirname(self.db_path), "session.json")

    def remember_session(self, username):
        """把"当前登录用户"记到磁盘，下次启动自动恢复。

        安全说明：
          * 只存账号名，**不存密码/激活码**（激活码仍在 users.json 里验签）；
          * 恢复时必须重新走 login() 的完整校验（激活状态、验签、过期、
            团队禁用），任何一步失败都回到未登录 —— 不是"无条件信任"；
          * 文件放在 data/users/ 下，与 users.json 同目录。
        """
        try:
            path = self._session_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"last_user": str(username or ""),
                           "time": time.strftime("%Y-%m-%d %H:%M:%S")},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except OSError as e:
            _x6_swallowed(__name__, e)
            return False

    def last_user(self):
        """读取上次登录的账号名（不做任何信任判断）。"""
        try:
            with open(self._session_path(), encoding="utf-8") as f:
                return str(json.load(f).get("last_user") or "")
        except (OSError, ValueError, AttributeError):
            return ""

    def restore_session(self):
        """启动时尝试恢复上次登录。返回 (ok, user, reason)。

        ⚠️ 必须走 login() 重新校验，不能直接把 current_user 设成账号名。
        """
        user = self.last_user()
        if not user:
            return False, "", "没有上次登录记录"
        r = self.login(user)
        if r.get("ok"):
            return True, user, ""
        return False, user, str(r.get("msg") or "恢复登录失败")

    def forget_session(self):
        """退出登录 / 撤销自动登录。"""
        try:
            path = self._session_path()
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            _x6_swallowed(__name__, e)
        self.current_user = None
        return {"ok": True}

    def whoami(self):
        if not self.current_user:
            return {"user": "未登录", "activated": False}
        role = (self.team.users.get(self.current_user, {}) if self.team else {}).get(
            "role", "viewer")
        return {"user": self.current_user, "activated": True, "role": role}

    def has_permission(self, permission):
        if not self.current_user or self.team is None:
            return False
        return bool(self.team.check(self.current_user, permission).get("ok"))

    def level_name(self):
        """兼容旧调用：不再有等级，直接返回账号名。"""
        if not self.current_user:
            return "未登录"
        return self.current_user

    def list_users(self):
        return {u: {"activated": bool(d.get("activated"))} for u, d in self.db.items()}

    def user_dir(self, username=None):
        u = username or self.current_user
        if not u:
            return None
        return os.path.join(self.data_dir, u)

    def run(self):
        return {
            "当前用户": self.whoami(),
            "总用户数": len(self.db),
            "已激活用户": [u for u, d in self.db.items() if d.get("activated")],
        }
