# -*- coding: utf-8 -*-
"""自动更新一体化：策略、问题收集、补丁生成、下载安装。

一键合并（2026-10-25）：原来拆成 4 个文件
  auto_update_policy / auto_update_problem / auto_update_patch /
  auto_update_download
对外只保留 `core.auto_update` 一个导入路径；四个 Mixin 的类名与方法
实现保持不变，模块内联加载（modules/installed/auto_updater.py）只需一次导入。
"""
from __future__ import annotations

from core.safe_http import open_url as safe_open_url

import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import threading
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


# 问题收集/建议/补丁生成已拆到 core/auto_update_problem.py（本文件到 600 行上限）。
# 这里保留同名导出，modules/installed/auto_updater.py 的导入路径不变。
from core.auto_update_problem import AutoUpdateProblemMixin  # noqa: F401


def _file_sha256(path):
    """本地文件摘要；读不了返回空串（调用方据此退回"照常下载"）。"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        _x6_swallowed(__name__, e, "hash local file")
        return ""


# ══════════════════════════════════════════════════════════════
# 1. 版本比较、自升级和签名策略（原 auto_update_policy.py）
# ══════════════════════════════════════════════════════════════
class AutoUpdatePolicyMixin:
    def _allow_self_upgrade(self):
        """「自主.升级」规则，默认开（等于改动前的无条件执行）"""
        try:
            if self.trunk:
                return bool(self.trunk.rule("自主.升级", True))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return True

    @staticmethod
    def _version_tuple(v):
        """'v25.1.6' -> (25, 1, 6)，用于版本比较"""
        out = []
        for seg in str(v).lstrip("vV").split("."):
            m = re.match(r"\d+", seg)
            out.append(int(m.group()) if m else 0)
        return tuple(out)

    def _allow_unsigned_update(self):
        try:
            return bool(self.trunk and self.trunk.config.get("allow_unsigned_update", False))
        except Exception:
            return False

    def _log(self, msg):
        if not self.trunk:
            print(msg)
            return
        try:
            self.trunk._log(msg)
        except Exception:
            print(msg)


# ══════════════════════════════════════════════════════════════
# 3. 沙箱验证、备份、部署与回滚（原 auto_update_patch.py）
# ══════════════════════════════════════════════════════════════
class AutoUpdatePatchMixin:
    def sandbox_verify_patch(self, patch_path):
        """在隔离副本验证补丁：语法 + 独立加载（不改动正式文件）"""
        if not os.path.exists(patch_path):
            return False, "补丁文件不存在"
        try:
            py_compile.compile(patch_path, doraise=True)
        except Exception as e:
            return False, "补丁语法错误: " + str(e)[:60]
        # 子进程隔离加载（复制到 staging 独立运行）
        test_code = (
            "import sys, os, importlib.util\n"
            "p = %r\n"
            "spec = importlib.util.spec_from_file_location('mod', p)\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "sys.modules['mod'] = m\n"
            "spec.loader.exec_module(m)\n"
            "print('OK')\n"
        ) % patch_path
        # 文件名带 pid+线程号：与 hot_reload.sandbox_test 同一个坑，
        # 共用固定文件名时两个验证流程并发会互相覆盖，验证结果张冠李戴。
        tf = os.path.join(
            self.staging, "_patch_test_%d_%d.py" % (os.getpid(), threading.get_ident()))
        with open(tf, "w", encoding="utf-8") as f:
            f.write(test_code)
        try:
            r = subprocess.run([sys.executable, tf], capture_output=True,
                               timeout=15)
            out = r.stdout.decode("utf-8", errors="replace")
            if r.returncode == 0 and "OK" in out:
                return True, out[-100:]
            # ⚠️ 失败时要说清**为什么**（2026-10-14 修）
            #
            # 原来只返回 stdout 的尾巴 —— 而 Python 的报错是走 **stderr** 的，
            # 于是用户看到的是"沙盒验证失败: "后面**什么都没有**。
            # 实测踩到：补丁只有两行注解语句，import 时求值报 NameError，
            # 报错全在 stderr，stdout 空的 —— 界面上就一句空话。
            #
            # 现在：优先给 stderr 的最后一两行（那才是真正的错因），
            # 都没有才退回 stdout。
            err = r.stderr.decode("utf-8", errors="replace").strip()
            detail = ""
            if err:
                lines = [x for x in err.splitlines() if x.strip()]
                detail = " | ".join(lines[-2:])[:160]
            if not detail:
                detail = out.strip()[-160:] or "（补丁没能加载，但没有输出）"
            return False, detail
        except Exception as e:
            return False, "超时或执行错误: " + str(e)[:50]
        finally:
            try:
                os.remove(tf)
            except OSError:
                pass

    def ask_confirm(self, plan_text):
        """通过躯干弹窗；没有确认界面时必须拒绝部署。"""
        if not self.trunk or not getattr(self.trunk, "confirm_cb", None):
            return False
        try:
            return bool(self.trunk.confirm("自动更新部署", plan_text))
        except Exception:
            return False

    def backup_current(self, prefix="backup_", keep=5):
        """把当前 core/ 与 modules/ 拷进 backups/<prefix><时间>/。

        prefix 用来区分用途：更新前是 backup_，回滚前是 before_rollback_。
        两者分开轮换，否则回滚时的自备份会把要回滚到的那个备份挤掉。
        """
        name = "%s%s" % (prefix, time.strftime("%Y%m%d_%H%M%S"))
        path = os.path.join(self.backup_dir, name)
        if os.path.exists(path):
            # 同一秒内连备份两次：加个后缀，绝不覆盖已有备份
            path = "%s_%d" % (path, int(time.time() * 1000) % 1000)
        os.makedirs(path, exist_ok=True)
        for d in ("core", "modules"):
            src = os.path.join(self.base, d)
            if os.path.exists(src):
                shutil.copytree(src, os.path.join(path, d), dirs_exist_ok=True)
        # 只保留最近 keep 个同类备份
        olds = sorted(x for x in os.listdir(self.backup_dir)
                      if x.startswith(prefix))
        while len(olds) > int(keep):
            shutil.rmtree(os.path.join(self.backup_dir, olds[0]),
                          ignore_errors=True)
            olds = sorted(x for x in os.listdir(self.backup_dir)
                          if x.startswith(prefix))
        return path

    def _find_module_file(self, target_file):
        """按中文文件名在 installed / modules_repo / core 找文件"""
        for d in (os.path.join(self.base, "modules", "installed"),
                  os.path.join(self.base, "modules_repo"),
                  os.path.join(self.base, "core")):
            p = os.path.join(d, target_file)
            if os.path.exists(p):
                return p
        return None

    def deploy_patch(self, target_file, patch_path, backup_path):
        """备份已做 → 替换正式文件 → 热重载 → 冒烟；失败自动回滚"""
        target = self._find_module_file(target_file)
        if not target:
            return {"ok": False, "原因": "找不到正式模块文件: " + target_file}
        # 记录原内容用于回滚
        old_content = open(target, encoding="utf-8").read()
        new_content = open(patch_path, encoding="utf-8").read()
        try:
            # 替换
            with open(target, "w", encoding="utf-8") as f:
                f.write(new_content)
            # 热重载（沙盒验证通过才加载）
            hr = self.trunk.modules.get("hot_reload") if self.trunk else None
            if hr:
                mod_key = None
                for k, v in (self.trunk._lazy or {}).items():
                    if v and v[0] == target_file[:-3]:
                        mod_key = k
                        break
                if mod_key:
                    ok, msg = hr.reload_module(mod_key)
                    if not ok:
                        raise RuntimeError(msg)
                else:
                    self._log("热重载: 未在懒加载表找到 " + target_file)
            self._log("部署完成: %s" % target_file)
            return {"ok": True, "目标": target_file}
        except Exception as e:
            # 回滚
            try:
                with open(target, "w", encoding="utf-8") as f:
                    f.write(old_content)
                self._log("已自动回滚: %s (%s)" % (target_file, str(e)[:50]))
            except Exception as e2:
                self._log("回滚失败: %s" % str(e2)[:50])
            return {"ok": False, "原因": str(e)[:80], "已回滚": True}

    def rollback(self, backup_path):
        """手动回滚到备份：逐个文件覆盖回去，**不整目录删除**。

        原来的实现是 rmtree(core) + rmtree(modules) 再从备份 copytree ——
        回滚会把更新之后新装的插件、用户自己改过的文件一起抹掉，而且备份
        不存在时还返回 True（界面据此报"回滚成功"，实际什么都没恢复）。
        现在只覆盖备份里存在的文件，备份不存在直接返回 False。

        回滚本身也要能退：先把当前状态备份成 before_rollback_*，
        再逐个写回并**校验**（写不进去 / .py 编译不过都算失败），
        这样"回滚了一半"不会被误报成成功。
        """
        try:
            src = os.path.abspath(str(backup_path or ""))
            if not src or not os.path.isdir(src):
                self._log("回滚失败: 备份目录不存在 %s" % src)
                return False
            try:
                pre = self.backup_current(prefix="before_rollback_")
            except Exception as e:
                # 备份当前状态失败就不动文件 —— 宁可回滚不了，也别制造不可逆
                _x6_swallowed(__name__, e, "backup before rollback")
                self._log("回滚失败: 无法备份当前状态（%s）" % str(e)[:60])
                return False
            restored, bad = 0, []
            for d in ("core", "modules"):
                bk = os.path.join(src, d)
                if not os.path.isdir(bk):
                    continue
                for root, _dirs, fs in os.walk(bk):
                    for name in fs:
                        s = os.path.join(root, name)
                        rel = os.path.relpath(s, bk)
                        t = os.path.join(self.base, d, rel)
                        try:
                            os.makedirs(os.path.dirname(t), exist_ok=True)
                            shutil.copy2(s, t)
                            if name.endswith(".py"):
                                # 在内存里编译，不落 __pycache__：只验能不能加载
                                with open(t, encoding="utf-8") as fh:
                                    compile(fh.read(), t, "exec")
                            restored += 1
                        except Exception as e:
                            _x6_swallowed(__name__, e, "verify restored file")
                            bad.append("%s/%s" % (d, rel.replace(os.sep, "/")))
                            if len(bad) >= 3:
                                break
                    if bad:
                        break
                if bad:
                    break
            self.last_rollback_backup = pre
            if bad:
                self._log("回滚校验失败: %s（当前状态已备份到 %s）"
                          % ("、".join(bad), pre))
                return False
            self._log("回滚完成: %s（%d 个文件；回滚前状态已备份到 %s）"
                      % (src, restored, pre))
            return True
        except Exception as e:
            self._log("回滚失败: %s" % str(e)[:80])
            return False

    def _reload_touched(self, rels):
        """对已替换的模块做热重载；只认登记过的懒加载模块，失败不影响更新结果"""
        hr = self.trunk.modules.get("hot_reload") if self.trunk else None
        if not hr:
            return
        lazy = getattr(self.trunk, "_lazy", {}) or {}
        for rel in rels:
            stem = os.path.basename(rel)[:-3] if rel.endswith(".py") else ""
            for key, v in lazy.items():
                if v and v[0] == stem:
                    try:
                        hr.reload_module(key)
                    except Exception as e:
                        _x6_swallowed(__name__, e)
                        pass
                    break


# ══════════════════════════════════════════════════════════════
# 4. 检查、下载、安装（原 auto_update_download.py）
# ══════════════════════════════════════════════════════════════
class AutoUpdateDownloadMixin:
    def check_update(self, manifest_url=None, timeout=10):
        """拉取远端 manifest.json，**先验签**再比对版本。

        返回 {ok, has_update, current, latest, changelog, verified, manifest, error}
        验签不通过一律拒绝更新（fail closed），防止投毒更新包被下载执行。
        """
        import urllib.request
        from core import release_sign
        from core.version import get_version

        cur = get_version()
        if not manifest_url and self.trunk:
            manifest_url = self.trunk.config.get("update_manifest_url", "") or ""
        if not manifest_url:
            return {"ok": False, "has_update": False, "current": cur,
                    "error": "未配置更新地址（data/config.json 的 update_manifest_url）"}
        try:
            from core.net_guard import get_net_guard
            d = get_net_guard(self.trunk).check(
                manifest_url, module="auto_updater", purpose="update_manifest")
            if not d.get("allow"):
                raise PermissionError(d.get("reason") or "网络请求被拒绝")
            req = urllib.request.Request(manifest_url,
                                         headers={"Cache-Control": "no-cache"})
            raw = safe_open_url(req, timeout=timeout).read()
            # utf-8-sig：兼容被记事本/PowerShell 存成带 BOM 的清单
            manifest = json.loads(raw.decode("utf-8-sig"))
        except Exception as e:
            return {"ok": False, "has_update": False, "current": cur,
                    "error": "拉取更新清单失败: " + str(e)[:80]}

        verified = release_sign.verify_manifest(
            manifest, release_sign.load_release_pubkey(self.base))
        if not verified:
            if not self._allow_unsigned_update():
                return {"ok": False, "has_update": False, "current": cur,
                        "verified": False,
                        "latest": str(manifest.get("version", "")),
                        "error": "更新清单验签失败（签名缺失或被篡改），已拒绝更新。\n"
                                 "发版请先运行 python sign_release.py 生成签名。"}
            self._log("警告: 更新清单未通过验签，但 allow_unsigned_update=true，继续")

        latest = str(manifest.get("version", "")).strip()
        return {"ok": True,
                "has_update": self._version_tuple(latest) > self._version_tuple(cur),
                "current": cur, "latest": latest.lstrip("vV"),
                "changelog": manifest.get("changelog", ""),
                "verified": verified, "manifest": manifest}

    def _safe_relpath(self, rel):
        """把清单里的相对路径限制在项目目录内，防目录穿越和链接逃逸。"""
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        if not rel or "\x00" in rel:
            return None
        base = os.path.realpath(os.path.abspath(self.base))
        p = os.path.realpath(os.path.abspath(os.path.join(base, rel)))
        try:
            if os.path.commonpath([base, p]) != base:
                return None
        except (ValueError, OSError):
            return None
        return p

    def download_and_install(self, manifest, progress_cb=None, confirm=True):
        """下载并安装更新包（manifest 必须验签通过）。

        流程：再验签 → 增量比对本地 sha256（已一致的不下载）→ 下载到 staging 并
        逐个校验 sha256 → 确认 → 备份 → 替换 → 记历史，任一文件失败则回滚已替换的文件。
        """
        import urllib.request
        from core import release_sign
        from core.version import get_version

        verified = release_sign.verify_manifest(
            manifest, release_sign.load_release_pubkey(self.base))
        if not verified and not self._allow_unsigned_update():
            return {"ok": False, "错误": "更新包验签失败，已终止安装"}

        files = manifest.get("files") or []
        if not files:
            return {"ok": False, "错误": "更新包文件列表为空"}

        # ① 增量比对：清单里给了 sha256 且本地文件已经一致，就不再下载/替换。
        #    全量包也能这么跑 —— 结果就是"只动真正变化的文件"。
        pending, skipped = [], 0
        for f in files:
            rel, url = f.get("path", ""), f.get("url", "")
            if not rel or not url or self._safe_relpath(rel) is None:
                return {"ok": False, "错误": "更新包条目非法: %r" % (rel,)}
            want = str(f.get("sha256", "") or "").lower()
            tp = self._safe_relpath(rel)
            if want and tp and os.path.exists(tp) and _file_sha256(tp) == want:
                skipped += 1
                continue
            pending.append(f)
        if not pending:
            self._log("增量更新: %d 个文件已是最新，无需下载" % skipped)
            return {"ok": True, "更新数": 0, "跳过": skipped,
                    "说明": "本地文件已与更新包一致（增量 sha256 校验通过），无需改动"}

        ver = str(manifest.get("version", "unknown"))
        stage = os.path.join(self.staging, "update_" + re.sub(r"[^\w.\-]", "_", ver))
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage, exist_ok=True)

        # ② 下载 + 逐文件校验 sha256（只下增量里真正变化的）
        total = len(pending)
        for i, f in enumerate(pending):
            rel, url = f.get("path", ""), f.get("url", "")
            if progress_cb:
                progress_cb(i, total, rel)
            try:
                from core.net_guard import get_net_guard
                d = get_net_guard(self.trunk).check(
                    url, module="auto_updater", purpose="update_download")
                if not d.get("allow"):
                    raise PermissionError(d.get("reason") or "网络请求被拒绝")
                req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
                data = safe_open_url(req, timeout=30).read()
            except Exception as e:
                return {"ok": False, "错误": "下载失败 %s: %s" % (rel, str(e)[:60])}
            if hashlib.sha256(data).hexdigest() != str(f.get("sha256", "")).lower():
                return {"ok": False, "错误": "文件校验失败(sha256 不符): " + rel}
            sp = os.path.join(stage, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            with open(sp, "wb") as fh:
                fh.write(data)
        if progress_cb:
            progress_cb(total, total, "下载完成")

        # ③ 用户确认（说清楚是增量：只动真正变化的文件）
        ask = "将更新到 v%s，共 %d 个文件" % (ver, total)
        if skipped:
            ask += "（另有 %d 个文件已是最新，增量跳过）" % skipped
        if confirm and not self.ask_confirm(ask):
            return {"ok": False, "错误": "用户取消", "取消": True}

        # ④ 备份 + 替换（失败回滚）
        bk = self.backup_current()
        old_ver = get_version()
        replaced = []
        try:
            for f in pending:
                rel = f["path"]
                sp = os.path.join(stage, rel.replace("/", os.sep))
                tp = self._safe_relpath(rel)
                os.makedirs(os.path.dirname(tp), exist_ok=True)
                if os.path.exists(tp):
                    keep = os.path.join(bk, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(keep), exist_ok=True)
                    shutil.copy2(tp, keep)
                shutil.copy2(sp, tp)
                replaced.append((tp, rel))
        except Exception as e:
            for tp, rel in replaced:
                keep = os.path.join(bk, rel.replace("/", os.sep))
                try:
                    if os.path.exists(keep):
                        shutil.copy2(keep, tp)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            return {"ok": False, "错误": "替换失败已回滚: " + str(e)[:60], "备份": bk}

        # ⑤ 记更新历史（对话框会读这个文件）
        try:
            hp = os.path.join(self.base, "updates", "update_history.jsonl")
            os.makedirs(os.path.dirname(hp), exist_ok=True)
            with open(hp, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "from": old_ver, "to": ver,
                    "files": len(replaced), "skipped": skipped,
                    "total": len(files), "incremental": True,
                    "verified": bool(verified),
                    # 备份目录必须记下来：更新对话框要靠它提供「回滚到这次更新之前」
                    "backup": bk,
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

        # ⑥ 热重载受影响的模块
        self._reload_touched([rel for _, rel in replaced])
        shutil.rmtree(stage, ignore_errors=True)
        self._log("更新完成: v%s -> v%s (%d 个文件，增量跳过 %d)"
                  % (old_ver, ver, len(replaced), skipped))
        return {"ok": True, "更新数": len(replaced), "跳过": skipped,
                "备份": bk, "版本": ver}
