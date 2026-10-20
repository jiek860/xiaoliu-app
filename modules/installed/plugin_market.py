# -*- coding: utf-8 -*-
"""插件市场 v1.0 - PluginMarket
真实现：扫描已安装模块 + 仓库模块，支持 安装/卸载/热加载。
- 已安装 = modules/installed 里的文件
- 仓库   = modules_repo 里的镜像
- 卸载    = 移到 data/plugin_backups + 从 lazy_config 移除注册
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from core.safe_http import open_url as safe_open_url
from modules.base import BaseModule
import os
import re
import json
import hashlib
import shutil

from core.path_safety import safe_join, safe_name
from core.plugin_api import (PLUGIN_API_VERSION, manifest_api_version,
                             validate_plugin_manifest,
                             validate_plugin_source)
from core.plugin_repository import (download_urls, manifest_entry_signed,
                                    remote_repo_urls, safe_plugin_filename)


def _icon_of(name):
    """按模块名猜图标"""
    m = str(name)
    if any(k in m for k in ["学习", "train", "learn", "训练"]):
        return "📚"
    if any(k in m for k in ["搜索", "search", "深"]):
        return "🔍"
    if any(k in m for k in ["记忆", "mem", "forget", "卡片"]):
        return "🧠"
    if any(k in m for k in ["任务", "task", "目标", "goal"]):
        return "🎯"
    if any(k in m for k in ["代码", "coder", "code", "编程", "执行", "runner"]):
        return "💻"
    if any(k in m for k in ["分析", "analyst", "reason", "因果", "推理"]):
        return "📊"
    if any(k in m for k in ["策划", "planner", "创意"]):
        return "🎨"
    if any(k in m for k in ["情感", "empathy", "共情", "偏好"]):
        return "💗"
    if any(k in m for k in ["远程", "remote", "mobile", "网络"]):
        return "🌐"
    if any(k in m for k in ["安全", "错误", "error", "异常"]):
        return "🛡️"
    if any(k in m for k in ["文件", "upload", "upload"]):
        return "📁"
    if any(k in m for k in ["语音", "voice", "音频"]):
        return "🎤"
    if any(k in m for k in ["定时", "sched", "时间"]):
        return "⏰"
    if any(k in m for k in ["更新", "update", "reload", "热"]):
        return "🔄"
    if any(k in m for k in ["路由", "route", "mcp", "agent"]):
        return "🧩"
    if any(k in m for k in ["知识", "rag", "graph", "图谱"]):
        return "📖"
    return "🧩"
class PluginMarket(BaseModule):
    NAME = "plugin_market"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = trunk.base if trunk else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.installed_dir = os.path.join(self.base, "modules", "installed")
        self.repo_dir = os.path.join(self.base, "modules_repo")
        self.backup_dir = os.path.join(self.base, "data", "plugin_backups")
        os.makedirs(self.backup_dir, exist_ok=True)
    # ---------- 扫描 ----------
    def _doc_of(self, file_path):
        try:
            t = open(file_path, encoding="utf-8", errors="ignore").read(4000)
            m = re.search(r'"""(.*?)"""', t, re.S)
            if m:
                lines = [x.strip() for x in m.group(1).splitlines() if x.strip()]
                return lines[0][:60] if lines else ""
            # 类注释
            m2 = re.search(r'^class\s+\w+.*?(?:\n\s+"""(.*?)""")', t, re.S | re.M)
            if m2:
                return m2.group(1).strip().splitlines()[0][:60] if m2.group(1) else ""
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return ""

    def _file_size(self, p):
        try:
            return os.path.getsize(p) // 1024
        except Exception:
            return 0

    def list_all(self):
        """扫描全部模块：已安装/仓库/注册状态"""
        from core.lazy_config import LAZY_MAP
        modules = []
        seen = set()
        # 1. 已注册（installed 有文件）
        #    注意：LAZY_MAP 的值自 v3.0 起是 3 元组 (文件, 类名, 中文名)。
        #    这里原来写成 `for name, (f, cls) in LAZY_MAP.items()`，只解 2 个，
        #    必然抛 "too many values to unpack (expected 2)" —— 整个插件市场
        #    扫描直接失败（界面显示"❌ 扫描失败"）。
        for name, info in LAZY_MAP.items():
            if isinstance(info, (list, tuple)) and len(info) >= 2:
                f, cls = info[0], info[1]
            elif isinstance(info, (list, tuple)) and info:
                f, cls = info[0], "?"
            else:
                f, cls = str(info), "?"
            # stt / voice 这类别名指向同一个文件，只保留先出现的那条，
            # 免得同一个模块在列表里出现两次（卡片数会和在线清单对不上）
            if f in seen:
                continue
            fp = os.path.join(self.installed_dir, f + ".py")
            if not os.path.exists(fp):
                fp2 = os.path.join(self.repo_dir, f + ".py")
                if os.path.exists(fp2):
                    modules.append({
                        "name": name, "file": f, "cls": cls,
                        "installed": False, "active": False,
                        "desc": self._doc_of(fp2), "size": self._file_size(fp2),
                        "icon": _icon_of(name),
                    })
                    seen.add(f)
                continue
            modules.append({
                "name": name, "file": f, "cls": cls,
                "installed": True, "active": True,
                "desc": self._doc_of(fp), "size": self._file_size(fp),
                "icon": _icon_of(name),
            })
            seen.add(f)
        # 2. 仓库里有但未安装
        if os.path.exists(self.repo_dir):
            for f in sorted(os.listdir(self.repo_dir)):
                if not f.endswith(".py") or f.startswith("_"):
                    continue
                name = f[:-3]
                if name in seen:
                    continue
                fp = os.path.join(self.repo_dir, f)
                modules.append({
                    "name": name, "file": name, "cls": "?",
                    "installed": False, "active": False,
                    "desc": self._doc_of(fp), "size": self._file_size(fp),
                    "icon": _icon_of(name),
                })
        # 按已安装优先、再按名字排
        # 插件治理摘要：信任等级和权限估计，供市场列表展示。
        try:
            from core.plugin_governance import PluginGovernance
            gov = PluginGovernance(self.base)
            for m in modules:
                fp = os.path.join(self.repo_dir, m.get("file", ""))
                src = ""
                if os.path.isfile(fp):
                    try:
                        src = open(fp, encoding="utf-8", errors="ignore").read(200000)
                    except Exception:  # 静默是故意的 - 读不到源码时只给默认治理信息
                        src = ""
                gi = gov.inspect(src, m)
                m["trust"] = gi.get("trust", "")
                m["permissions"] = gi.get("permissions", [])
                m["risk"] = gi.get("risk", "")
                meta = self._repo_meta(str(m.get("file") or "") + ".py")
                from core.plugin_capabilities import plugin_manifest_info
                m.update(plugin_manifest_info(meta))
        except Exception as e:  # 静默是故意的 - 治理摘要失败不影响插件列表
            _x6_swallowed(__name__, e, "best-effort fallback")
        modules.sort(key=lambda x: (not x["installed"], x["name"]))
        return modules

    # ---------- 验签 ----------
    def _allow_unsigned(self):
        """是否允许安装无签名模块（默认 False，需在 data/config.json 显式开启）"""
        try:
            return bool(self.trunk and self.trunk.config.get("allow_unsigned_plugins", False))
        except Exception:
            return False

    def _allow_inprocess_plugins(self):
        return bool(self.trunk and getattr(self.trunk, "config", {}).get("allow_inprocess_plugins", False))

    def _signer(self):
        from core.plugin_signer import PluginSigner
        return PluginSigner(self.trunk)

    def _repo_meta(self, filename):
        """从 modules_repo/manifest.json 取某文件的 sha256/signature（没有则返回 {}）"""
        try:
            mp = os.path.join(self.repo_dir, "manifest.json")
            if not os.path.exists(mp):
                return {}
            data = json.load(open(mp, encoding="utf-8-sig"))
            for m in data:
                if m.get("file") == filename:
                    return m
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return {}

    def _verify_meta(self, data, meta):
        """按 meta 里的 signature/sha256 校验内容。

        返回 (结果, 说明)：True=已验签通过，False=校验失败，None=没有校验材料
        """
        meta = meta or {}
        try:
            ps = self._signer()
        except Exception as e:
            return False, "验签组件加载失败: %s" % str(e)[:40]
        sig = str(meta.get("signature") or "")
        want = str(meta.get("sha256") or "").lower()
        got = ps.calc_hash_bytes(data)
        if want and got != want:
            return False, "sha256 不匹配（内容与清单不符）"
        if sig:
            if not ps.verify_hash(got, sig):
                return False, "签名校验失败（可能被篡改或非官方包）"
            return True, "已验签"
        if want:
            # 只有哈希、没有签名不能视为可信：能改内容的人通常也能改清单里的
            # sha256。返回 None 让调用方按 allow_unsigned_plugins 严格拒绝。
            return None, "只有 sha256，没有 RSA 签名（默认拒绝安装）"
        return None, "清单里没有 sha256/签名信息"

    def _validate_plugin_payload(self, raw, meta, label="插件"):
        """安装/下载前检查插件 API 版本与 core 依赖边界。

        旧插件没有 api_version 时只给兼容 warning；不支持的版本或
        依赖 core 私有实现则直接拒绝。官方随包模块靠清单
        ``first_party: true`` 放行审计过的集成层。
        """
        try:
            src = (raw.decode("utf-8", errors="replace")
                   if isinstance(raw, bytes) else str(raw))
            r = validate_plugin_manifest(meta or {}, src)
        except Exception as e:
            return False, "插件 API 校验异常: " + str(e)[:100]
        for w in r.get("warnings") or []:
            try:
                if self.trunk:
                    self.trunk._log("%s API 兼容提示: %s" % (label, w))
            # 静默是故意的：兼容提示写不进日志不影响安装判定，主流程仍返回校验结果
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")
        if not r.get("ok"):
            return False, "插件 API 校验失败: " + "；".join(
                (r.get("errors") or [])[:3])
        return True, ""

    def _read_repo_file(self, fname):
        """读仓库文件（优先 manifest 登记的 file 字段）"""
        for cand in (fname, self._repo_meta(fname).get("file")):
            if not cand:
                continue
            p = safe_join(self.repo_dir, cand)
            if p and os.path.isfile(p):
                return p
        return None

    # ---------- 安装 ----------
    def install(self, name):
        """从仓库复制到已安装目录（复制前按 manifest 验签）"""
        from core.lazy_config import LAZY_MAP
        fname = None
        if name in LAZY_MAP:
            fname = LAZY_MAP[name][0]
        else:
            # 从 repo 找
            for f in os.listdir(self.repo_dir):
                if f[:-3] == name and f.endswith(".py"):
                    fname = name
                    break
        if not fname:
            return {"ok": False, "原因": "仓库里找不到 " + name}
        src = self._read_repo_file(fname + ".py")
        dst = os.path.join(self.installed_dir, fname + ".py")
        if not src:
            return {"ok": False, "原因": "仓库文件缺失: " + fname}

        # ---- 验签：仓库模块必须与 manifest 登记的 sha256/签名一致 ----
        try:
            raw = open(src, "rb").read()
        except Exception as e:
            return {"ok": False, "原因": "读取仓库文件失败: " + str(e)[:40]}
        meta = self._repo_meta(os.path.basename(src))
        res, why = self._verify_meta(raw, meta)
        if res is False:
            return {"ok": False, "原因": "仓库模块校验失败: " + why}
        if res is None and not self._allow_unsigned():
            return {"ok": False,
                    "原因": "仓库模块没有签名/校验值，已拒绝安装。"
                            "请先运行 python tools/sign_modules.py 生成清单签名"}

        # ---- 插件 API 版本 / core 依赖边界 ----
        api_ok, api_why = self._validate_plugin_payload(raw, meta, fname)
        if not api_ok:
            return {"ok": False, "原因": api_why}

        # 语法校验（沙盒：先编译临时副本）
        try:
            import py_compile
            tmp = os.path.join(self.backup_dir, "_check.py")
            shutil.copy(src, tmp)
            py_compile.compile(tmp, doraise=True)
            os.remove(tmp)
        except Exception as e:
            return {"ok": False, "原因": "语法校验失败: " + str(e)[:50]}
        shutil.copy(src, dst)
        # 尝试动态加载验证
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("pm_" + fname, dst)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            cls = LAZY_MAP.get(name, (fname, None))[1]
            if cls and not hasattr(m, cls):
                os.remove(dst)
                return {"ok": False, "原因": "类 %s 不存在，已回滚" % cls}
        except Exception as e:
            os.remove(dst)
            return {"ok": False, "原因": "加载失败已回滚: " + str(e)[:50]}
        # 热加载进躯干
        if self.trunk and hasattr(self.trunk, "_load_lazy"):
            try:
                self.trunk._load_lazy(name)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return {"ok": True, "msg": "安装成功: " + fname}

    # ---------- 在线下载 ----------
    def list_online(self):
        """Query explicitly enabled, host-allowlisted HTTPS sources in order."""
        urls, why = remote_repo_urls(getattr(self.trunk, "config", {}) or {})
        if not urls:
            if self.trunk:
                self.trunk._log("在线插件仓库已禁用: " + why)
            return []
        from core.net_guard import get_net_guard
        ng = get_net_guard(self.trunk)
        errors = []
        for base in urls:
            try:
                u = base + "/manifest.json"
                d = ng.check(u, module="plugin_market", purpose="plugin_index")
                if not d.get("allow"):
                    raise PermissionError(d.get("reason") or "网络请求被拒绝")
                data = json.loads(safe_open_url(u, timeout=8).read().decode("utf-8-sig"))
                items = data if isinstance(data, list) else data.get("modules")
                if isinstance(items, list):
                    return [m for m in items if isinstance(m, dict)]
            except Exception as e:
                errors.append("%s: %s" % (base, str(e)[:50]))
        if self.trunk:
            self.trunk._log("在线插件仓库全部失败: " + " | ".join(errors[:2]))
        return []

    def download(self, filename, meta=None):
        """Download one signed remote plugin from the first valid source.

        Every source is tried only for transport availability. The file is never
        written unless the manifest signature verifies successfully.
        """
        urls, why = remote_repo_urls(getattr(self.trunk, "config", {}) or {})
        if not urls:
            return {"ok": False, "原因": why}
        filename = safe_plugin_filename(filename)
        if not filename:
            return {"ok": False, "原因": "非法模块文件名"}
        dst = safe_join(self.installed_dir, filename)
        if not dst:
            return {"ok": False, "原因": "模块落点越界"}
        if meta is None:
            meta = self._repo_meta(filename)
        if not manifest_entry_signed(meta):
            return {"ok": False, "原因": "远程插件必须携带有效 RSA 签名"}
        from core.net_guard import get_net_guard
        ng = get_net_guard(self.trunk)
        errors, raw, verified_why = [], None, ""
        for u in download_urls(urls, filename):
            try:
                d = ng.check(u, module="plugin_market", purpose="plugin_download")
                if not d.get("allow"):
                    raise PermissionError(d.get("reason") or "网络请求被拒绝")
                candidate = safe_open_url(u, timeout=10).read()
                res, source_why = self._verify_meta(candidate, meta)
                # Remote plugins intentionally do not consult _allow_unsigned().
                if res is None:
                    return {"ok": False,
                            "原因": "远程插件没有有效签名，已拒绝: " + source_why}

                if res is True:
                    raw, verified_why = candidate, source_why
                    break
                errors.append("%s: %s" % (u, source_why))
            except Exception as e:
                errors.append("%s: %s" % (u, str(e)[:60]))
        if raw is None:
            return {"ok": False, "原因": "所有插件仓库均失败或验签不通过: " +
                    " | ".join(errors[:3])}
        api_ok, api_why = self._validate_plugin_payload(raw, meta, filename)
        if not api_ok:
            return {"ok": False, "原因": api_why}
        tmp = dst + ".download"
        try:
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, dst)
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return {"ok": False, "原因": "写入失败: " + str(e)[:60]}
        try:
            from core.plugin_governance import PluginGovernance
            gov = PluginGovernance(self.base)
            gi = gov.inspect(raw.decode("utf-8", errors="replace")[:200000], meta)
            gov.record(filename, source="download", trust=gi.get("trust", ""),
                       permissions=gi.get("permissions", []),
                       sha256=hashlib.sha256(raw).hexdigest())
        except Exception:
            gi = {}
        return {"ok": True, "msg": "已下载: %s（%s）" % (filename, verified_why),
                "治理": gi}

    def rollback_module(self, name):
        """从 data/plugin_backups 恢复上一版模块文件。"""
        from core.lazy_config import LAZY_MAP
        if name not in LAZY_MAP:
            return {"ok": False, "原因": "模块未登记"}
        fname = LAZY_MAP[name][0] + ".py"
        src = os.path.join(self.backup_dir, fname)
        if not os.path.isfile(src):
            return {"ok": False, "原因": "没有可回滚的备份: " + fname}
        dst = safe_join(self.installed_dir, fname)
        if not dst:
            return {"ok": False, "原因": "安装路径非法"}
        shutil.copy2(src, dst)
        try:
            self.trunk._load_lazy(name)
        except Exception as e:  # 静默是故意的 - 回滚后热加载失败下次启动会加载
            _x6_swallowed(__name__, e, "best-effort fallback")
        return {"ok": True, "msg": "已回滚: " + fname}

    def governance_report(self, limit=100):
        try:
            from core.plugin_governance import PluginGovernance
            return {"历史": PluginGovernance(self.base).history(limit)}
        except Exception as e:
            return {"错误": str(e)[:80]}

    # ---------- 卸载 ----------
    def uninstall(self, name):
        from core.lazy_config import LAZY_MAP
        if name not in LAZY_MAP:
            return {"ok": False, "原因": "未注册: " + name}
        fname = LAZY_MAP[name][0]
        fp = os.path.join(self.installed_dir, fname + ".py")
        if os.path.exists(fp):
            shutil.move(fp, os.path.join(self.backup_dir, fname + ".py"))
        # 从 lazy_config 移除
        cfg_path = os.path.join(self.base, "core", "lazy_config.py")
        try:
            s = open(cfg_path, encoding="utf-8").read()
            for pat in ['    "%s": (' % name, '  "%s": (' % name]:
                if pat in s:
                    i = s.index(pat)
                    j = s.index(")", i) + 1
                    s = s[:i] + s[j + 1:]
                    open(cfg_path, "w", encoding="utf-8").write(s)
                    break
        except Exception as e:
            return {"ok": False, "原因": "移除注册失败: " + str(e)[:40]}
        # 从躯干卸载实例
        if self.trunk and name in self.trunk.modules:
            try:
                del self.trunk.modules[name]
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return {"ok": True, "msg": "已卸载: " + fname}

    # ---------- 一键装外部 .py 插件 ----------
    def install_file(self, file_path):
        """用户提供 .py 文件 → 沙盒验证 → 复制 → 注册 → 热加载（一键装插件）"""
        import io as _io
        import importlib.util
        import py_compile
        if not file_path or not os.path.exists(file_path):
            return {"ok": False, "原因": "文件不存在"}
        fname = os.path.splitext(os.path.basename(file_path))[0]
        if not fname or not fname[0].isalpha():
            return {"ok": False, "原因": "插件文件名需以字母开头（如 myplugin.py）"}
        if not self._allow_inprocess_plugins():
            return {"ok": False, "原因": "进程内插件安装默认关闭，请使用隔离安装；"
                    "仅开发调试可显式设置 allow_inprocess_plugins=true（不推荐）"}
        dst = os.path.join(self.installed_dir, fname + ".py")
        # ① 沙盒语法校验（编译临时副本，不碰原文件）
        tmp = os.path.join(self.backup_dir, "_check_%s.py" % fname)
        shutil.copy(file_path, tmp)
        try:
            py_compile.compile(tmp, doraise=True)
        except Exception as e:
            try: os.remove(tmp)
            except Exception as e:
                _x6_swallowed(__name__, e)
            return {"ok": False, "原因": "语法校验失败: " + str(e)[:60]}
        # ② 找类名
        src_text = _io.open(tmp, encoding="utf-8", errors="ignore").read()
        m = re.search(r'^class\s+(\w+)', src_text, re.M)
        try: os.remove(tmp)
        except Exception as e:
            _x6_swallowed(__name__, e)
        cls = m.group(1) if m else None
        if not cls:
            return {"ok": False, "原因": "插件里没找到 class 定义"}
        # 插件 API 版本 / core 依赖边界（本地文件没有清单，按第三方严格检查）
        api_ok, api_why = self._validate_plugin_payload(src_text, {}, fname)
        if not api_ok:
            return {"ok": False, "原因": api_why}
        if self.trunk:
            self.trunk._log("警告: 进程内兼容模式安装插件 %s，该模式不是安全沙盒" % fname, "WARN")
        # ③ 动态加载验证（沙盒执行，失败不落盘）
        try:
            spec = importlib.util.spec_from_file_location("plg_" + fname, file_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not hasattr(mod, cls):
                return {"ok": False, "原因": "类 %s 在文件里不存在" % cls}
        except Exception as e:
            return {"ok": False, "原因": "加载验证失败: " + str(e)[:60]}
        # ④ 落盘 + 注册到 lazy_config（自动生成 key）
        shutil.copy(file_path, dst)
        cfg_path = os.path.join(self.base, "core", "lazy_config.py")
        key = fname.replace("-", "_")
        try:
            cfg = _io.open(cfg_path, encoding="utf-8").read()
            if ('"%s": (' % key) not in cfg:
                idx = cfg.rfind("\n}")
                if idx > 0:
                    line = '\n    "%s": ("%s", "%s"),' % (key, fname, cls)
                    cfg = cfg[:idx] + line + cfg[idx:]
                    _io.open(cfg_path, "w", encoding="utf-8", newline="\n").write(cfg)
        except Exception as e:
            return {"ok": False, "原因": "注册失败: " + str(e)[:50]}
        # ⑤ 热加载进躯干（失败不阻塞，下次启动自然注册）
        if self.trunk:
            try:
                self.trunk._load_lazy(key)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return {"ok": True, "msg": "安装成功: " + fname + "（key: " + key + "）"}

    # ---------- 状态 ----------
    def stats(self):
        mods = self.list_all()
        return {
            "模块总数": len(mods),
            "已安装": sum(1 for m in mods if m["installed"]),
            "可安装": sum(1 for m in mods if not m["installed"]),
            "总大小KB": sum(m["size"] for m in mods),
        }

    def run(self, *a):
        return self.stats()
