# -*- coding: utf-8 -*-
"""错误库 v2.1 - 错误码 + 中文说明 + 解决方案 + 统计 + 导出 + 搜索"""
import os
from core.safe import safe
from modules.base import BaseModule


class ErrorLibrary(BaseModule):
    NAME = "error_lib"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.error_codes = {
            "E001": {"说明": "网络连接失败", "解决": "检查网络，重试"},
            "E002": {"说明": "文件不存在", "解决": "检查路径是否正确"},
            "E003": {"说明": "权限不足", "解决": "用管理员身份运行"},
            "E004": {"说明": "模型未启动", "解决": "先启动Ollama"},
            "E005": {"说明": "依赖缺失", "解决": "pip install 对应的包"},
            "E006": {"说明": "代码语法错误", "解决": "检查代码语法"},
            "E007": {"说明": "超时", "解决": "重试或加大超时时间"},
            "E008": {"说明": "激活码无效", "解决": "检查激活码是否正确"},
            "E009": {"说明": "数据库错误", "解决": "检查数据库文件"},
            "E010": {"说明": "配置错误", "解决": "检查config.json"},
        }
        # 兼容旧名（保留一个只读别名，逐步废弃）
        self.errors = self.error_codes
        self.usage_count = {}
        self.custom_errors = {}
        self.history = []

    @safe
    def lookup(self, code):
        """查错误码"""
        self.usage_count[code] = self.usage_count.get(code, 0) + 1
        result = self.errors.get(code, self.custom_errors.get(code, {"说明": "未知错误", "解决": "看日志"}))
        self.history.append({"错误码": code, "时间": "now"})
        return result

    @safe
    def add_error(self, code, desc, solution):
        """添加自定义错误码"""
        self.custom_errors[code] = {"说明": desc, "解决": solution}
        return {"ok": True}

    @safe
    def all_errors(self):
        """列出所有错误码"""
        all_err = {**self.errors, **self.custom_errors}
        return all_err

    @safe
    def search_error(self, keyword):
        """搜索错误码"""
        all_err = {**self.errors, **self.custom_errors}
        found = {k: v for k, v in all_err.items() if keyword in v["说明"]}
        return found

    @safe
    def get_history(self, count=10):
        """获取查询历史"""
        return {"历史": self.history[-count:]}

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        self.usage_count = {}
        return {"ok": True}

    @safe
    def stats(self):
        """统计"""
        all_err = {**self.errors, **self.custom_errors}
        return {
            "错误码总数": len(all_err),
            "查询次数": sum(self.usage_count.values()),
            "常用错误码": sorted(self.usage_count.items(), key=lambda x: x[1], reverse=True)[:5]
        }

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        report = f"""错误库报告
==========
错误码总数: {s['错误码总数']}
查询次数: {s['查询次数']}
常用错误码: {s['常用错误码']}
"""
        return {"报告": report}

    def run(self, *args):
        if args:
            return self.lookup(args[0])
        return self.stats()

    @safe
    def delete_error(self, code):
        """删除自定义错误码"""
        if code in self.custom_errors:
            del self.custom_errors[code]
            return {"成功": True}
        return {"成功": False, "错误": "只能删除自定义错误码"}

    @safe
    def get_error_frequency(self):
        """错误频率统计"""
        return sorted(self.usage_count.items(), key=lambda x: x[1], reverse=True)

    @safe
    def guess_error(self, text):
        """根据报错文字猜测错误码"""
        all_err = {**self.errors, **self.custom_errors}
        for code, info in all_err.items():
            if info["说明"] in text:
                return {"猜测": code, "说明": info["说明"]}
        return {"猜测": None}


    # ========== 运行时错误记录 ==========
    def _load_runtime(self):
        import json, time
        p = os.path.join(getattr(self.trunk, "base", "."), "data", "errors_runtime.json")
        if os.path.exists(p):
            try:
                return json.load(open(p, encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_runtime(self, lst):
        import json, time
        p = os.path.join(getattr(self.trunk, "base", "."), "data", "errors_runtime.json")
        try:
            json.dump(lst[-500:], open(p, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        except Exception:
            pass

    @safe
    def log(self, module, action, error, fixed=False):
        """记录一条运行时错误"""
        import time
        lst = self._load_runtime()
        lst.append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "module": module,
            "action": action,
            "error": str(error)[:500],
            "fixed": fixed,
        })
        self._save_runtime(lst)
        return {"ok": True, "总数": len(lst)}

    @safe
    def list(self, only_unfixed=True):
        """列出错误；only_unfixed=True 只返回未修复的"""
        lst = self._load_runtime()
        if only_unfixed:
            lst = [e for e in lst if not e.get("fixed")]
        return {"未修复": len([e for e in lst if not e.get("fixed")]),
                "总数": len(lst), "错误": lst[-50:]}

    @safe
    def analyze(self):
        """用 LLM 分析最近一条未修复错误"""
        lst = [e for e in self._load_runtime() if not e.get("fixed")]
        if not lst:
            return {"分析": "", "错误": ""}
        last = lst[-1]
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return {"分析": "无LLM，无法分析", "错误": last.get("error", "")}
        prompt = (
            "错误模块：%s\n操作：%s\n错误信息：%s\n"
            "请给出修复建议，如果有代码补丁请用 ```python 包裹。"
            % (last.get("module"), last.get("action"), last.get("error"))
        )
        try:
            txt = llm.chat(prompt)
        except Exception as e:
            txt = "分析失败: " + str(e)[:80]
        return {"分析": txt, "错误": last.get("error", "")}

    @safe
    def mark_all_fixed(self):
        """把所有未修复的错误标记为已处理

        原来这一步只存在于 self_heal.apply() 里。self_heal 已删除
        （名字叫"自愈"，实际只是标记 + 记录，一行代码都不改），
        标记和清理的职责搬回错误库自己，另外定时任务会定期调它。
        """
        import time as _t
        lst = self._load_runtime()
        n = 0
        for e in lst:
            if not e.get("fixed"):
                e["fixed"] = True
                e["fixed_time"] = _t.time()
                n += 1
        self._save_runtime(lst)
        return {"ok": True, "已标记": n, "总数": len(lst)}

    @safe
    def clear_all(self):
        """清空运行时错误记录：先全部标记已处理，再立刻清理掉"""
        self.mark_all_fixed()
        r = self.cleanup_fixed(hours=0)
        left = len(self._load_runtime())
        return {"ok": True, "清理": r.get("清理", 0), "剩余": left}

    @safe
    def cleanup_fixed(self, hours=24):
        """清理 hours 小时前已修复的错误"""
        import time
        lst = self._load_runtime()
        now = time.time()
        kept = []
        removed = 0
        for e in lst:
            if e.get("fixed"):
                try:
                    t = time.mktime(time.strptime(e["time"], "%Y-%m-%d %H:%M:%S"))
                except Exception:
                    t = now
                if now - t > hours * 3600:
                    removed += 1
                    continue
            kept.append(e)
        self._save_runtime(kept)
        return {"清理": removed}


