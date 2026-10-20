# -*- coding: utf-8 -*-
"""健康检查模块 - 从trunk.py拆出来，负责自检/健康分/导出模块图"""
import os, json, time
from datetime import datetime


class HealthCheck:
    def __init__(self, trunk):
        self.trunk = trunk
        self.base = trunk.base
        self.modules = trunk.modules
        self._lazy = trunk._lazy

    def _log(self, msg):
        self.trunk._log(msg)

    def export_module_map(self):
        """导出模块关系图"""
        groups = {"llm":"核心","vector_store":"核心","knowledge_graph":"核心","rules_engine":"核心","auth":"核心","backup":"核心","trunk":"核心","scheduler":"后台","hot_reload":"后台","learning_loop":"闭环","self_heal":"闭环","memory_loop":"闭环","task_loop":"闭环","skill_distill":"闭环","smart_router":"智能体","deep_search":"工具","tool_caller":"工具","computer_controller":"工具","code_runner":"工具","file_upload":"工具","multimodal":"工具","voice":"工具","mcp_server":"工具","task_planner":"高级","error_lib":"高级","auto_updater":"高级","proactive_learner":"高级","rag_engine":"高级","reasoning_engine":"高级","plugin_market":"高级","skill_capture":"高级","self_reflect":"L模块","empathy":"L模块","personality":"L模块","forgetting_curve":"L模块","l135_anomaly":"L模块","memory_cards":"L模块"}
        descs = {"llm":"大模型：本地+云端+流式","vector_store":"向量检索：nomic-embed+余弦","knowledge_graph":"知识图谱：三元组+多跳","rules_engine":"规则引擎：底层规则","auth":"账号激活登录：激活码授权","backup":"自动备份：保留2份","trunk":"微核躯干：注册/总线","scheduler":"定时任务：24h后台","hot_reload":"热更新：沙盒+回滚","learning_loop":"学习闭环：找缺口→搜索→入库","self_heal":"自愈闭环：错误→分析→修复","memory_loop":"记忆闭环：对话→记忆卡→复习","task_loop":"任务闭环：拆步→执行→验证","skill_distill":"技能沉淀：成功任务→SKILL","smart_router":"智能路由：LLM判断谁答","deep_search":"深度搜索：多源并行","tool_caller":"工具调用：LLM自动决定","computer_controller":"电脑控制：鼠标键盘","code_runner":"代码沙盒：隔离跑Python","file_upload":"文件上传：PDF/Word","multimodal":"多模态：看图/听音频","voice":"语音：STT/TTS","mcp_server":"MCP服务：连外部工具","task_planner":"任务规划：自动拆步","error_lib":"错误库：记录+修复建议","auto_updater":"自动更新：自更新流水线","proactive_learner":"主动学习：定时上网找知识","rag_engine":"RAG：检索增强生成","reasoning_engine":"推理引擎：多跳推理","plugin_market":"插件市场：一键装模块","skill_capture":"技能捕获：自动沉淀","self_reflect":"自我反思：回答后打分","empathy":"共情：情绪感知","personality":"人格引擎：小6性格","forgetting_curve":"遗忘：旧记忆自动删","l135_anomaly":"异常检测：行为偏差","memory_cards":"记忆卡：情景记忆"}
        cns = {"trunk":"微核躯干","llm":"大模型","vector_store":"向量检索","knowledge_graph":"知识图谱","rules_engine":"规则引擎","auth":"账号授权","backup":"自动备份","scheduler":"定时任务","hot_reload":"热更新","learning_loop":"学习闭环","self_heal":"自愈闭环","memory_loop":"记忆闭环","task_loop":"任务闭环","skill_distill":"技能沉淀","smart_router":"智能路由","deep_search":"深度搜索","tool_caller":"工具调用","computer_controller":"电脑控制","code_runner":"代码沙盒","file_upload":"文件上传","multimodal":"多模态","voice":"语音","mcp_server":"MCP服务","task_planner":"任务规划","error_lib":"错误库","auto_updater":"自动更新","proactive_learner":"主动学习","rag_engine":"RAG引擎","reasoning_engine":"推理引擎","plugin_market":"插件市场","skill_capture":"技能捕获","self_reflect":"自我反思","empathy":"共情","personality":"人格引擎","forgetting_curve":"遗忘","l135_anomaly":"异常检测","memory_cards":"记忆卡"}
        all_names = list(self.modules.keys()) + [k for k in self._lazy.keys() if k not in self.modules]
        modules = [{"name":n,"cn":cns.get(n,n),"desc":descs.get(n,""),"group":groups.get(n,"其他"),"loaded":n in self.modules} for n in all_names]
        links = [[n, "trunk"] for n in all_names if n != "trunk"]
        _groups = {}
        for n in all_names:
            g = groups.get(n, "其他")
            _groups.setdefault(g, []).append(n)
        for _g, ms in _groups.items():
            for i in range(len(ms)):
                for j in range(i+1, len(ms)):
                    links.append([ms[i], ms[j]])
        _loop_links = [["learning_loop","proactive_learner"],["self_heal","error_lib"],
            ["self_heal","auto_updater"],["task_loop","task_planner"],
            ["rag_engine","vector_store"],["rag_engine","knowledge_graph"],
            ["rag_engine","deep_search"],["skill_distill","skill_capture"],
            ["memory_loop","memory_cards"],["memory_loop","forgetting_curve"],
            ["self_reflect","personality"],["empathy","personality"],
            ["computer_controller","code_runner"],["file_upload","rag_engine"],
            ["multimodal","llm"],["voice","llm"],["tool_caller","deep_search"]]
        links.extend(_loop_links)
        out = {"modules":modules,"links":links}
        p = os.path.join(self.base, r"data\modules_map.js")
        open(p,"w",encoding="utf-8").write("var MODULE_DATA = " + json.dumps(out, ensure_ascii=False, indent=2) + ";")

    def check_ollama(self):
        try:
            import requests
            url = self.trunk.config.get("ollama_url", "http://localhost:11434")
            r = requests.get(url + "/api/tags", timeout=3)
            models = [m["name"] for m in r.json().get("models", [])]
            return {"ok": True, "models": models}
        except Exception as e:
            return {"ok": False, "error": str(e)[:50]}

    def check_cloud(self):
        try:
            import requests
            url = self.trunk.config.get("cloud_url", "")
            key = self.trunk.config.get("cloud_key", "")
            if not url or not key:
                return {"ok": False, "error": "未配置"}
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:50]}

    def health_score(self):
        score = 100
        if not self.check_ollama()["ok"]:
            score -= 20
        if not self.check_cloud()["ok"]:
            score -= 10
        return score
