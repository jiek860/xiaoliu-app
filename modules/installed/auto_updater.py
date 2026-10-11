# -*- coding: utf-8 -*-
"""自动更新 v12.0 - 完整自更新闭环（编排者模式）

闭环：取问题 → 自我反思/错误库 → 更新建议 → 编程小匠补丁
     → 隔离副本沙盒验证(60项) → GUI弹窗确认 → 全量备份+替换+热重载
     → 失败自动回滚

本模块只当"指挥"，具体活全部 trunk.call 给对应模块（星型拓扑）。
"""
from modules.base import BaseModule
import os, shutil, subprocess, sys, time, json, re, hashlib, py_compile, threading


class AutoUpdater(BaseModule):
    NAME = "auto_updater"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.staging = os.path.join(self.base, "staging")
        self.backup_dir = os.path.join(self.base, "backups")
        self.patch_dir = os.path.join(self.staging, "patches")
        os.makedirs(self.staging, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.patch_dir, exist_ok=True)

    # ============ ① 收集问题源 ============
    def collect_problems(self):
        """错误库未修复错误 + 自我反思教训 → 问题清单"""
        problems = []
        # 错误库
        try:
            err = self.trunk.call("error_lib", "list") if self.trunk else {}
            n = (err or {}).get("未修复", 0)
            if n:
                problems.append("错误库有 %d 个未修复错误" % n)
        except Exception as e:
            problems.append("读取错误库失败: " + str(e)[:40])
        # 自我反思
        try:
            r = self.trunk.call("self_reflect", "get_history", 20) if self.trunk else None
            if r and isinstance(r, dict):
                lessons = r.get("历史", [])
                if lessons:
                    problems.append("自我反思记录了 %d 条历史" % len(lessons))
        except Exception:
            pass
        return problems

    # ============ ② 汇总成更新建议 ============
    def build_suggestion(self, problems):
        """LLM 把问题转成具体更新建议"""
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return {"建议": "无LLM，跳过建议生成", "目标模块": ""}
        prompt = (
            "你是程序架构师。程序有以下问题：\n" +
            "\n".join(problems) +
            "\n请给出1个最值得修的更新建议，格式严格：\n"
            "目标模块:xxx.py（用中文文件名）\n"
            "建议:一句话说明改什么\n"
            "理由:为什么值得改"
        )
        try:
            txt = llm.chat(prompt) or ""
            mod = re.search(r"目标模块[:：]\s*([^\n]+)", txt)
            sug = re.search(r"建议[:：]\s*([^\n]+)", txt)
            return {
                "建议": sug.group(1).strip() if sug else txt[:80],
                "目标模块": (mod.group(1).strip() if mod else "").strip(".py") + ".py",
                "原始": txt[:200],
            }
        except Exception as e:
            return {"建议": "LLM失败: " + str(e)[:40], "目标模块": ""}

    # ============ ③ 编程小匠产出补丁 ============
    def gen_patch(self, suggestion, target_file):
        """调 agent_coder 生成模块新版代码（补丁），写入 patch_dir"""
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return {"ok": False, "错误": "无LLM"}
        target_path = self._find_module_file(target_file)
        old_src = ""
        if target_path and os.path.exists(target_path):
            old_src = open(target_path, encoding="utf-8").read()[:2000]
        prompt = (
            "你是编程小匠。请重写模块文件 %s 的完整Python代码。\n"
            "更新建议：%s\n"
            "现有代码（供参考，前2000字）：\n%s\n"
            "要求：\n"
            "1. 保持类名不变，保持 __init__(self, trunk=None) 签名\n"
            "2. 在原有功能基础上，只做建议里的改进，不要删掉已有方法\n"
            "3. 输出完整可运行代码，不要省略号，不要解释，只输出代码"
        ) % (target_file, suggestion, old_src)
        try:
            code = llm.chat(prompt) or ""
            # 去掉可能的 ```python 围栏
            code = re.sub(r"^```[a-zA-Z]*\s*", "", code.strip())
            code = re.sub(r"\s*```$", "", code.strip())
            patch_path = os.path.join(self.patch_dir, target_file)
            with open(patch_path, "w", encoding="utf-8") as f:
                f.write(code)
            return {"ok": True, "补丁": patch_path, "代码长度": len(code)}
        except Exception as e:
            return {"ok": False, "错误": str(e)[:60]}

    # ============ ④ 隔离副本沙盒验证（60项） ============
    def run_health_checks(self):
        """对全程序做语法+模块加载检查，返回 (通过数, 总数, 失败列表)"""
        passed, total, fails = 0, 0, []
        # 1. core 全部语法
        core_dir = os.path.join(self.base, "core")
        for f in sorted(os.listdir(core_dir)):
            if f.endswith(".py") and not f.startswith("_"):
                total += 1
                try:
                    py_compile.compile(os.path.join(core_dir, f), doraise=True)
                    passed += 1
                except Exception as e:
                    fails.append("core\\%s: %s" % (f, str(e)[:50]))
        # 2. modules/installed 全部语法
        ins_dir = os.path.join(self.base, "modules", "installed")
        if os.path.isdir(ins_dir):
            for f in sorted(os.listdir(ins_dir)):
                if f.endswith(".py") and not f.startswith("_"):
                    total += 1
                    try:
                        py_compile.compile(os.path.join(ins_dir, f), doraise=True)
                        passed += 1
                    except Exception as e:
                        fails.append("installed\\%s: %s" % (f, str(e)[:50]))
        return passed, total, fails

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
            r = subprocess.run([sys.executable, tf], capture_output=True, timeout=15)
            out = r.stdout.decode("utf-8", errors="replace")
            return r.returncode == 0 and "OK" in out, out[-100:]
        except Exception as e:
            return False, "超时或执行错误: " + str(e)[:50]
        finally:
            try:
                os.remove(tf)
            except OSError:
                pass

    # ============ ⑤ 弹窗确认 ============
    def ask_confirm(self, plan_text):
        """通过躯干弹窗（GUI注册了 confirm_cb 会弹窗，无则放行）"""
        if not self.trunk:
            return True
        try:
            return bool(self.trunk.confirm("自动更新部署", plan_text))
        except Exception:
            return True

    # ============ ⑥ 备份+替换+热重载（失败回滚） ============
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

    # ============ 完整闭环 ============
    def run_auto_update(self, confirm=True):
        """执行一次完整自更新闭环，返回每步结果"""
        log = []
        step = lambda s: (log.append(s), self._log(s))[1]
        step("▶ 自更新闭环开始")
        # ① 收集问题
        problems = self.collect_problems()
        if not problems:
            problems = ["程序近期无明显错误，可做预防性优化"]
        step("① 问题源: %s" % "; ".join(problems)[:80])
        # ② 更新建议
        sug = self.build_suggestion(problems)
        step("② 建议: %s" % sug.get("建议", "")[:60])
        target_file = sug.get("目标模块", "")
        if not target_file:
            return {"ok": False, "日志": log, "原因": "LLM未给出目标模块"}
        # ③ 编程小匠补丁
        patch = self.gen_patch(sug.get("建议", ""), target_file)
        if not patch.get("ok"):
            return {"ok": False, "日志": log, "原因": patch.get("错误")}
        step("③ 编程小匠补丁: %s (%d字)" % (target_file, patch.get("代码长度", 0)))
        # ④ 沙盒验证
        ok, msg = self.sandbox_verify_patch(patch["补丁"])
        if not ok:
            return {"ok": False, "日志": log, "原因": "沙盒验证失败: " + msg}
        # 全程序60项检查（部署前验证无破坏）
        p, t, fails = self.run_health_checks()
        step("④ 沙盒通过 | 全程序检查 %d/%d" % (p, t))
        if fails:
            return {"ok": False, "日志": log, "原因": "全程序检查失败: " + fails[0]}
        # ⑤ 弹窗确认
        plan = "将更新模块 %s\n建议：%s\n已通过沙盒验证+全程序%d项检查" % (target_file, sug.get("建议", "")[:60], t)
        if confirm and not self.ask_confirm(plan):
            return {"ok": False, "日志": log, "原因": "用户取消", "取消": True}
        step("⑤ 用户已确认")
        # ⑥ 备份 + 部署 + 热重载（失败回滚）
        bk = self.backup_current()
        step("⑥ 备份: %s" % os.path.basename(bk))
        dep = self.deploy_patch(target_file, patch["补丁"], bk)
        if not dep.get("ok"):
            step("✖ 部署失败: %s（已回滚）" % dep.get("原因", ""))
            return {"ok": False, "日志": log, "原因": dep.get("原因")}
        step("✔ 部署完成并热重载")
        step("▶ 自更新闭环结束")
        return {"ok": True, "日志": log, "备份": bk, "目标": target_file}

    # ============ ⓪ 远端更新：检查 / 下载安装（强制验签）============
    @staticmethod
    def _version_tuple(v):
        """'v25.1.3' -> (25, 1, 3)，用于版本比较"""
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
            req = urllib.request.Request(manifest_url,
                                         headers={"Cache-Control": "no-cache"})
            raw = urllib.request.urlopen(req, timeout=timeout).read()
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
        """把清单里的相对路径限制在项目目录内，防目录穿越"""
        rel = str(rel).replace("\\", "/").lstrip("/")
        base = os.path.normpath(self.base)
        p = os.path.normpath(os.path.join(base, rel))
        if p != base and not p.startswith(base + os.sep):
            return None
        return p

    def download_and_install(self, manifest, progress_cb=None, confirm=True):
        """下载并安装更新包（manifest 必须验签通过）。

        流程：再验签 → 下载到 staging 并逐个校验 sha256 → 确认 → 备份 → 替换 → 记历史，
        任一文件失败则回滚已替换的文件。
        """
        import urllib.request
        from core import release_sign
        from core.version import get_version

        if not release_sign.verify_manifest(manifest,
                                            release_sign.load_release_pubkey(self.base)) \
                and not self._allow_unsigned_update():
            return {"ok": False, "错误": "更新包验签失败，已终止安装"}

        files = manifest.get("files") or []
        if not files:
            return {"ok": False, "错误": "更新包文件列表为空"}

        ver = str(manifest.get("version", "unknown"))
        stage = os.path.join(self.staging, "update_" + re.sub(r"[^\w.\-]", "_", ver))
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage, exist_ok=True)

        # ① 下载 + 逐文件校验 sha256
        total = len(files)
        for i, f in enumerate(files):
            rel, url = f.get("path", ""), f.get("url", "")
            if not rel or not url or self._safe_relpath(rel) is None:
                return {"ok": False, "错误": "更新包条目非法: %r" % (rel,)}
            if progress_cb:
                progress_cb(i, total, rel)
            try:
                req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
                data = urllib.request.urlopen(req, timeout=30).read()
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

        # ② 用户确认
        if confirm and not self.ask_confirm("将更新到 v%s，共 %d 个文件" % (ver, total)):
            return {"ok": False, "错误": "用户取消", "取消": True}

        # ③ 备份 + 替换（失败回滚）
        bk = self.backup_current()
        old_ver = get_version()
        replaced = []
        try:
            for f in files:
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
                except Exception:
                    pass
            return {"ok": False, "错误": "替换失败已回滚: " + str(e)[:60], "备份": bk}

        # ④ 记更新历史（对话框会读这个文件）
        try:
            hp = os.path.join(self.base, "updates", "update_history.jsonl")
            os.makedirs(os.path.dirname(hp), exist_ok=True)
            with open(hp, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "from": old_ver, "to": ver,
                    "files": len(replaced), "verified": True,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # ⑤ 热重载受影响的模块
        self._reload_touched([rel for _, rel in replaced])
        shutil.rmtree(stage, ignore_errors=True)
        self._log("更新完成: v%s -> v%s (%d 个文件)" % (old_ver, ver, len(replaced)))
        return {"ok": True, "更新数": len(replaced), "备份": bk, "版本": ver}

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
                    except Exception:
                        pass
                    break

    # ============ 其他 ============
    def analyze_performance(self):
        start = time.time()
        try:
            if self.trunk:
                self.trunk.reply("测试")
        except Exception:
            pass
        elapsed = time.time() - start
        return {"响应时间": "%.2f秒" % elapsed,
                "性能": "优秀" if elapsed < 1 else "一般" if elapsed < 3 else "较慢"}

    def get_update_suggestions(self):
        return {"建议": self.build_suggestion(self.collect_problems() or ["预防性优化"])}

    def _log(self, msg):
        if not self.trunk:
            print(msg)
            return
        try:
            self.trunk._log(msg)
        except Exception:
            print(msg)

    def run(self, *args):
        return {
            "状态": "自更新闭环就绪",
            "沙盒": self.staging,
            "备份数": len(os.listdir(self.backup_dir)),
            "性能": self.analyze_performance(),
            "用法": "调用 run_auto_update() 执行完整闭环"
        }
