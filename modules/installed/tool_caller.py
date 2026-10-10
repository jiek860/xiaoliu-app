# -*- coding: utf-8 -*-
"""工具调用器 v11.0 - 真Function Calling：LLM输出JSON→自动执行→结果喂回"""
import json
import sys, os as _os, time
from core.safe import safe
from modules.base import BaseModule


class ToolCaller(BaseModule):
    NAME = "tool_caller"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.usage_history = []
        # 可用工具清单（每个工具有参数说明）
        self.tools = {
            "deep_search": {
                "desc": "联网搜索网页",
                "mod": "deep_search", "method": "search",
                "args": {"query": "搜索关键词"},
            },
            "vector_search": {
                "desc": "搜索历史记忆",
                "mod": "vector_store", "method": "search",
                "args": {"query": "搜索词"},
            },
            "graph_query": {
                "desc": "查询知识图谱",
                "mod": "knowledge_graph", "method": "rag_query",
                "args": {"query": "查询内容"},
            },
            "code_run": {
                "desc": "运行Python代码",
                "mod": "code_runner", "method": "run",
                "args": {"code": "Python代码"},
            },
            "file_read": {
                "desc": "读文件内容",
                "mod": "file_upload", "method": "read",
                "args": {"path": "文件路径"},
            },
            "task_plan": {
                "desc": "规划任务步骤",
                "mod": "task_planner", "method": "run_goal",
                "args": {"goal": "任务目标"},
            },
            "computer": {
                "desc": "控制电脑：打开软件/截屏/系统信息",
                "mod": "computer_controller", "method": "try_handle",
                "args": {"action": "操作"},
            },
        }
        self._merge_mcp_tools()

    def _merge_mcp_tools(self):
        try:
            mc = self.trunk.modules.get("mcp_server")
            if not mc:
                self.trunk.call("mcp_server", "__no__")
                mc = self.trunk.modules.get("mcp_server")
            if mc and hasattr(mc, "list_tools"):
                for t in mc.list_tools().get("工具", []):
                    key = "mcp_" + str(t.get("name", "")).strip()
                    if key and key not in self.tools:
                        self.tools[key] = {
                            "desc": "MCP外部工具-" + str(t.get("desc", "")),
                            "mod": "mcp_server", "method": "call_tool",
                            "args": {"input": "输入"},
                            "mcp_name": t.get("name"),
                        }
        except Exception:
            pass

    def _llm_decide(self, query):
        """真Function Calling：LLM输出JSON决定用什么工具和参数"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return []
        tool_desc = "\n".join([
            f'- "{k}": {v["desc"]}，参数: {json.dumps(v["args"], ensure_ascii=False)}'
            for k, v in self.tools.items()
        ])
        prompt = f"""你是工具调用决策器。根据用户问题决定用哪些工具。

可用工具：
{tool_desc}

用户问题：{query[:200]}

返回JSON格式（不需要工具就返回空数组）：
[{{"tool": "工具名", "args": {{"参数名": "参数值"}}}}]

只返回JSON，不要其他文字："""
        try:
            r = llm.chat(prompt).strip()
            # 提取JSON
            if "[" in r:
                r = r[r.index("["):r.rindex("]")+1]
            calls = json.loads(r)
            # 验证工具存在
            valid = []
            for c in calls:
                if isinstance(c, dict) and c.get("tool") in self.tools:
                    valid.append(c)
            return valid[:3]
        except:
            return []

    def call_tools(self, query):
        """真Function Calling流程：LLM决策→执行→结果返回"""
        calls = self._llm_decide(query)
        if not calls:
            return {"用工具": "无", "回答": "直接聊天"}

        results = []
        # 工具调用日志：tool_call_logger 这个模块登记了却没人调用，
        # 它专门就是干这个的（记工具名/参数/结果/耗时，留最近 50 条）。
        tcl = self.trunk.modules.get("tool_call_logger")
        if tcl is None:
            try:
                self.trunk.call("tool_call_logger", "__no__")
                tcl = self.trunk.modules.get("tool_call_logger")
            except Exception:
                tcl = None

        for call in calls:
            tool_name = call["tool"]
            args = call.get("args", {})
            info = self.tools[tool_name]
            _t0 = time.time()
            try:
                if tool_name.startswith("mcp_"):
                    r = self.trunk.call(info["mod"], info["method"],
                                        info.get("mcp_name", tool_name), args)
                else:
                    self.trunk.call(info["mod"], "__no__")
                    # 把args拼成模块认识的参数
                    arg_val = list(args.values())[0] if args else query
                    r = self.trunk.call(info["mod"], info["method"], arg_val)
                results.append({"工具": tool_name, "参数": args, "结果": str(r)[:400], "成功": True})
                self.usage_history.append({"tool": tool_name, "query": query, "ok": True})
                _res = r
            except Exception as e:
                results.append({"工具": tool_name, "参数": args, "结果": str(e)[:60], "成功": False})
                self.usage_history.append({"tool": tool_name, "query": query, "ok": False})
                _res = e
            if tcl is not None:
                try:
                    tcl.log_call(tool_name, args, _res, time.time() - _t0)
                except Exception:
                    pass

        return {"用工具": [c["tool"] for c in calls], "结果": results}

    def run(self, query=""):
        if query:
            return self.call_tools(query)
        ok = sum(1 for h in self.usage_history if h["ok"])
        return {"工具数": len(self.tools), "总调用": len(self.usage_history), "成功率": f"{ok/max(len(self.usage_history),1)*100:.0f}%"}

