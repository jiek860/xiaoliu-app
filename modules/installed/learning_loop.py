# -*- coding: utf-8 -*-
from modules.base import BaseModule
"""学习闭环 v13.0 - 多方向学习库：编程/拟人化/自主化/自我进化/多智能体 轮换学习
编排者：找缺口→搜资料→提炼→入库→汇报
"""
import os, time, json, re, threading


class LearningPipeline(BaseModule):
    NAME = "learning_loop"
    VERSION = "1.0"

    TOOLS = [
        {"name": "learn_topic", "method": "run",
         "desc": "学一个网址/主题：搜资料→提炼→存进知识库和向量库",
         "args": {"topic": "网址或学习主题，如 https://docs.python.org 或 异步编程"},
         "hints": ["学习", "学一下", "了解一下", "查资料学", "深入研究"]},
        {"name": "learn_status", "method": "status",
         "desc": "看学习闭环的状态和累计轮次",
         "args": {},
         "readonly": True,
         "hints": ["学习状态", "学了什么", "学习进度"]},
    ]
    """学习闭环编排者：只当指挥，具体活 trunk.call 给各模块"""

    # 多方向学习库：自动学习按 方向→主题 轮换
    DIRS = {
        "小6项目实战": [
            "向量检索 TF-IDF 余弦相似度 实现", "文本嵌入 embedding 模型对比",
            "LLM 多轮对话 上下文管理", "流式输出 SSE 实现", "Python 热重载 importlib",
            "错误日志 自动修复 系统", "插件架构 Python 动态加载",
            "多智能体 角色分工 对话系统", "Markdown 渲染 Python 库",
            "代码高亮 复制按钮 界面", "PDF 文本提取 Python", "Word docx 解析 Python",
            "文件上传 GUI 应用", "用户权限系统 设计", "配置持久化 JSON 保存",
            "日志系统 logging 最佳实践", "数据备份 恢复 策略",
            "模型微调 LLaMA Factory", "技能库 经验沉淀 智能体",
            "知识图谱 RAG 问答系统", "主动学习 智能体 设计",
            "任务规划 多步执行 Agent",
        ],
        "拟人化": [
            "对话语气自然化", "去除AI味 让回复像真人", "情感识别与共情回复",
            "人格一致性 性格稳定", "记忆如何影响对话", "记住用户偏好",
            "幽默感与轻松表达", "对话节奏与语气词", "主动关怀用户",
            "换位思考表达", "长对话自然衔接", "避免机械重复回答",
            "道歉与认错方式", "适度表达不确定性", "个性化称呼与风格",
        ],
        "自主化": [
            "主动学习决策 学什么", "自我反思与打分改进", "目标拆解与自主执行",
            "自主检索知识", "自我评估 知道自己弱点", "感知用户状态",
            "主动提议帮助", "任务优先级管理", "失败处理与重试策略",
            "长期规划能力", "自主监控与巡检", "环境感知与自适应",
        ],
        "自我进化": [
            "热更新原理", "模块热加载", "自更新流水线 写码测试部署回滚",
            "版本管理与回滚", "沙盒测试", "自动备份策略",
            "错误自愈", "技能沉淀 做过的事记住", "代码生成与自动验证",
            "自我进化架构", "学习效果评估", "自动清理与优化",
        ],
        "多智能体认知": [
            "多Agent协作", "任务路由与分工", "记忆分层 工作记忆长期记忆",
            "认知流水线", "知识图谱推理", "上下文管理",
            "子智能体人设设计", "群聊协调机制", "智能体记忆隔离",
            "角色切换与风格适配", "多智能体共识与投票",
        ],
    }
    DIR_ORDER = ["小6项目实战", "拟人化", "自主化", "自我进化", "多智能体认知"]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.state_path = os.path.join(self.base, "data", "learning_loop.json")
        self.kb_dir = os.path.join(self.base, "data", "knowledge_docs")
        os.makedirs(self.kb_dir, exist_ok=True)
        self.state = self._load()
        self._running = False
        self._thread = None

    def _load(self):
        if os.path.exists(self.state_path):
            try:
                return json.load(open(self.state_path, encoding="utf-8"))
            except:
                pass
        return {"rounds": 0, "learned": [], "last": 0, "dir_idx": 0, "topic_idx": {}}

    def _save(self):
        try:
            json.dump(self.state, open(self.state_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except:
            pass

    def _log(self, msg):
        if self.trunk:
            try:
                self.trunk._log(msg)
                return
            except:
                pass
        print(msg)

    # ① 找知识缺口：方向轮换 + 方向内主题轮换
    def collect_gap(self):
        self.state.setdefault("dir_idx", 0)
        self.state.setdefault("topic_idx", {})
        # 「学习.自主选方向」规则（默认开 = 原来的轮换行为）。
        # 这条原本也是硬编码的：规则引擎 E 组登记着「自主决定学什么」，
        # 但没人读。关掉规则就固定学第一个方向，不自己换方向。
        auto_dir = True
        try:
            if self.trunk:
                auto_dir = bool(self.trunk.rule("学习.自主选方向", True))
        except Exception:
            pass
        if auto_dir:
            d = self.DIR_ORDER[self.state["dir_idx"] % len(self.DIR_ORDER)]
            self.state["dir_idx"] += 1
        else:
            d = self.DIR_ORDER[0]
        topics = self.DIRS[d]
        i = self.state["topic_idx"].get(d, 0) % len(topics)
        topic = topics[i]
        self.state["topic_idx"][d] = i + 1
        self._save()
        return d, topic

    # ② 深度搜索资料
    def fetch(self, topic):
        try:
            r = self.trunk.call("deep_search", "search", topic)
            if isinstance(r, dict) and r.get("结果"):
                return r["结果"]
            return []
        except Exception as e:
            self._log("搜索失败: %s" % str(e)[:50])
            return []

    # ③ 提炼入库：写知识文档 + 入向量
    def store(self, d, topic, items):
        n = 0
        md_lines = ["# " + topic, "",
                    "> 方向: %s | 入库时间: %s" % (d, time.strftime("%Y-%m-%d %H:%M")), ""]
        for it in items[:5]:
            title = it.get("标题", "")
            link = it.get("链接", "")
            content = str(it.get("内容", "") or it.get("摘要", ""))[:300]
            md_lines.append("## " + title)
            if link:
                md_lines.append("来源: " + link)
            if content:
                md_lines.append(content.strip())
            md_lines.append("")
            text = title + " " + content
            if text.strip():
                try:
                    r = self.trunk.call("vector_store", "add", text, tag=d)
                    # 只统计真入库成功的（嵌入失败 add 返回 ok=False，不入库）
                    if isinstance(r, dict) and r.get("ok") is False:
                        self._log("向量入库失败(嵌入失败): %s" % str(text)[:30])
                    else:
                        n += 1
                except Exception as e:
                    self._log("向量入库异常: %s" % str(e)[:50])
        try:
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", topic)[:40]
            doc = os.path.join(self.kb_dir, "[" + d + "] " + safe_name + ".md")
            body = "\n".join(md_lines)
            open(doc, "w", encoding="utf-8").write(body)
            # 建索引：knowledge_docs/ 里已经有 80 多个文档，但 trunk 的
            # _index.json 只有 27 条、停在 09-22 —— 就是因为这里只写文件、
            # 从来没调过 kb_add，索引再没人更新（kb_search/kb_categories 靠它）。
            if self.trunk is not None and hasattr(self.trunk, "kb_add"):
                self.trunk.kb_add("学习主题: " + topic, body[:500], d)
        except Exception:
            pass
        self.state["rounds"] += 1
        self.state["last"] = time.time()
        self.state["learned"].append({"方向": d, "t": topic, "条数": n,
                                      "time": time.strftime("%Y-%m-%d %H:%M")})
        self.state["learned"] = self.state["learned"][-20:]
        self._save()
        return n

    # ④ 汇报
    def report(self, d, topic, n):
        return {
            "方向": d,
            "主题": topic,
            "入库条数": n,
            "累计轮次": self.state["rounds"],
            "各方向进度": {k: "%d/%d" % (self.state.get("topic_idx", {}).get(k, 0), len(v))
                        for k, v in self.DIRS.items()},
            "最近学习": self.state["learned"][-3:][::-1],
        }

    # ===== 连续自主学习：学完一个立即学下一个（不固定时间） =====
    def start_continuous(self, interval=1200):
        """启动连续学习线程：每轮学完休息 interval 秒（LLM冷却），然后立刻学下一个"""
        if self._running:
            return "连续学习已在运行"
        self._running = True
        self._thread = threading.Thread(target=self._continuous_loop,
                                        args=(interval,), daemon=True)
        self._thread.start()
        return "连续学习已启动（学完自动学下一个）"

    def stop_continuous(self):
        self._running = False
        return "连续学习已停止"

    def status(self):
        return {"连续学习运行中": self._running,
                "累计轮次": self.state.get("rounds", 0),
                "最近学习": self.state.get("learned", [])[-3:][::-1]}

    def _continuous_loop(self, interval):
        while self._running:
            # 聊天中（含排队）或回复后120s内暂停学习，避免抢模型
            try:
                _busy = self.trunk._chat_busy() if (self.trunk and hasattr(self.trunk, "_chat_busy")) else False
                if _busy:
                    self._log("用户在聊天，学习暂停本轮")
                    time.sleep(30)
                    continue
            except Exception:
                pass
            try:
                r = self.run()  # 学一个主题（内部每步实时保存）
                self._log("连续学习完成: %s" % str(r.get("主题", r))[:50])
            except Exception as e:
                self._log("连续学习异常: %s" % str(e)[:50])
                try:
                    self.trunk._log("连续学习异常: %s" % str(e)[:50])
                except:
                    pass
            if self._running:
                time.sleep(interval)  # 不固定时间：只做短暂LLM冷却，然后立即下一个

    def run(self, topic=""):
        """执行一轮学习闭环；topic 指定则学指定主题（方向=编程）"""
        self._log("▶ 学习闭环开始")
        d = "小6项目实战"
        if not topic:
            d, topic = self.collect_gap()
        self._log("① 方向: %s | 缺口: %s" % (d, str(topic)[:50]))
        items = self.fetch(topic)
        self._log("② 搜索到 %d 条资料" % len(items))
        if not items:
            return {"ok": False, "原因": "没有搜到资料", "方向": d, "主题": topic}
        n = self.store(d, topic, items)
        self._log("③ 提炼入库 %d 条" % n)
        r = self.report(d, topic, n)
        self._log("▶ 学习闭环结束")
        r["ok"] = True
        return r
    # ========== 新增：偏好可视化 + 主动推荐 + 学习反馈 ==========
    def preference_viz(self):
        """偏好可视化：显示你常用什么功能"""
        if not self.trunk:
            return {}
        prefs = {}
        for k, v in self.trunk.modules.items():
            try:
                if hasattr(v, "stats"):
                    s = v.stats()
                    if isinstance(s, dict):
                        for kk, vv in s.items():
                            if isinstance(vv, (int, float)) and vv > 0:
                                prefs[k] = vv
            except: pass
        return {"偏好统计": prefs}

    def recommend(self):
        """主动推荐：你常用这个，要不要试试那个？"""
        prefs = self.preference_viz().get("偏好统计", {})
        if not prefs:
            return "多聊聊我就知道你喜欢什么了"
        top = sorted(prefs.items(), key=lambda x: x[1], reverse=True)[:3]
        return "你常用：" + "、".join([f"{k}({v}次)" for k, v in top])

    def feedback(self, user_input, good=True):
        """学习反馈：你说'不对'它就改"""
        if not good:
            self._log(f"用户反馈不好: {user_input[:30]}")
            return {"已记录": "负面反馈"}
        return {"已记录": "正面反馈"}

