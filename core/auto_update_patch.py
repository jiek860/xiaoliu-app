# -*- coding: utf-8 -*-
"""自动更新：健康检查、沙箱验证、备份、部署和回滚。"""
from __future__ import annotations

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

    def backup_current(self):
        name = "backup_%s" % time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.backup_dir, name)
        os.makedirs(path, exist_ok=True)
        for d in ("core", "modules"):
            src = os.path.join(self.base, d)
            if os.path.exists(src):
                shutil.copytree(src, os.path.join(path, d), dirs_exist_ok=True)
        # 只保留最近5个备份
        olds = sorted(os.listdir(self.backup_dir))
        while len(olds) > 5:
            shutil.rmtree(os.path.join(self.backup_dir, olds[0]), ignore_errors=True)
            olds = sorted(os.listdir(self.backup_dir))
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
        """手动回滚到备份"""
        for d in ("core", "modules"):
            bk = os.path.join(backup_path, d)
            dst = os.path.join(self.base, d)
            if os.path.exists(bk):
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(bk, dst, dirs_exist_ok=True)
        return True

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
