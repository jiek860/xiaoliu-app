# -*- coding: utf-8 -*-
"""自动更新：问题收集、建议生成、补丁生成与健康检查（2026-10-31 拆分）。

从 `core/auto_update.py` 拆出（该文件已到 600 行上限）。
这里是「先发现问题 → 再让模型给建议 → 生成补丁」的前半段，不碰文件落盘；
沙箱验证、备份、部署、回滚仍留在 `core/auto_update.py`。
对外导入路径不变：`from core.auto_update import AutoUpdateProblemMixin`。
"""
import os
import py_compile
import re
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class AutoUpdateProblemMixin:
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
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return problems

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
            # ⚠️ 解析不出目标模块时**必须返回空串**，不能返回 ".py"（2026-10-14 修）
            #
            # 原来写的是：
            #     (mod.group(1).strip() if mod else "").strip(".py") + ".py"
            # 模型没按格式回时 mod 是 None -> "" .strip(".py") -> ""
            # -> 再 + ".py" -> **".py"**。
            #
            # 而调用方的守卫是 `if not target_file: return "LLM未给出目标模块"`
            # —— `".py"` 是**真值**，守卫形同虚设。闭环会拿着一个
            # 垃圾目标名继续往下走（打补丁写进 `.py`、再去部署），
            # 直到最后报一句很难懂的错。
            #
            # 现在：拿不到就返回空串，让那道守卫真正生效。
            _t = (mod.group(1).strip() if mod else "").strip()
            if _t.endswith(".py"):
                _t = _t[:-3].strip()
            return {
                "建议": sug.group(1).strip() if sug else txt[:80],
                "目标模块": (_t + ".py") if _t else "",
                "原始": txt[:200],
            }
        except Exception as e:
            return {"建议": "LLM失败: " + str(e)[:40], "目标模块": ""}

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

    def analyze_performance(self):
        start = time.time()
        try:
            if self.trunk:
                self.trunk.reply("测试")
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        elapsed = time.time() - start
        return {"响应时间": "%.2f秒" % elapsed,
                "性能": "优秀" if elapsed < 1 else "一般" if elapsed < 3 else "较慢"}

    def get_update_suggestions(self):
        return {"建议": self.build_suggestion(self.collect_problems() or ["预防性优化"])}
