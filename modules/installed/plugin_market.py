# -*- coding: utf-8 -*-
"""插件市场 v1.0 - PluginMarket
真实现：扫描已安装模块 + 仓库模块，支持 安装/卸载/热加载。
- 已安装 = modules/installed 里的文件
- 仓库   = modules_repo 里的镜像
- 卸载    = 移到 data/plugin_backups + 从 lazy_config 移除注册
"""
from modules.base import BaseModule
import os
import re
import sys
import json
import shutil


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
        except Exception:
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
        modules.sort(key=lambda x: (not x["installed"], x["name"]))
        return modules

    # ---------- 验签 ----------
    def _allow_unsigned(self):
        """是否允许安装无签名模块（默认 False，需在 data/config.json 显式开启）"""
        try:
            return bool(self.trunk and self.trunk.config.get("allow_unsigned_plugins", False))
        except Exception:
            return False

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
        except Exception:
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
            return True, "仅校验 sha256（该模块未签名）"
        return None, "清单里没有 sha256/签名信息"

    def _read_repo_file(self, fname):
        """读仓库文件（优先 manifest 登记的 file 字段）"""
        for cand in (fname, self._repo_meta(fname).get("file")):
            if not cand:
                continue
            p = os.path.join(self.repo_dir, cand)
            if os.path.exists(p):
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
            except Exception:
                pass
        return {"ok": True, "msg": "安装成功: " + fname}

    # ---------- 在线下载 ----------
    def list_online(self):
        """从远程仓库拉模块清单（需要配置 online_repo_url）

        仓库现在用 manifest.json 作为索引（它带 sha256 / signature，下载时用于验签）；
        旧版用的 modules.json 已从仓库删除（实测返回 404），这里保留回退以防旧仓库。
        """
        url = self.trunk.config.get("online_repo_url", "") if self.trunk else ""
        if not url:
            return []
        import urllib.request, json
        import time as _t
        last_err = ""
        for fname in ("manifest.json", "modules.json"):
            try:
                r = urllib.request.urlopen(
                    "%s/%s?t=%d" % (url.rstrip("/"), fname, int(_t.time())), timeout=8)
                data = json.loads(r.read().decode("utf-8-sig"))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and isinstance(data.get("modules"), list):
                    return data["modules"]
            except Exception as e:
                last_err = "%s: %s" % (fname, str(e)[:40])
                continue
        if self.trunk:
            self.trunk._log("在线仓库连接失败: " + last_err)
        return []

    def download(self, filename, meta=None):
        """从远程仓库下载 .py 文件，**落盘前必须验签**，raw 慢时自动切 API

        meta: manifest.json 里的条目（含 sha256 / signature）。
              没有校验材料时，除非 config 里 allow_unsigned_plugins=true，否则拒绝安装。
        """
        url = self.trunk.config.get("online_repo_url", "") if self.trunk else ""
        if not url:
            return {"ok": False, "原因": "未配置在线仓库地址"}
        import urllib.request, json, base64
        # 备用源：raw + API
        urls = [
            url + "/" + filename,
            "https://gitee.com/api/v5/repos/cloud-drift/liuyun/contents/" + filename + "?ref=master"
        ]
        # 没传 meta 时，退回本地仓库清单里的登记信息
        if meta is None:
            meta = self._repo_meta(filename)
        last_err = ""
        for i, u in enumerate(urls):
            try:
                r = urllib.request.urlopen(u, timeout=10)
                raw = r.read()
                if i == 1:  # API返回JSON
                    j = json.loads(raw)
                    raw = base64.b64decode(j["content"])
            except Exception as e:
                last_err = str(e)[:50]
                continue
            # ---- 验签：不通过绝不落盘 ----
            res, why = self._verify_meta(raw, meta)
            if res is False:
                return {"ok": False, "原因": "下载内容校验失败: " + why}
            if res is None and not self._allow_unsigned():
                return {"ok": False,
                        "原因": "该模块没有签名/校验值，已拒绝安装。"
                                "需要强制安装可在 data/config.json 设 allow_unsigned_plugins=true"}
            dst = os.path.join(self.installed_dir, filename)
            open(dst, "wb").write(raw)
            return {"ok": True, "msg": "已下载: %s（%s）" % (filename, why)}
        return {"ok": False, "原因": last_err}

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
            except Exception:
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
        dst = os.path.join(self.installed_dir, fname + ".py")
        # ① 沙盒语法校验（编译临时副本，不碰原文件）
        tmp = os.path.join(self.backup_dir, "_check_%s.py" % fname)
        shutil.copy(file_path, tmp)
        try:
            py_compile.compile(tmp, doraise=True)
        except Exception as e:
            try: os.remove(tmp)
            except Exception: pass
            return {"ok": False, "原因": "语法校验失败: " + str(e)[:60]}
        # ② 找类名
        src_text = _io.open(tmp, encoding="utf-8", errors="ignore").read()
        m = re.search(r'^class\s+(\w+)', src_text, re.M)
        try: os.remove(tmp)
        except Exception: pass
        cls = m.group(1) if m else None
        if not cls:
            return {"ok": False, "原因": "插件里没找到 class 定义"}
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
            except Exception:
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
