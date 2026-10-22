# -*- coding: utf-8 -*-
"""代码执行 v2.0 - Python运行 + 安全检查 + 成功率统计 + 历史 + 清空"""
import subprocess, sys, os, time, tempfile
from core.safe import safe
from modules.base import BaseModule


class CodeExecutor(BaseModule):
    NAME = "code_runner"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.history = []
        self.success_count = 0
        self.fail_count = 0
        self.timeout = 10  # 秒

    @safe
    def run_code(self, code):
        """在进程级沙箱中运行 Python 代码。"""
        from core.sandbox import run_python
        r = run_python(str(code or ""), timeout=self.timeout)
        # ⚠️ 返回契约必须统一（2026-10-21 修）：
        #    历史实现只在失败时给中文键（"错误"），成功时只给 stdout/
        #    returncode，**没有 "成功" 字段**。而 pipeline 的
        #    post_processor.verify_code() 读的是 res.get("成功")，
        #    于是每次"沙盒验证"都被判成"运行失败"—— 即使代码本身跑通了。
        #    现在两条路径都带齐：成功(bool) / 输出 / 错误 / stdout /
        #    stderr / returncode / 沙箱。
        stdout = r.get("stdout", "") or ""
        stderr = r.get("stderr", "") or ""
        base = {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": r.get("returncode"),
            "沙箱": "进程级",
        }
        if r.get("timed_out"):
            self.fail_count += 1
            result = dict(base, **{
                "成功": False,
                "输出": stdout[:500],
                "错误": "超时（%s秒），进程树已终止" % self.timeout,
            })
        elif r.get("ok"):
            self.success_count += 1
            result = dict(base, **{
                "成功": True,
                "输出": (stdout or "(无输出)")[:500],
                "错误": stderr[:200],
                "耗时": r.get("duration"),
            })
        else:
            self.fail_count += 1
            result = dict(base, **{
                "成功": False,
                "输出": stdout[:500],
                "错误": stderr[:200] or "执行失败",
            })

        self.history.append({
            "代码": str(code or "")[:50],
            "结果": str(result.get("stdout", result.get("错误", "")))[:50],
            "时间": time.strftime("%m-%d %H:%M")
        })
        if len(self.history) > 20:
            self.history = self.history[-20:]
        return result

    @safe
    def get_history(self, count=10):
        """获取运行历史"""
        return {"历史": self.history[-count:]}

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        self.success_count = 0
        self.fail_count = 0
        return {"ok": True}

    @safe
    def stats(self):
        """统计"""
        total = self.success_count + self.fail_count
        rate = f"{self.success_count/total*100:.1f}%" if total > 0 else "0%"
        return {
            "总运行次数": total,
            "成功次数": self.success_count,
            "失败次数": self.fail_count,
            "成功率": rate
        }

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        report = f"""代码执行报告
==========
总运行次数: {s['总运行次数']}
成功次数: {s['成功次数']}
失败次数: {s['失败次数']}
成功率: {s['成功率']}
"""
        return {"报告": report}

    def run(self, *args, **kwargs):
        """统一入口：支持 timeout 关键字参数临时覆盖默认超时"""
        if args:
            if "timeout" in kwargs:
                old = self.timeout
                try:
                    self.timeout = int(kwargs["timeout"])
                    return self.run_code(args[0])
                finally:
                    self.timeout = old
            return self.run_code(args[0])
        return self.stats()
