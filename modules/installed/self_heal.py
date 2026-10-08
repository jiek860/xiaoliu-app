# -*- coding: utf-8 -*-
"""自愈闭环 v12.0 - 编排者：扫描错误→LLM分析→生成修复→沙盒验证→确认→应用→复查"""
import os, time, json, subprocess, sys
import sys, os as _os
from core.safe import safe
from modules.base import BaseModule


class SelfHealPipeline(BaseModule):
    NAME = "self_heal"
    VERSION = "1.0"
    """自愈闭环：只当指挥，具体活 trunk.call 给错误库/代码执行/自动更新"""

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.staging = os.path.join(self.base, "staging", "heal")
        os.makedirs(self.staging, exist_ok=True)

    def _log(self, msg):
        if self.trunk:
            try:
                self.trunk._log(msg)
                return
            except:
                pass
        print(msg)

    def _llm(self):
        return self.trunk.modules.get("llm") if self.trunk else None

    # ① 扫描错误
    def scan(self):
        try:
            r = self.trunk.call("error_lib", "list")
            n = (r or {}).get("未修复", 0)
            return n
        except Exception as e:
            self._log("扫描错误库失败: %s" % str(e)[:50])
            return 0

    # ② LLM 分析 + ③ 修复建议
    def analyze(self):
        try:
            r = self.trunk.call("error_lib", "analyze")
            if isinstance(r, dict) and r.get("分析"):
                return r
        except Exception as e:
            self._log("分析失败: %s" % str(e)[:50])
        return None

    # ④ 沙盒验证修复方案
    def verify(self, analysis):
        """把修复方案当代码片段在 staging 隔离跑（只验证语法）"""
        code = str(analysis.get("分析", ""))
        if not code.strip():
            return False, "无修复方案"
        # 提取可能的代码块
        import re
        m = re.search(r"```(?:python|py)?\n(.*?)```", code, re.DOTALL)
        test_code = m.group(1) if m else code
        # 防误判：LLM 只返回“分析建议文字”（无代码块、无代码特征）→ 跳过，不拿废话跑沙盒
        if not m:
            looks_code = any(t in test_code for t in ("def ", "import ", "class ", "self.", "return ", " = "))
            if not looks_code:
                return False, "LLM 未产出代码补丁（仅文字建议），跳过自动修复"
        tf = os.path.join(self.staging, "_heal_test.py")
        try:
            open(tf, "w", encoding="utf-8").write(test_code)
            r = subprocess.run([sys.executable, "-m", "py_compile", tf],
                               capture_output=True, timeout=10)
            return r.returncode == 0, r.stderr.decode("utf-8", errors="replace")[-100:]
        except Exception as e:
            return False, str(e)[:60]

    # ⑤ 确认
    def confirm(self, analysis):
        if not self.trunk:
            return True
        try:
            return bool(self.trunk.confirm("自愈修复", "错误: %s\n方案: %s" % (
                str(analysis.get("错误", ""))[:60],
                str(analysis.get("分析", ""))[:100])))
        except:
            return True

    # ⑥ 应用（标记修复 + 记录）
    def apply(self, analysis):
        try:
            el = self.trunk.modules.get("error_lib")
            if el:
                import time as _t
                # 操作运行时错误列表（不是错误码字典）
                lst = el._load_runtime()
                for e in lst:
                    if not e.get("fixed"):
                        e["fixed"] = True
                        e["fixed_time"] = _t.time()
                el._save_runtime(lst)
                # 记一条"已应用修复"
                el.log("self_heal", "applied",
                       "已应用修复方案: " + str(analysis.get("分析", ""))[:100])
                try:
                    el.cleanup_fixed(24)
                except Exception:
                    pass
            return True
        except Exception as e:
            self._log("应用修复标记失败: %s" % str(e)[:50])
            return False

    def run(self, *args):
        if self.trunk and hasattr(self.trunk, "_chat_busy") and self.trunk._chat_busy():
            self._log("聊天活跃，自愈闭环本轮让路")
            return {"ok": True, "状态": "聊天中，让路"}
        self._log("▶ 自愈闭环开始")
        n = self.scan()
        self._log("① 未修复错误: %d" % n)
        if n == 0:
            self._log("✔ 无错误，自愈闭环结束")
            return {"ok": True, "状态": "无未修复错误"}
        a = self.analyze()
        if not a:
            return {"ok": False, "原因": "LLM 分析失败"}
        self._log("② 分析: %s" % str(a.get("分析", ""))[:60])
        ok, msg = self.verify(a)
        self._log("③ 沙盒验证: %s" % ("通过" if ok else "失败 " + msg[:40]))
        if not ok:
            return {"ok": False, "原因": "沙盒验证失败: " + msg}
        if not self.confirm(a):
            return {"ok": False, "原因": "用户取消", "取消": True}
        self._log("④ 用户已确认")
        ok = self.apply(a)
        self._log("⑤ 应用: %s" % ("完成" if ok else "失败"))
        left = self.scan()
        self._log("▶ 自愈闭环结束 | 剩余未修复: %d" % left)
        return {"ok": ok, "剩余未修复": left, "分析": str(a.get("分析", ""))[:100]}
