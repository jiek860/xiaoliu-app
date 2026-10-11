# -*- coding: utf-8 -*-
"""规则引擎 v1.0（core） - ABCD 四组规则统一落地
- 注册：rule_id → {组, 类别, 描述, 默认值}
- 配置：data\\rules\\rules.json 覆盖默认值（用户可调，重启保留）
- 查询：trunk.rule(key, default) / rules_engine.get(key)
- 评估：evaluate(rule_id, context) 简易条件判定
- 单一事实源：所有模块的可调参数都从这里读，不再散落硬编码
"""
import os, json


class RuleEngine:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.rules_dir = os.path.join(self.base, "data", "rules")
        self.rules_path = os.path.join(self.rules_dir, "rules.json")
        os.makedirs(self.rules_dir, exist_ok=True)
        self.registry = {}   # rule_id -> 规则定义（组/类别/描述/默认/当前/来源）
        self._json_loaded = False
        self._load_json()
        self._register_all()

    # ---------- 配置加载 ----------
    def _load_json(self):
        """读 data\\rules\\rules.json 的覆盖值（存在则应用，不存在用默认）"""
        if os.path.exists(self.rules_path):
            try:
                d = json.load(open(self.rules_path, encoding="utf-8"))
                self._json_overrides = d.get("rules", {}) if isinstance(d, dict) else {}
                self._json_loaded = True
                return
            except Exception:
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
        except Exception:
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
            except Exception:
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
        # ===== 记忆卡规则（v2 规则级参数，可调） =====
        B2 = "B-代码已有"
        self.register("记忆卡.min_rounds", B2, "参数", "最少几轮强制总结", 5)
        self.register("记忆卡.recall_days", B2, "参数", "hint 只带几天内的新记忆", 7)
        self.register("记忆卡.max_hint_cards", B2, "参数", "hint 最多带几张卡", 3)
        self.register("记忆卡.max_facts", B2, "参数", "每张卡最多带几条事实", 3)
        self.register("记忆卡.dup_threshold", B2, "参数", "Jaccard 去重阈值", 0.55)
        self.register("记忆卡.topic_words", B2, "参数", "话题切换共同词阈值", 3)

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
