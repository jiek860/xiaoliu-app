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
        """运行Python代码"""
        # 安全检查
        dangerous = ["os.system", "subprocess", "shutil.rmtree", "open(", "eval(", "exec("]
        for d in dangerous:
            if d in code:
                return {"错误": f"检测到危险操作: {d}", "安全": "已阻止"}

        # 写临时文件
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmpfile = f.name

        try:
            r = subprocess.run(
                [sys.executable, tmpfile],
                capture_output=True, text=True, timeout=self.timeout
            )
            self.success_count += 1
            result = {
                "stdout": r.stdout[:500],
                "stderr": r.stderr[:500],
                "returncode": r.returncode
            }
        except subprocess.TimeoutExpired:
            self.fail_count += 1
            result = {"错误": f"超时（{self.timeout}秒）"}
        except Exception as e:
            self.fail_count += 1
            result = {"错误": str(e)[:80]}
        finally:
            os.unlink(tmpfile)

        # 记录历史
        self.history.append({
            "代码": code[:50],
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
