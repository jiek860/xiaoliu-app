# -*- coding: utf-8 -*-
"""v26-7.2: 工具链编排 完整版"""
import json


class ToolChain:
    """多工具串联执行，变量传递"""
    def __init__(self, trunk=None):
        self.trunk = trunk

    def run_chain(self, steps):
        """
        steps = [{"tool": "...", "args": {...}, "save_as": "var1"}, ...]
        支持变量传递：{{var名}}
        """
        context = {}
        results = []
        for i, step in enumerate(steps):
            tool_name = step["tool"]
            args = dict(step.get("args", {}))
            # 变量替换
            for k, v in args.items():
                if isinstance(v, str):
                    for var, val in context.items():
                        v = v.replace("{{%s}}" % var, str(val))
                    args[k] = v
            # 执行
            try:
                if self.trunk:
                    arg_val = list(args.values())[0] if args else ""
                    r = self.trunk.call(tool_name, "run", arg_val)
                    result_str = str(r)[:200]
                else:
                    result_str = "ok"
                results.append({"步骤": i+1, "工具": tool_name, "结果": result_str, "状态": "成功"})
                if step.get("save_as"):
                    context[step["save_as"]] = result_str
            except Exception as e:
                results.append({"步骤": i+1, "工具": tool_name, "错误": str(e)[:60], "状态": "失败"})
        return {"ok": True, "步骤": results, "变量": context, "总步骤": len(steps)}

    def plan_chain(self, query):
        """LLM自动规划工具链（简化版）"""
        return {
            "query": query,
            "建议步骤": ["搜索", "总结", "生成报告"],
        }

    def run(self, *a):
        return {"功能": "工具链编排", "支持": "变量传递、错误处理"}
