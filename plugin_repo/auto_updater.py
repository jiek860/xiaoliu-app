# -*- coding: utf-8 -*-
"""自动更新 v12.0 - 完整自更新闭环（编排者模式）

闭环：取问题 → 自我反思/错误库 → 更新建议 → 编程小匠补丁
     → 隔离副本沙盒验证(60项) → GUI弹窗确认 → 全量备份+替换+热重载
     → 失败自动回滚

本模块只当"指挥"，具体活全部 trunk.call 给对应模块（星型拓扑）。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from modules.base import BaseModule
import os, shutil, subprocess, sys, time, json, re, hashlib, py_compile, threading


from core.auto_update import (
    AutoUpdateDownloadMixin, AutoUpdatePatchMixin, AutoUpdatePolicyMixin,
    AutoUpdateProblemMixin,
)


class AutoUpdater(
    AutoUpdateProblemMixin,
    AutoUpdatePatchMixin,
    AutoUpdateDownloadMixin,
    AutoUpdatePolicyMixin,
    BaseModule,
):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "auto_updater"

    VERSION = "1.0"

    # ── 质量闸（2026-10-27）：更新前后都必须过项目门禁 ──
    # 为什么加：原来只做「沙盒跑通 + 60 项自检」就替换正式文件。沙盒只证明
    # **这一个文件**能 import，证明不了整包还能跑 —— 补丁改掉别的模块依赖的
    # 符号、或把版本号改乱，沙盒照样通过，装到用户机器上才发现启动不了。
    _GATE_TIMEOUT = 600

    def _run_gate_cmd(self, label, cmd, timeout=None):
        """跑一条门禁命令。返回 (ok, 说明)。找不到命令/超时都算失败（宁可不更新）"""
        env = self.env_all()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            r = subprocess.run(cmd, cwd=(getattr(self, "base", None)
                                        or os.path.dirname(os.path.dirname(
                                            os.path.dirname(os.path.abspath(__file__))))),
                               env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout or self._GATE_TIMEOUT)
        except FileNotFoundError:
            return False, "%s：找不到命令 %s" % (label, " ".join(cmd[:2]))
        except subprocess.TimeoutExpired:
            return False, "%s：超过 %d 秒未完成" % (label, self._GATE_TIMEOUT)
        except Exception as e:
            return False, "%s：%s" % (label, str(e)[:80])
        if r.returncode == 0:
            return True, "%s：通过" % label
        out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        tail = " | ".join([x.strip() for x in out[-6:] if x.strip()])[:300]
        return False, "%s：失败（退出码 %d）%s" % (label, r.returncode, tail)

    def quality_gate(self, stage="部署前"):
        """自更新的质量闸：部署前跑全门禁，部署后跑快检 + 冒烟 pytest。

        返回 (ok, 说明列表)。任何一项失败 → 调用方必须放弃部署（部署后的则回滚）。
        """
        py = sys.executable or "py"
        notes = []
        if stage == "部署前":
            ok, why = self._run_gate_cmd(
                "提交前检查(全套)", [py, "tools/pre_commit_check.py", "--full"])
            notes.append(why)
            return ok, notes
        ok1, why1 = self._run_gate_cmd(
            "提交前检查(快检)", [py, "tools/pre_commit_check.py"])
        notes.append(why1)
        ok2, why2 = self._run_gate_cmd(
            "冒烟测试", [py, "-m", "pytest", "tests/test_smoke.py",
                         "tests/test_installed_modules_smoke_extra.py", "-q"])
        notes.append(why2)
        return (ok1 and ok2), notes

    def close(self):
        """模块卸载/退出时调：停止接受新的自更新（门禁子进程不会再被拉起）。"""
        self._closed = True
        return {"状态": "已停止"}

    TOOLS = [
        {
         "contract": {
             "params": {},
             "returns": {"type": "object"},
             "description": "自更新：分析问题→打补丁→验证→确认→部署",
         },
         "name": "auto_update", "method": "run_auto_update",
         "desc": "自更新：分析问题→打补丁→验证→确认→部署",
         "args": {},
         "confirm": True,
         # bg：这条要跑几分钟。聊天触发时 _dispatch 是被回复流程**同步**调用的
         # （core/pipeline/legacy_reply.py:133），同步跑会把回复整个卡死 —— 必须转后台。
         "bg": True,
         "hints": ["自动更新", "自我更新", "升级自己", "自更新", "改自己代码"]},
    ]

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
        # ⑤.5 「自主.升级」规则：决定允不允许真的落地部署
        #     这条规则（E 组）原本零引用 —— 也就是说自更新一直在无条件执行。
        #     默认 True = 现状不变；关掉它则只做分析+补丁+沙盒验证（都已完成），
        #     但不改文件、不热重载。危险操作本来就还要过上面那道弹窗确认。
        if not self._allow_self_upgrade():
            step("⏸ 「自主.升级」已关闭：分析已完成，但不部署")
            return {"ok": False, "日志": log, "原因": "自主.升级 已关闭（规则引擎 E 组）",
                    "已分析": True, "目标": target_file}
        # ⑤.6 质量闸（2026-10-27）：沙盒只证明这**一个文件**能加载，
        #      证明不了整包还能跑。部署前必须过项目门禁（含全量 pytest）。
        gok, gnotes = self.quality_gate("部署前")
        step("⑤.6 质量闸(部署前): %s" % "; ".join(gnotes)[:160])
        if not gok:
            return {"ok": False, "日志": log, "原因": "质量闸未过（部署前）：" + gnotes[-1],
                    "目标": target_file, "已分析": True}
        # ⑥ 备份 + 部署 + 热重载（失败回滚）
        bk = self.backup_current()
        step("⑥ 备份: %s" % os.path.basename(bk))
        dep = self.deploy_patch(target_file, patch["补丁"], bk)
        if not dep.get("ok"):
            step("✖ 部署失败: %s（已回滚）" % dep.get("原因", ""))
            return {"ok": False, "日志": log, "原因": dep.get("原因")}
        # ⑥.5 部署后再闸一次：热重载成功 ≠ 整包还能跑
        #      （真实场景：补丁改掉的符号只有别的模块用到，导入阶段看不出来）
        gok2, gnotes2 = self.quality_gate("部署后")
        step("⑥.5 质量闸(部署后): %s" % "; ".join(gnotes2)[:160])
        if not gok2:
            rb = self.rollback(bk)
            step("✖ 部署后检查未过，已回滚: %s" % ("成功" if rb else "失败"))
            return {"ok": False, "日志": log, "备份": bk, "已回滚": bool(rb),
                    "原因": "质量闸未过（部署后）：" + gnotes2[-1],
                    "目标": target_file}
        step("✔ 部署完成并热重载")
        step("▶ 自更新闭环结束")
        return {"ok": True, "日志": log, "备份": bk, "目标": target_file,
                "质量闸": gnotes + gnotes2}

    def run(self, *args):
        return {
            "状态": "自更新闭环就绪",
            "沙盒": self.staging,
            "备份数": len(os.listdir(self.backup_dir)),
            "性能": self.analyze_performance(),
            "用法": "调用 run_auto_update() 执行完整闭环"
        }