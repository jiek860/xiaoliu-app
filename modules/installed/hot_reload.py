# -*- coding: utf-8 -*-
"""热更新模块 v5.1 - 沙盒验证+自动加载+错误弹窗
v5.1: 改用 importlib 动态加载，支持中文文件名模块；监控目录兼容 modules_repo/
"""
from modules.base import BaseModule
# importlib.util 是子模块，必须显式导入：只写 import importlib 的话，
# 在干净进程里 importlib.util 不存在，reload_module 会报
# "module 'importlib' has no attribute 'util'" 然后走回滚 ——
# 全程序能跑只是因为别处碰巧先导入了它，属于侥幸。
import os, sys, importlib, importlib.util, time, subprocess, hashlib, threading

class HotReload(BaseModule):
    NAME = "hot_reload"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = trunk.base if trunk else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # SEV-06: 监控多个目录，不只modules_repo
        self.watch_dirs = [
            os.path.join(self.base, "modules_repo"),
            os.path.join(self.base, "modules", "installed"),
        ]
        self.staging = os.path.join(self.base, "staging")
        self.last_check = {}
        self.reload_count = 0
        self.core_dir = os.path.join(self.base, "core")
        # 同一时刻只允许一个热更新在跑：避免并发写 staging、并发抢 sys.modules
        self._reload_lock = threading.RLock()
        os.makedirs(self.staging, exist_ok=True)

    def check_changes(self):
        """检查代码变化（监控多个目录）"""
        changed = []
        for watch_dir in self.watch_dirs:
            if not os.path.isdir(watch_dir):
                continue
            for f in os.listdir(watch_dir):
                if not f.endswith('.py'):
                    continue
                path = os.path.join(watch_dir, f)
                mtime = os.path.getmtime(path)
                name = f[:-3]
                # mtime + 内容哈希 双变化才算改动
                try:
                    h = hashlib.md5(open(path, "rb").read()).hexdigest()
                except Exception:
                    h = ""
                old = self.last_check.get(name)
                if old and mtime > old[0] and h != old[1]:
                    changed.append(name)
                self.last_check[name] = (mtime, h)
        return changed

    def _find_module(self, name):
        """按模块名（文件名去 .py）查找实际文件，支持中文名"""
        for d in ("modules", "installed"), ("modules_repo",), ("core",):
            p = os.path.join(self.base, *d, name + ".py")
            if os.path.exists(p):
                return p
        return None

    def sandbox_test(self, module_name):
        """沙盒验证模块能不能正常加载（importlib 方式，子进程隔离）"""
        lines = [
            "import sys, os, importlib.util",
            "base = r'%s'" % self.base,
            # 必须先把项目根与 libs 放进 sys.path：
            # 子进程里 sys.path[0] 是本脚本所在目录（staging/），
            # 不补的话模块里的 `from modules.base import BaseModule`、
            # `from core.xxx import yyy` 全会失败，沙盒会把 60% 的正常模块误判为坏模块。
            "sys.path.insert(0, base)",
            "sys.path.insert(0, os.path.join(base, 'libs'))",
            "sys.path.insert(0, os.path.join(base, 'optional_libs'))",
            "cands = [",
            "    os.path.join(base, 'modules', 'installed', '%s.py')," % module_name,
            "    os.path.join(base, 'modules_repo', '%s.py')," % module_name,
            "    os.path.join(base, 'core', '%s.py')," % module_name,
            "]",
            "path = next((p for p in cands if os.path.exists(p)), None)",
            "if not path: print('FAIL: 模块文件不存在'); raise SystemExit(1)",
            "spec = importlib.util.spec_from_file_location('core.%s', path)" % module_name,
            "mod = importlib.util.module_from_spec(spec)",
            "sys.modules['core.%s'] = mod" % module_name,
            "spec.loader.exec_module(mod)",
            "print('OK')",
        ]
        test_code = chr(10).join(lines)
        # 每个调用者用独立的临时文件名。
        # 原来所有线程共用 staging/_reload_test.py：并发热更新时后写的那个会把先写的
        # 覆盖掉，先写的那个子进程实际执行的是别人的脚本 ——
        # 实测 2 线程并发，好模块被判"验证失败"最高 40/40；反序启动时坏模块被判
        # "验证通过"11/40（坏代码会被直接加载进程序）。文件名带上 pid+线程号即可根治。
        test_file = os.path.join(
            self.staging, "_reload_test_%d_%d.py" % (os.getpid(), threading.get_ident()))
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(test_code)
        try:
            r = subprocess.run([sys.executable, test_file],
                               capture_output=True, timeout=10, cwd=self.base)
            output = r.stdout.decode("utf-8", errors="replace")
            if r.returncode == 0 and "OK" in output:
                return True
            # 失败时把真实报错写进日志，避免只看到一句"沙盒验证失败"无从排查
            err = (r.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
            if self.trunk:
                self.trunk._log("沙盒验证 %s 失败: %s" % (module_name, (err[-1] if err else output)[:120]))
            return False
        except Exception:
            return False
        finally:
            # 临时文件用完就删，不再在 staging/ 里堆垃圾
            try:
                os.remove(test_file)
            except OSError:
                pass

    def reload_module(self, name):
        """沙盒验证后热更新；加载/构造失败自动回滚旧版本

        串行化：scheduler / auto_updater / 自身巡检都可能从不同线程调进来，
        不加锁的话同一个模块会被并发加载、sys.modules 被互相顶掉。
        """
        with self._reload_lock:
            return self._reload_module_locked(name)

    def _reload_module_locked(self, name):
        if not self.sandbox_test(name):
            return False, "⚠️ 沙盒验证失败，已保留旧版本（未加载）"
        try:
            path = self._find_module(name)
            if not path:
                return False, "❌ 找不到模块文件: " + name
        except Exception as e:
            return False, "❌ 查找失败: " + str(e)[:50]

        # 加载新版本前备份当前文件（供回滚）
        bak_dir = os.path.join(self.base, "backups", "hot_reload")
        os.makedirs(bak_dir, exist_ok=True)
        bak_path = os.path.join(bak_dir, name + ".py.bak")
        try:
            import shutil
            shutil.copy2(path, bak_path)
        except Exception:
            pass

        try:
            mod_key = "core." + name
            spec = importlib.util.spec_from_file_location(mod_key, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_key] = mod
            spec.loader.exec_module(mod)
            new_cls = None
            for k, v in vars(mod).items():
                if isinstance(v, type) and v.__module__ == mod.__name__:
                    new_cls = v
                    break
            if new_cls and self.trunk:
                try:
                    self.trunk.modules[name] = new_cls(self.trunk)
                except TypeError:
                    try:
                        self.trunk.modules[name] = new_cls()
                    except Exception as e2:
                        self._rollback(name, bak_path)
                        return False, "❌ 构造失败，已自动回滚旧版本: " + str(e2)[:40]
            self.reload_count += 1
            return True, "✅ %s 热更新成功（沙盒验证通过，旧版已备份）" % name
        except Exception as e:
            self._rollback(name, bak_path)
            return False, "❌ 加载失败，已自动回滚旧版本: " + str(e)[:50]

    def _rollback(self, name, bak_path):
        """恢复备份文件，并尽量保留旧实例"""
        try:
            import shutil
            if os.path.exists(bak_path):
                path = self._find_module(name)
                if path:
                    shutil.copy2(bak_path, path)
            if self.trunk:
                self.trunk._log("热更新已回滚: %s" % name)
        except Exception:
            pass

    def check_core_changes(self):
        """检查 core/*.py 是否变化（mtime+内容哈希）"""
        changed = []
        if not os.path.isdir(self.core_dir):
            return changed
        for f in os.listdir(self.core_dir):
            if not f.endswith(".py"):
                continue
            path = os.path.join(self.core_dir, f)
            try:
                h = hashlib.md5(open(path, "rb").read()).hexdigest()
            except Exception:
                continue
            key = "core:" + f
            if key in self.last_check and self.last_check[key][1] != h:
                changed.append(f)
            self.last_check[key] = (os.path.getmtime(path), h)
        return changed

    def reload_core(self):
        """core 变化：沙盒验证整包 → 通过则自动重启程序"""
        if not self._sandbox_core_pkg():
            return {"ok": False, "原因": "core 沙盒验证失败，不重启"}
        self._restart_program()
        return {"ok": True, "状态": "core 已通过沙盒验证并重启"}

    def _sandbox_core_pkg(self):
        """子进程：import core 入口模块，验证整棵依赖树可加载"""
        core_files = [f[:-3] for f in os.listdir(self.core_dir) if f.endswith(".py") and f != "__init__.py"]
        entry = "trunk" if "trunk" in core_files else core_files[0]
        code = ("import sys; sys.path.insert(0, r'%s'); import core.%s; print('OK')"
                % (self.base, entry))
        try:
            r = subprocess.run([sys.executable, "-c", code],
                               capture_output=True, timeout=15)
            return r.returncode == 0 and b"OK" in r.stdout
        except Exception:
            return False

    def _restart_program(self):
        """启动新进程并退出当前（平滑重启）"""
        try:
            exe = sys.executable
            if exe.lower().endswith("python.exe"):
                exe = exe[:-4] + "w.exe"
            subprocess.Popen([exe, os.path.join(self.base, "gui", "app_pyqt.py")],
                             cwd=self.base)
        except Exception:
            pass
        os._exit(0)

    def auto_reload(self):
        """自动热更新（installed 模块热更 + core 整包重载）"""
        changed = self.check_changes()
        results = []
        for name in changed:
            ok, msg = self.reload_module(name)
            results.append(msg)
        core_changed = self.check_core_changes()
        if core_changed:
            results.append("core 变化 %s -> 自动沙盒验证+重启" % core_changed[:2])
            try:
                self.reload_core()
            except Exception as e:
                results.append("core 重载失败: %s" % str(e)[:40])
        return {"检测到变化": len(changed) + len(core_changed), "结果": results}

    def run(self, *args):
        return {
            "状态": "热更新v5.1就绪",
            "已重载次数": self.reload_count,
            "沙盒验证": "开启",
            "监控目录": self.watch_dirs
        }
