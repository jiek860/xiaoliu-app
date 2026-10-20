# -*- coding: utf-8 -*-
"""真·多智能体群聊 v16.0 - GroupChat
按问题类型并行召集 小七(编程技术) / 小八(分析推理) / 小九(策划创意)，
与小6组成群聊，各自独立人设、独立记忆（记忆按登录账号隔离）。
- 小6的主回复由躯干主链路生成，本模块只负责追加相关角色
- 说“大家/各位/都来说”等强制全员回复；@角色名/直呼角色名单独点名
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import re
import json
import time
from concurrent.futures import ThreadPoolExecutor

from core.safe import safe
from modules.base import BaseModule

class GroupChat(BaseModule):
    NAME = "group_chat"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = trunk.base if trunk else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # 角色：人设 + 关键词路由
        self.roles = {
            "小七": {
                "duty": "编程与技术",
                "persona": (
                    "你是小七，小6群聊里的编程技术担当，性格直爽、爱折腾代码。"
                    "要求：1)只谈编程、软件、电脑技术相关内容；"
                    "2)说话直接干脆，不寒暄、不复述问题；"
                    "3)涉及代码给最小可用片段，用```包裹；"
                    "4)回复不超过200字。"
                ),
                "keywords": [
                    "代码", "编程", "python", "bug", "报错", "程序", "脚本", "函数",
                    "软件", "安装", "接口", "数据库", "算法", "服务器", "部署", "配置",
                    "html", "css", "java", "javascript", "js", "api", "插件", "模块",
                    "异常", "调试", "正则", "类库", "框架", "git", "命令行",
                ],
            },
            "小八": {
                "duty": "分析推理",
                "persona": (
                    "你是小八，小6群聊里的冷静分析担当，理性、重事实和逻辑。"
                    "要求：1)习惯分1、2、3点给结论，指出利弊和风险；"
                    "2)不煽情、不灌鸡汤；3)说话不超过200字；"
                    "4)不要重复小6已经说过的内容，只补充你独有的分析。"
                ),
                "keywords": [
                    "分析", "为什么", "原因", "对比", "区别", "评价", "好坏", "总结",
                    "数据", "逻辑", "怎么看", "值不值", "风险", "概率", "报告", "复盘",
                    "原理", "靠谱吗", "是不是", "会不会",
                ],
            },
            "小九": {
                "duty": "策划创意",
                "persona": (
                    "你是小九，小6群聊里的创意策划担当，热情活泼、点子多。"
                    "要求：1)擅长把事情拆成可执行步骤，给方案和备选；"
                    "2)想法有创意、具体可落地；3)说话不超过200字；"
                    "4)不要重复小6已经说过的内容，直接上你的方案。"
                ),
                "keywords": [
                    "计划", "方案", "策划", "创意", "设计", "点子", "怎么办", "安排",
                    "路线", "规划", "帮我想", "活动", "文案", "起名", "礼物", "旅行",
                    "攻略", "惊喜", "生日", "约会", "推荐", "怎么弄",
                ],
            },
        }
        # 强制全员发言的提示词
        self.all_hint = ["大家", "所有人", "一起讨论", "都来说", "都说说", "各位", "群聊", "讨论讨论", "你们几个"]
        # D2: 角色配置中心化——data\group_roles.json 可覆盖默认（设置改名联动）
        self.roles_file = os.path.join(self.base, "data", "group_roles.json")
        self._load_roles()

    def _load_roles(self):
        """D2: 读角色配置文件；无文件则落盘默认；外部配置补齐缺失角色"""
        import json as _json
        default_roles = self.roles.copy()
        if os.path.exists(self.roles_file):
            try:
                ext = _json.load(open(self.roles_file, encoding="utf-8"))
                if isinstance(ext, dict) and ext:
                    # 合并：以外部为准，但补齐缺失角色
                    for k, v in default_roles.items():
                        if k not in ext:
                            ext[k] = v
                    self.roles = ext
                    return
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        try:
            _json.dump(self.roles, open(self.roles_file, "w", encoding="utf-8"),
                       ensure_ascii=False, indent=2)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    @safe
    def save_roles(self):
        """D2: 设置改名后写回 JSON，重启不丢"""
        import json as _json
        _json.dump(self.roles, open(self.roles_file, "w", encoding="utf-8"),
                   ensure_ascii=False, indent=2)
        return True

    def rename_role(self, old, new):
        """改角色名：同步 keywords + 持久化；聊天即时生效"""
        old = str(old).strip()
        new = str(new).strip()
        if old not in self.roles:
            return {"ok": False, "原因": "角色不存在: " + old}
        if not new or (new in self.roles and new != old):
            return {"ok": False, "原因": "新名字为空或已存在"}
        cfg = self.roles.pop(old)
        cfg["keywords"] = [w.replace(old, new) for w in cfg.get("keywords", [])]
        self.roles[new] = cfg
        self.save_roles()
        return {"ok": True, "角色": new}

    def update_role(self, name, persona=None, keywords=None, duty=None):
        """D2: 更新单个角色配置（改名/改人设/改关键词），改后写回 JSON"""
        if name not in self.roles:
            return False
        if persona is not None:
            self.roles[name]["persona"] = persona
        if keywords is not None:
            self.roles[name]["keywords"] = keywords
        if duty is not None:
            self.roles[name]["duty"] = duty
        return self.save_roles()

    # ---------- 账号与记忆 ----------
    def _username(self):
        try:
            r = self.trunk.call("auth", "whoami")
            if isinstance(r, dict):
                u = r.get("user")
                if u and u != "未登录":
                    return u
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return None

    def _mem_dir(self, username):
        if username:
            d = os.path.join(self.base, "data", "users", username, "group_mem")
        else:
            d = os.path.join(self.base, "data", "group_mem")  # 游客共用
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return d

    def _mem_path(self, role, username):
        return os.path.join(self._mem_dir(username), role + ".jsonl")

    def _load_mem(self, role, username, n=5):
        """读该角色最近 n 轮自己的问答，拼成 messages"""
        p = self._mem_path(role, username)
        if not os.path.exists(p):
            return []
        try:
            lines = open(p, encoding="utf-8").readlines()[-n:]
            out = []
            for ln in lines:
                try:
                    m = json.loads(ln)
                    out.append({"role": "user", "content": m.get("u", "")})
                    out.append({"role": "assistant", "content": m.get("a", "")})
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            return out
        except Exception:
            return []

    def _append_mem(self, role, username, q, a):
        try:
            with open(self._mem_path(role, username), "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "u": q[:300], "a": a[:1000]},
                                   ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    # ---------- 路由 ----------
    def pick_roles(self, text):
        """根据消息返回需要发言的角色列表（保持 小七→小八→小九 顺序）"""
        t = (text or "").lower()
        # 强制全员
        if any(h in text for h in self.all_hint):
            return list(self.roles.keys())
        hits = []
        for role, cfg in self.roles.items():
            named = ("@" + role) in text or role in text
            kw_hit = any(k.lower() in t for k in cfg["keywords"])
            if named or kw_hit:
                hits.append(role)
        return hits

    # 角色 → 子智能体模块映射
    ROLE_MOD = {"小七": "agent_coder", "小八": "agent_analyst", "小九": "agent_planner"}

    # ---------- 单角色回复 ----------
    def _role_reply(self, role, question, main_answer, username):
        # ① 优先调真实子智能体模块（agent_coder/agent_analyst/agent_planner）
        mname = self.ROLE_MOD.get(role)
        if mname:
            try:
                mod = self.trunk.modules.get(mname) if self.trunk else None
                if not mod and self.trunk:
                    self.trunk._load_lazy(mname)
                    mod = self.trunk.modules.get(mname)
                if mod and hasattr(mod, "reply"):
                    ans = mod.reply(str(question)[:300])
                    if ans and not str(ans).startswith(("本地模型错误", "（抱歉", "出错了", "（无模型")):
                        ans = re.sub(r"^【[^】]{1,8}】\s*", "", str(ans).strip())[:300]
                        if ans:
                            self._append_mem(role, username, question, ans)
                            return "【%s】\n%s" % (role, ans)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        # ② 回退：LLM 用人设生成
        cfg = self.roles[role]
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return None
        msgs = [{"role": "system", "content": cfg["persona"]}]
        msgs += self._load_mem(role, username)
        msgs.append({"role": "user", "content": (
            "群友的问题：%s\n\n小6刚才回复的要点：%s\n\n"
            "请你从%s担当的角度补充你的看法，不要简单重复小6的话，直接开口说重点。"
            % (str(question)[:300], str(main_answer)[:600], cfg["duty"])
        )})
        try:
            # 群聊子角色固定走主力模型 xiao6-7b，不参与三级路由（避免简单问候被分流到小模型）
            force_model = self.trunk.config.get("local_model", "xiao6-7b:latest")
            ans = llm.chat(msgs, inject_persona=False, force_model=force_model)
            if not ans or str(ans).startswith("本地模型错误") or str(ans).startswith("（抱歉"):
                return None
            ans = str(ans).strip()
            # 去掉模型自己加的【某某】前缀
            ans = re.sub(r"^【[^】]{1,8}】\s*", "", ans).strip()
            if not ans:
                return None
            self._append_mem(role, username, question, ans)
            return "【%s】\n%s" % (role, ans)
        except Exception:
            return None

    # ---------- 群聊编排 ----------
    def start_roles(self, question, username=None):
        """先把角色回复**发出去**，和主回复的生成并行跑

        为什么要有这个方法：
          原来角色回复是串在主回复**后面**的（生成 12 秒 → 再等角色 11 秒），
          一轮回复白白多花十几秒。而角色回复其实不依赖主回复
          （小七/小八/小九 都映射到真实子智能体，走 _role_reply 的路径①，
           那条路径根本不用 main_answer），所以完全可以重叠。
        只预取走路径①的角色 —— 走路径②（LLM 按人设生成）的要用到主回复要点，
        那种还是老实等主回复出来再说。

        返回 {角色: Future}；没有可预取的角色就返回 None。
        """
        try:
            if self.trunk:
                cfg = getattr(self.trunk, "config", {}) or {}
                if cfg.get("群聊模式", True) is False:
                    return None
            roles = [r for r in self.pick_roles(question) if r in self.ROLE_MOD]
            if not roles:
                return None
            if username is None:
                username = self._username()
            ex = ThreadPoolExecutor(max_workers=3)
            futs = {r: ex.submit(self._role_reply, r, question, "", username)
                    for r in roles}
            self._prefetch_ex = ex
            return futs
        except Exception:
            return None

    def compose(self, question, main_answer, username=None, prefetch=None):
        """小6主回复 + 相关角色补充，返回合并文本；无角色命中时原样返回

        prefetch: start_roles() 的返回值。给了就用它（角色回复大概率和
                  主回复同时跑完，这里几乎不用等）。
        """
        # C7: 群聊开关统一传播——模块内再查一次开关，双保险
        if self.trunk:
            cfg = getattr(self.trunk, "config", {}) or {}
            if cfg.get("群聊模式", True) is False:
                return main_answer
        if username is None:
            username = self._username()
        roles = self.pick_roles(question)
        # 主回复统一带【小6】名字（即使无角色补充也带，方便识别是谁在说话）
        parts = ["【小6】\n" + str(main_answer).strip()]
        if not roles:
            return "\n".join(parts)

        prefetch = prefetch or {}
        todo = [r for r in roles if r not in prefetch]
        ex = None
        try:
            futs = {r: prefetch[r] for r in roles if r in prefetch}
            if todo:
                ex = ThreadPoolExecutor(max_workers=3)
                for r in todo:
                    futs[r] = ex.submit(self._role_reply, r, question,
                                        main_answer, username)
            for role in roles:                       # 保持角色顺序
                try:
                    # 预取的那些基本已经好了，给个短上限就够；
                    # 现发的还是给 15 秒
                    seg = futs[role].result(timeout=15 if role in todo else 3)
                except Exception:
                    seg = None
                # D8: 角色回复与主回复重复度过高（Jaccard>0.7）则跳过该角色发言
                if seg and self._jaccard(seg, str(main_answer)) > 0.7:
                    seg = None
                if seg:
                    parts.append(seg)
        finally:
            if ex is not None:
                ex.shutdown(wait=False)
        return "\n\n".join(parts)

    def _jaccard(self, a, b):
        """D8: 两段文本字符级 Jaccard 相似度"""
        if not a or not b:
            return 0.0
        sa = set(str(a))
        sb = set(str(b))
        inter = len(sa & sb)
        union = len(sa | sb)
        return inter / union if union else 0.0

    def run(self, *a):
        return {
            "模块": "真·多智能体群聊",
            "角色": list(self.roles.keys()),
            "说明": "按问题类型并行召集相关角色，各角色独立人设与按账号隔离的记忆",
            "全员触发词": self.all_hint,
        }

