# -*- coding: utf-8 -*-
"""规则引擎 v1.0（core） - ABCD 四组规则统一落地
- 注册：rule_id → {组, 类别, 描述, 默认值}
- 配置：data\\rules\\rules.json 覆盖默认值（用户可调，重启保留）
- 查询：trunk.rule(key, default) / rules_engine.get(key)
- 评估：evaluate(rule_id, context) 简易条件判定
- 单一事实源：所有模块的可调参数都从这里读，不再散落硬编码
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json
from core.data_paths import data_path


# 规则默认值升级表：老版本写进 rules.json 的"值"如果**正好是老默认**，
# 说明用户从没动过它 —— 直接迁到新默认。
# 不迁移会怎样：改了默认值的老机器永远拿不到新值（2026-11-01 实测
# "语音.首包上限ms" 改成 3000 后，data/rules/rules.json 仍是 1500，
# 每句正常回复都首包超时降级到系统朗读 —— 用户切音色当然听不出变化）。
_OLD_DEFAULTS = {
    "语音.首包上限ms": (1500, 3000),
}


class RuleEngine:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.rules_dir = data_path(self, "rules")
        self.rules_path = os.path.join(self.rules_dir, "rules.json")
        os.makedirs(self.rules_dir, exist_ok=True)
        self.registry = {}   # rule_id -> 规则定义（组/类别/描述/默认/当前/来源）
        self._json_loaded = False
        self._migrated = False
        self._load_json()
        self._register_all()
        if self._migrated:
            self._save_json()

    # ---------- 配置加载 ----------
    def _load_json(self):
        """读 data\\rules\\rules.json 的覆盖值（存在则应用，不存在用默认）"""
        if os.path.exists(self.rules_path):
            try:
                d = json.load(open(self.rules_path, encoding="utf-8"))
                self._json_overrides = d.get("rules", {}) if isinstance(d, dict) else {}
                self._json_loaded = True
                return
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        self._json_overrides = {}

    def _save_json(self):
        """把当前生效值落盘（用户 set 后持久化）"""
        out = {"rules": {}}
        for rid, r in self.registry.items():
            out["rules"][rid] = {
                "组": r["组"], "类别": r["类别"],
                "描述": r["描述"], "default": r["default"],
                "value": r["当前"],  # 保留当前值
            }
        try:
            json.dump(out, open(self.rules_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    # ---------- 注册 ----------
    def register(self, rule_id, group, category, desc, default):
        """注册一条规则；JSON 有覆盖值则当前值取 JSON"""
        cur = default
        src = "默认"
        if self._json_loaded and rule_id in self._json_overrides:
            jv = self._json_overrides.get(rule_id)
            if isinstance(jv, dict) and "value" in jv:
                cur = jv["value"]
                src = "json"
            elif not isinstance(jv, dict):
                cur = jv
                src = "json"
        old = _OLD_DEFAULTS.get(rule_id)
        if old and src == "json" and cur == old[0] and default != old[0]:
            # 用户没改过（值就是老默认）→ 跟随新默认，并标记需要回写
            cur = default
            src = "迁移"
            self._migrated = True
        self.registry[rule_id] = {
            "组": group, "类别": category, "描述": desc,
            "default": default, "当前": cur, "来源": src,
        }
        return self

    # ---------- 查询 ----------
    def get(self, rule_id, default=None):
        r = self.registry.get(rule_id)
        if r is not None:
            return r["当前"]
        return default

    def set(self, rule_id, value, persist=True):
        """改一条规则当前值；persist=True 落盘重启保留"""
        if rule_id not in self.registry:
            return False
        self.registry[rule_id]["当前"] = value
        self.registry[rule_id]["来源"] = "运行时"
        if persist:
            # 合并到 JSON（保留默认值定义）
            if not self._json_loaded:
                self._json_overrides = {}
            self._json_overrides[rule_id] = {"value": value}
            try:
                allrules = {}
                for rid, r in self.registry.items():
                    allrules[rid] = {
                        "组": r["组"], "类别": r["类别"],
                        "描述": r["描述"], "default": r["default"],
                        "value": r["当前"],
                    }
                json.dump({"rules": allrules},
                          open(self.rules_path, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return True

    # ---------- 评估（简易条件判定，供模块用） ----------
    def evaluate(self, rule_id, context=None):
        """返回该规则当前值（布尔类规则直接返回，数值类返回非0即真）"""
        v = self.get(rule_id)
        if v is None:
            return False
        if isinstance(v, (bool,)):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, str):
            return v.lower() not in ("", "off", "false", "no", "0")
        return bool(v)

    # ---------- 全部规则 ----------
    def all_rules(self):
        """列出全部规则及生效值/来源（供状态栏/日志展示）"""
        rows = []
        for rid in sorted(self.registry.keys()):
            r = self.registry[rid]
            rows.append({
                "规则": rid, "组": r["组"], "类别": r["类别"],
                "描述": r["描述"], "值": r["当前"], "来源": r["来源"],
            })
        return {"规则数": len(rows), "规则": rows}

    def status(self):
        groups = {}
        for r in self.registry.values():
            groups.setdefault(r["组"], 0)
            groups[r["组"]] += 1
        return {"规则引擎": "v1.0", "规则总数": len(self.registry),
                "分组": groups, "配置来源": "json" if self._json_loaded else "默认"}

    def run(self, *args):
        return self.status()

    # ---------- ABCD 全量规则注册 ----------
    def _register_all(self):
        """注册 A/B/C/D 四组全部规则（单一事实源）"""
        A = "A-文档对齐"; B = "B-代码已有"; C = "C-新增优化"; D = "D-新增优化"
        # ===== A 组：文档对齐实际代码 =====
        self.register("向量.半衰期天", A, "参数", "向量分数时间衰减半衰期(天)", 60)
        self.register("沙盒.超时秒", A, "参数", "代码执行/沙盒验证超时(秒)", 10)
        self.register("模型.空闲卸载秒", A, "参数", "LLM 空闲多久卸载模型(秒)", 120)
        self.register("模块.空闲卸载秒", A, "参数", "非核心模块空闲多久卸载(秒)", 120)
        self.register("路由.关键词阈值", A, "参数", "关键词命中≥N 直走不调LLM", 2)
        self.register("备份.保留数", A, "参数", "自动备份保留最新几个", 2)
        self.register("记忆.每人上限", A, "参数", "每账号记忆条数上限", 200)
        self.register("历史.注入轮数", A, "参数", "回复注入最近几轮对话", 5)
        self.register("情景.窗口小时", A, "参数", "情景记忆活跃窗口(小时)", 48)
        self.register("路由.意图数", A, "参数", "智能路由意图表数量", 10)
        self.register("学习.方向数", A, "参数", "学习方向库数量", 5)
        self.register("错误库.上限", A, "参数", "错误记录上限(条)", 500)
        self.register("错误库.截断", A, "参数", "错误记录展示截断(条)", 300)

        # ===== B 组：代码已有规则补录 =====
        self.register("向量.容量上限", B, "参数", "向量数据容量上限(条)", 2000)
        self.register("向量.截断数", B, "参数", "向量数据保留(条)", 1000)
        self.register("缓存.上限", B, "参数", "查询缓存上限(条)", 200)
        self.register("缓存.截断", B, "参数", "查询缓存保留(条)", 100)
        self.register("路由.重试", B, "参数", "LLM 调用失败重试次数", 1)
        self.register("超时.本地秒", B, "参数", "本地模型调用超时(秒)", 90)
        self.register("超时.云端秒", B, "参数", "云端模型调用超时(秒)", 30)
        self.register("超时.嵌入秒", B, "参数", "嵌入请求超时(秒)", 10)
        self.register("回复.组装顺序", B, "规则", "固定顺序:电脑控制→向量→情景→图谱→历史→人格→LLM→群聊", "fixed")
        self.register("后台.步骤数", B, "参数", "回复后后台闭环步数", 8)
        self.register("向量.降级", B, "规则", "嵌入失败返回旧结果不崩", True)

        # ===== C 组：新增优化（已落地） =====
        self.register("路由.conf_threshold", C, "参数", "LLM 路由置信度下限，低于回主LLM", 0.6)
        self.register("检索.top_k", C, "参数", "回复链路向量检索条数(统一)", 3)
        self.register("群聊.开关", C, "规则", "群聊组合+评估+子智能体统一开关", True)
        self.register("技能.确认门", C, "规则", "技能沉淀需用户确认后入库", True)
        self.register("电脑控制.白名单", C, "规则", "文件操作限白名单", True)
        self.register("嵌入.节流秒", C, "参数", "嵌入请求最小间隔(秒)", 0.2)
        self.register("情景.直接接线", C, "规则", "_bg 直接调 remember_scene", True)

        # ===== D 组：新增优化（已落地） =====
        self.register("错误.清理小时", D, "参数", "已修复错误保留多久后清理(小时)", 24)
        self.register("群聊.角色JSON", D, "规则", "角色配置中心化 data/group_roles.json", True)
        self.register("记忆卡.注入去重", D, "规则", "hint 与最近注入卡 Jaccard 去重", True)
        self.register("电脑控制.覆盖确认", D, "规则", "覆盖已存在文件需弹窗确认", True)
        self.register("热重载.哈希检测", D, "规则", "mtime+内容哈希双变化才算改动", True)
        self.register("记忆.压缩再丢", D, "规则", "超上限先压缩最旧10条再截断", True)
        self.register("定时.失败重试", D, "参数", "定时任务失败自动重试次数", 1)
        self.register("群聊.重复阈值", D, "参数", "角色回复与主回复相似度超过即跳过", 0.7)
        self.register("定时.备份间隔秒", D, "参数", "自动备份间隔(秒)", 3600)
        self.register("定时.错误库维护间隔秒", D, "参数", "多久做一次错误库维护：标记已处理并清理旧的(秒)", 14400)
        self.register("定时.复习间隔秒", D, "参数", "记忆复习间隔(秒)", 1800)
        self.register("定时.热检间隔秒", D, "参数", "热更新检测间隔(秒)", 300)
        self.register("学习.连续间隔秒", D, "参数", "连续学习轮间冷却(秒)", 60)
        self.register("电脑控制.允许关机", D, "参数", "是否允许关机/重启（默认禁用，防误触发）", False)
        # 命令执行：默认关闭。code_runner 用黑名单挡危险代码，那套既能被绕过
        # （getattr(os,"sys"+"tem")）又会误伤正常代码（open("a.txt") 直接被杀）；
        # 这里改成白名单 + 默认关 + 每条都弹窗确认，见 computer_controller.shell()
        self.register("电脑控制.允许命令", D, "参数",
                      "是否允许执行白名单内的命令（默认禁用）", False)
        # 工具模式：按场景收窄进 LLM 候选的工具范围（日常/干活/编程/维护）。
        # 默认"全部"= 不过滤，行为与不加这个机制时完全一致。
        # 收窄只影响"给模型看哪些工具"，不影响命令面板里能搜到什么。
        self.register("工具.模式", D, "参数",
                      "工具模式：全部/日常/干活/编程/维护（收窄模型可见的工具）", "全部")
        # ===== 记忆卡规则（v2 规则级参数，可调） =====
        B2 = "B-代码已有"
        self.register("记忆卡.min_rounds", B2, "参数", "最少几轮强制总结", 5)
        self.register("记忆卡.recall_days", B2, "参数", "hint 只带几天内的新记忆", 7)
        self.register("记忆卡.max_hint_cards", B2, "参数", "hint 最多带几张卡", 3)
        self.register("记忆卡.max_facts", B2, "参数", "每张卡最多带几条事实", 3)
        self.register("记忆卡.dup_threshold", B2, "参数", "Jaccard 去重阈值", 0.55)
        self.register("记忆卡.topic_words", B2, "参数", "话题切换共同词阈值", 3)
        # ===== 记忆注入 / 重排（第 4 批 A2 + 深度④⑤，从"代码里的默认值"补录成规则）=====
        self.register("记忆.注入", B2, "规则",
                      "记忆是否注入上下文（总开关，关掉只看情景记忆）", True)
        self.register("记忆.v2", B2, "规则",
                      "记忆实现：off/shadow/on（on=记忆卡替代旧情景记忆）", "on")
        self.register("记忆.注入张数", B2, "参数", "每次最多注入几张记忆卡", 3)
        self.register("记忆.注入字数", B2, "参数", "每次注入记忆的总字数上限", 200)
        self.register("记忆.去重小时", B2, "参数", "同一张卡多久内不重复注入(小时)", 24)
        self.register("记忆.来源引用", B2, "规则",
                      "注入的知识带（来源：记忆）并在回复里说明来源", True)
        self.register("检索.rerank_top_k", B2, "参数",
                      "三路知识重排后最多保留几条", 5)

        # ===== 过程可见（第 5 批 A4 + 深度⑥⑦⑧）=====
        self.register("聊天.过程可见", B2, "规则",
                      "回复步骤是否可见：off/shadow/on（shadow 只记日志不显示）", "on")
        self.register("聊天.单步取消", B2, "规则",
                      "允许单独中止某一步（如只停模型生成，不整个退出）", True)
        self.register("聊天.进度预估", B2, "规则",
                      "步骤条是否显示预计剩余时间（按已完成步骤平均耗时估算）", True)

        # ===== 编辑内核（第 6 批 B1 + 深度①~④）=====
        self.register("code.行号hunk", B2, "规则",
                      "允许模型用 start/end/context 行号形状写 hunk（本地按内容切原文）", True)
        self.register("code.锚点定位", B2, "规则",
                      "原文对不上时按上下文锚点模糊定位（用户手改过也能落）", True)
        self.register("code.三方比对", B2, "规则",
                      "应用前对比磁盘最新内容，冲突给保留我/用AI/手动合并三选一", True)
        self.register("code.逐段撤销", B2, "规则",
                      "每个 hunk 单独留快照，可只撤销其中一段", True)
        self.register("code.改动范围", B2, "规则",
                      "只允许改任务相关文件：off/ask/strict（越界二次审批）", "ask")

        # ===== IDE 内核（第 7 批 B3/B4 + 深度④~⑥）=====
        self.register("编辑.语言服务", B2, "规则",
                      "按文件类型接语言服务（跳定义/引用/重命名/诊断），没装自动退回 jedi", True)
        self.register("编辑.保存格式化", B2, "规则",
                      "保存时自动格式化（black/ruff/prettier），off/on（默认 off：不静默重排用户文件）", "off")
        self.register("编辑.格式化工具", B2, "规则",
                      "优先用哪个格式化工具：auto/black/ruff/prettier/clang-format/gofmt", "auto")
        self.register("编辑.格式先行", B2, "规则",
                      "应用补丁前先格式化目标文件（定位失败自动回退，不留半成品）", True)

        # ===== 上下文与诊断（第 8 批 B2/B5 + 深度⑤~⑩）=====
        self.register("代码.相关片段数", B2, "参数",
                      "上下文里最多带几段跨文件相关代码（相关符号/测试/语义）", 3)
        self.register("代码.仓库地图字数", B2, "参数",
                      "符号地图（按引用热度排序）压进上下文的最大字数", 2400)
        # 默认关：代码片段进了同一个向量库，聊天记忆检索也会搜到它，
        # 长片段会把上下文挤爆。明确打开后才入库 + 召回。
        self.register("代码.语义检索", B2, "规则",
                      "用向量库召回相关代码片段（默认关：会和记忆检索抢额度）", False)
        self.register("代码.测试关联", B2, "规则",
                      "改文件时自动带出对应测试文件（改名只对上文件名也算弱关联）", True)
        self.register("编辑.LSP诊断优先", B2, "规则",
                      "问题列表优先用语言服务的诊断，没装退回 ruff/ast", True)
        self.register("编辑.实时检查", B2, "规则",
                      "编辑停手后实时跑 ruff（未保存文本走 stdin）并标波浪线", True)
        self.register("编辑.一键修复", B2, "规则",
                      "问题行提供「让 AI 修这一行」入口（右键/问题页，不新增按钮）", True)

        # ===== E 组：自主规则（v2 自主版，来自 xiao6-qwen3-4b 训练配方） =====
        E = "E-自主规则"
        self.register("自主.模式", E, "规则", "小6自主模式总开关（体检/提议/升级/学习）", True)
        self.register("自主.升级", E, "规则", "允许自主设计并执行升级方案（危险操作仍弹窗确认）", True)
        self.register("自主.目标驱动", E, "规则", "目标自动拆步执行、汇报进度、检查收尾", True)
        self.register("自主.真实不假装", E, "规则", "做不到/不确定明确说明，不编造已升级已完成", True)
        self.register("联网.默认放开", E, "规则", "默认可联网抓取（官网/GitHub/论坛/文档），无需每次询问", True)
        self.register("联网.反爬应对", E, "规则", "UA轮换/多源并行/失败自动换源", True)
        self.register("联网.AI反馈收集", E, "规则", "主动收集各AI产品用户反馈，提炼改进点", True)
        self.register("学习.自主选方向", E, "规则", "自主决定学什么，学完存入知识库/向量库", True)
        self.register("安全.研究放开", E, "规则", "允许学习CVE/CTF/渗透/防御等公开安全资料（用于学习与防御）", True)
        self.register("安全.底线严格", E, "规则", "拒绝攻击真实系统/恶意软件/入侵盗号/诈骗勒索", True)

        # ===== F 组：成长与主动（批次 48） =====
        F = "F-成长与主动"
        self.register("反思.多维评分", F, "规则",
                      "多维反思 off/shadow/on（关掉回到 v2.1 行为）", "shadow")
        self.register("反思.失败库", F, "规则",
                      "低分样本写入 data/chat_failures.jsonl", True)
        self.register("反思.建议晋升", F, "规则",
                      "同类建议聚合为候选规则（人工确认后生效）", True)
        self.register("反思.晋升阈值", F, "参数",
                      "同类建议出现几次生成候选", 3)
        self.register("反思.TTL天", F, "参数",
                      "反思建议有效天数（防过拟合）", 30)
        self.register("主动.事件驱动", F, "规则",
                      "事件驱动主动搭话 off/shadow/on", "shadow")
        self.register("主动.免打扰开始", F, "参数", "免打扰开始小时（24 制）", 22)
        self.register("主动.免打扰结束", F, "参数", "免打扰结束小时（24 制）", 8)
        self.register("主动.沉默分钟", F, "参数",
                      "用户多久没说话才触发长沉默搭话（分钟）", 90)
        self.register("主动.接受窗口分钟", F, "参数",
                      "用户多久内回话算接受主动搭话（分钟）", 30)
        self.register("语音.情绪", F, "规则",
                      "TTS 按心境调语速/音调 off/on", "on")
        self.register("语音.首包上限ms", F, "参数",
                      "语音首包超过该毫秒数改用系统朗读（edge-tts 实测首包 1.0~1.8 秒）",
                      3000)
        self.register("语音.本地兜底", F, "规则",
                      "在线语音失败时改用系统朗读 off/on（断网/403 也有声音）", "on")

        # ===== G 组：代码 Agent 执行方式 =====
        # 默认开：同步执行时 LLM + 多轮补丁 + pytest 全压在 Qt 主线程上，
        # 用户一点"开始"整个工作台就"未响应"（Windows 会直接标灰）。
        # 关掉 = 回到同步版（任务结束前界面点不动），只在排查线程问题时才建议关。
        G = "G-代码Agent"
        self.register("code_agent.background", G, "规则",
                      "工作台代码任务走后台线程（关掉回同步执行，会卡界面）", True)

    def get_all_rules(self):
        """获取所有规则"""
        return {rid: r for rid, r in self.registry.items()}

    def search_rules(self, keyword):
        """搜索规则"""
        found = {}
        for rid, r in self.registry.items():
            if keyword in rid or keyword in r.get("描述", ""):
                found[rid] = r
        return found

    def reset_rule(self, rule_id):
        """重置规则为默认值"""
        if rule_id in self.registry:
            self.registry[rule_id]["当前"] = self.registry[rule_id]["default"]
            self._save_json()
            return {"成功": True}
        return {"成功": False, "错误": "规则不存在"}

    def reset_all(self):
        """重置所有规则"""
        for rid in self.registry:
            self.registry[rid]["当前"] = self.registry[rid]["default"]
        self._save_json()
        return {"成功": True, "重置数": len(self.registry)}
