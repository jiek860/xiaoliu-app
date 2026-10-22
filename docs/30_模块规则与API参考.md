# 小6智能体  模块规则与 API 参考

版本：v25.2.23  
更新日期：2026-10-22
文档定位：**开发者查阅模块/规则/能力与 Trunk API 的参考手册。**

> 本文件由原《全模块规则体系》和《API 文档》合并。
> 真正的事实源是代码：`core/lazy_config.py`、`core/rules_engine.py`、
> `core/core_caps.py`、`core/module_caps.py`、`modules_repo/manifest.json`。
> 文档只做导航和核对，代码与测试优先。

---

## 第一部分：模块与规则体系

## 小6 程序全模块规则体系（现状核对版 v2.1）

> ⚠️ **先读这段（2026-10-13 核对后补）**
>
> **这份文档是 v2.0 时期的「规则全景设计稿」，不是现状快照。**
> 它原来写着"文档为唯一事实源"—— 那句话是**错的**。真正的事实源是代码：
>
> ⚠️ 另外：本文里的模块名还是 v7 时期的 `lNN_` 老命名，其中 4 个已机械替换成现行名（personality / self_reflect / forgetting_curve / anomaly_detector）；
> 其余 `l27_empathy` / `l44_intuition` / `l123_preference` / `l124_goal` / `l17_causal` 这几块能力已经并入别的模块，
> **现行模块清单以 `core/lazy_config.py` 的 `LAZY_MAP` 为准**。
>
> | 事实源 | 内容 | 现状 |
> |---|---|---|
> | `core/lazy_config.py` | 模块登记表 | **72 个模块** |
> | `core/rules_engine.py` | 规则定义 | **63 条规则** |
> | `core/core_caps.py` | core 侧能力声明 | 19 条 |
> | `core/module_caps.py` | 能力注册表（合并两来源） | 49 条能力 |
> | `modules_repo/manifest.json` | 插件清单（RSA 签名） | 48 条 |
>
> **本文已知对不上的地方（点名列出，不藏）**
>
> | 位置 | 文档写的 | 实际 |
> |---|---|---|
> | 开头覆盖面 | 43 个注册模块（历史口径） | **72 个** |
> | 别名映射 | `web_learner→proactive_learner` | 这条**已删除**（它指向的 `active_learning` 已退役）；真身从来不是 `proactive_learner` |
> | 别名映射 | （未提） | 实际还有 `model_mode→本地路由` |
> | C 组状态 | 标注"建议"、待落地后参数化 | **8 条都已有实现**（见下表） |
>
> **C 组 8 条的实际状态（2026-10-13 关键词级核对）**
>
> | 编号 | 内容 | 代码里的落点 |
> |---|---|---|
> | C1 | LLM 路由置信度 | `modules/installed/smart_router.py` |
> | C2 | 情景记忆直接接线 | `core/trunk.py` |
> | C3 | 技能沉淀加"确认有用"门 | `modules/installed/skill_capture.py` |
> | C4 | 电脑控制安全白名单 | `modules/installed/computer_controller.py`（28 条白名单 + 默认禁用） |
> | C5 | top_k 参数统一 | `core/config.py` / `core/knowledge_graph.py` |
> | C6 | 自愈 apply 落点明确 | `core/config_healer.py` / `core/self_check.py` |
> | C7 | 群聊模式开关统一传播 | `modules/installed/group_chat.py` |
> | C8 | 嵌入请求节流 | `core/vector_store.py` + 规则 |
>
> 注：C 组是**关键词级**核对（代码里有对应实现），不等于逐条验证过行为。
>
> **这份文档还有用的地方**：五层规则模型（触发→处理→判定→动作→降级/生命周期）
> 与"通用规则"那一节，是理解设计意图的好材料。
> **但涉及"现在有多少条 / 哪些开着"，一律以代码为准。**

> 覆盖：躯干 + 核心模块 + 子智能体 + 全部闭环 + 全部注册模块
> 规则五层模型：**触发 → 处理 → 判定 → 动作 → 降级/生命周期**
> v2.0 变更：A 组 8 处修正（对齐实际代码）+ B 组 11 处补充（代码已有规则入文档）+ C 组 8 条新增优化规则
> 状态：**设计稿**（各条落地情况见上面的核对表）

---

### 〇、规则总览

| 层 | 管什么 | 例子 |
|---|---|---|
| L1 触发 | 什么时候激活 | 强信号词/轮数/定时/事件广播 |
| L2 处理 | 拿到输入怎么做 | 提取/检索/拆分/过滤 |
| L3 判定 | 怎么打分下结论 | 阈值/相似度/置信度/评分 |
| L4 动作 | 命中后执行什么 | 入库/回复/弹窗/调模块 |
| L5 降级+生命周期 | 失败/老化怎么办 | 兜底/冷却/去重/清理/卸载 |

**通用规则（全模块生效）**
- 懒加载：首次 `trunk.call` 才加载，加载失败记日志不崩
- 调用兜底：模块不存在/方法不存在 → 返回 `{"error":...}`，不抛到聊天
- 别名映射（**已按 2026-10-13 的代码更新**）：`errors→error_lib / enhanced_memory→vector_store / file_reader→file_upload / auto_fixer→error_lib / llm_client→llm / model_mode→本地路由`（call 时先转别名）
  - ⚠️ 原文这里还写着 `web_learner→proactive_learner`，**已删除**：真身从来不是 `proactive_learner`，而且它指向的 `active_learning` 已退役、别名本身也一并删掉了
- 崩溃钩子：`sys.excepthook` → 崩溃含 traceback 写入 `data/logs/crashes.log`
- 危险动作：删文件/跑命令/自更新/关机 → 必须先 `trunk.confirm` 弹窗确认
- LLM 可用性：本地→回退主力→云端 三段降级
- 路径规则：一律 `self.base` 动态拼接，禁写死

---

### 一、躯干规则（core/trunk.py，642 行实测）

**定位**：微内核总线，只做"注册/路由/总线/懒加载/模型注入/记忆知识存取/确认钩子/后台接线/自检"。

| 规则项 | 规则 |
|---|---|
| **L1 触发** | ①任何模块调用都经 `trunk.call(模块,方法,参数)`；②事件用 `publish/subscribe` 广播（松耦合）；③后台闭环在 `_start_background` 启动时自动接线；④后台 8 步闭环在每次回复后经 `_bg` 自动执行 |
| **L2 处理** | `call` 流程：别名转换 → 查 `modules` 已注册 → 未注册查 `_lazy` 懒加载 → 加载并缓存 → 调用方法 → 异常捕获返回 `{"error":...}`；`_load_lazy` 优先 `modules/installed`（插件市场），其次 `core/`，都没有则提示"模块未安装" |
| **L3 判定** | 路由判定交给 `smart_router`（关键词≥2 直走 / LLM 判断）→ 复杂任务（意图 task）交 `task_loop`；回复组装顺序见下 |
| **L4 动作** | ①核心注册 5 个启动即注册；②后台服务：scheduler + hot_reload(每 5 分钟扫 .py) 自动启动（任一失败不影响主程序）；③模型注入 `assign_model`：把同一 LLM 实例绑定给需要模型的模块；④记忆/知识库读写封装：`mem_add(去重+200条上限)/mem_recent(5)/kb_add/kb_search/kb_categories`；⑤回复流程见下 |
| **L5 降级+生命周期** | ①模块加载失败 → `_log` 记日志返回 error 不崩；②**双卸载机制**：llm_client watchdog（15s 轮询、120s 空闲 `keep_alive=0` 卸模型省显存）+ 躯干 `_auto_unload_loop`（30s 轮询、**非核心模块** 120s 未用卸模块，调 stop/close/shutdown/cleanup 后 del + 清 sys.modules + gc）；③配置/记忆/知识库全部落盘 `data/`，启动加载变更保存；④深度自检 `_deep_check`：语法编译 + 5 核心模块 + Ollama 模型数 + 云端 + 健康分（Ollama 断 -20 / 云端断 -10） |

**回复组装真实顺序（L4 细化）**
```
1. 电脑控制快速通道（第一优先级）：自然语言 → computer_controller.try_handle
   → 命中则 LLM 把结果整理成一句中文 → mem_add → 直接返回
2. 向量检索：vector_store.search(user_input, top_k=3)
3. 情景记忆：memory_loop.recall(top_k=2, hours=48) → 带 [情景记忆 场景 时间]
4. 知识图谱：knowledge_graph.rag_query(user_input)
5. 历史对话：mem_recent(5)，用户 200 字/助手 100 字截断
6. 人格 few-shot：personality.full_hint + few_shot_examples
7. 调 LLM（三级选模型，见 §2.1）
8. 存记忆 → 群聊 compose（config 群聊模式开）→ _bg 后台 8 步
```

**后台 _bg 8 步（每次回复后自动，全部 try 兜底不阻塞）**
```
① 存向量 vector_store.add
② 存知识图谱 knowledge_graph.add_dialog
③ 反思 self_reflect.reflect(打分+教训)
④ 拟人 personality.sense_feeling + remember_event
⑤ 记忆卡 memory_cards.maybe_summarize(规则级触发)
⑥ 记忆闭环 memory_loop.run(记忆卡→遗忘曲线→到期复习→检索增强)
⑦ 技能捕获：触发词["帮我写|帮我做|帮我实现|写一个|做一个|实现一个|修复|整理一下"]
   且回答不以（/抱歉/出错了 开头 → skill_loop.capture
⑧ 群聊评估 group_loop.evaluate(异常检测) + 任务路由：动词["做|写|实现|开发|设计|搭建|整理|制作|创建|生成"]
   且 len≥8 → smart_router.route → 意图 task → task_loop.run
```

**关键参数**：核心 5 常驻、其余 43 懒加载、非核心模块 120s 卸载、模型 120s 卸载、备份保留 2 个、记忆每人 200 条、历史取 5 轮。

---

### 二、核心模块规则（5 个）

#### 2.1 llm_client（LLM 客户端 v8.0，248 行实测）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 任意模块要模型时调 `chat/stream_chat`；`model_mode` 决定本地路由/云端 |
| L2 处理 | `_pick_model` 三级路由：①带图（messages 含 images）→ VL 视觉模型（qwen3-vl:8b）；②复杂信号 → VL 强模型（HARD_KW 40+ 词：认真/一步步/算法/架构/看图/重构/并发…，或长度>200，或代码块```≥2）；③简单问候（30+ 词表 + <15字）或纯情绪词（嗯/哦/好/哈哈…）→ 小模型；④默认主力 7b |
| L3 判定 | 路由模型失败（空或"本地模型错误"）且非主力 → **回退主力重试 1 次**（日志"路由模型不可用，回退主力"）；本地全挂 → **云端兜底**；云端模式失败 → 重试 1 次（共 2 次，间隔 1s） |
| L4 动作 | `stream_chat` 流式逐 token（on_token）；`_touch` 记录活跃防卸载；云端 URL 自动补 `/chat/completions`；云端不支持 images 时剥离；`inject_persona=False` 群聊子角色跳过小6人格；`force_model` 固定模型跳过路由；人格注入在 `_try_local` 内以 system 消息前缀 |
| L5 降级+生命周期 | 超时：本地 90s / 云端 30s / 嵌入 10s；模型 watchdog：15s 轮询、120s 空闲发 `keep_alive=0` 卸载模型；配置从 config.json 热读（reload_config） |

#### 2.2 vector_store（向量检索 v5.2，88 行实测）
| 规则项 | 规则 |
|---|---|
| L1 触发 | `add` 记忆/知识入库；`search` 检索；线程锁防并发 |
| L2 处理 | **真神经网络嵌入**：nomic-embed-text（`/api/embeddings`，文本截 500 字）→ 余弦相似度 |
| L3 判定 | **时间衰减**：`score *= exp(-age/60)`（60 天半衰期，旧记忆自动降权）；查询缓存命中直接返回 |
| L4 动作 | 返回 `[{text, score, time}]` 供 prompt 注入 |
| L5 降级+生命周期 | 数据 2000 条截断 1000；查询缓存 200 条截 100；嵌入失败 → 返回前 top_k 条 score=0（不空答）；数据落盘 `data/vectors.json` + `data/embeddings.json` |

#### 2.3 auth（三级权限）
| 规则项 | 规则 |
|---|---|
| L1 触发 | `register/login/whoami/list_users`；登录缓存 `data/login_cache.json` |
| L2 处理 | 密码哈希存储；用户名→数据目录隔离 `data/users/<名>/` |
| L3 判定 | 权限等级 1>2>3：1 级可注册 2/3 级；2 级可注册 3 级；3 级只能注册 3 级；游客仅聊天 |
| L4 动作 | 登录成功 → 设置 `current_user` → 恢复该用户记忆/聊天记录 |
| L5 降级+生命周期 | 用户文件损坏 → 重建空库；登录失败返回明确原因不崩 |

#### 2.4 backup（备份恢复）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 定时任务触发 / 自更新前 / 手动调用 |
| L2 处理 | 打包关键数据（config/记忆/知识/用户/聊天记录）到 `data/backups/` |
| L3 判定 | 保留最近 2 个，自动清理更旧备份 |
| L4 动作 | 恢复时全量回滚数据目录 |
| L5 降级 | 备份失败记日志，不阻断主流程 |

#### 2.5 knowledge_graph（知识图谱）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 对话入库 `add_dialog`（_bg 第②步）/ 显式查询 / `rag_query`（回复组装第 4 步） |
| L2 处理 | 实体-关系-实体三元组存 `data/graph.json`；`multi_hop` 沿关系跳转 |
| L3 判定 | 实体相似合并；查询按相关度排序 |
| L4 动作 | 结果注入 prompt；RAG 检索时提供图谱上下文 |
| L5 降级+生命周期 | 0 三元组时查询返回空，不报错；图谱可视化可导出 |

---

### 三、子智能体规则（3 个）

#### 3.1 agent_coder（编程小匠·小七）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 智能路由判 `code` / 群聊 ROLE_MOD 命中编程 / 用户点名小七 |
| L2 处理 | 先检索代码相关记忆/知识库 → 生成代码 → 可交 `code_runner` 沙盒验证 |
| L3 判定 | 代码正确性靠沙盒跑通；复杂任务拆子步骤 |
| L4 动作 | 聊天框回复代码块；可调 `code_runner` 执行 |
| L5 降级 | LLM 失败 → 返回示例模板，不空答 |

#### 3.2 agent_analyst（分析官·小八）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 路由 `analysis` / 群聊分析类问题 |
| L2 处理 | 检索数据/记忆/知识 → 因果/对比/归因分析 |
| L3 判定 | 结论给证据和置信度，避免臆断 |
| L4 动作 | 结构化回复（结论+依据+建议） |
| L5 降级 | 无数据 → 明确说"需要数据"，不编数字 |

#### 3.3 agent_planner（策划师·小九）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 路由 `planner` / 群聊方案策划 |
| L2 处理 | 目标拆解 → 步骤/资源/风险 → 时间线 |
| L3 判定 | 步骤可执行性检查（每步有动作和产出） |
| L4 动作 | 方案式回复；复杂目标交 `task_loop` 执行 |
| L5 降级 | 目标不清 → 反问澄清 |

---
### 四、闭环模块规则（6 个编排者）

> 闭环特点：编排者只当"指挥"，具体活全部 `trunk.call` 给模块；每步成败记录，失败即中止/回滚。

#### 4.1 learning_loop（学习闭环 v13.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 启动自动接线；`start_continuous(interval=60)` 连续学习线程；手动 `run(topic)` 指定主题；学习完一个立即学下一个 |
| L2 处理 | ①`collect_gap` 找知识缺口：**5 方向轮换** `["小6项目实战","拟人化","自主化","自我进化","多智能体认知"]`，方向内主题 `topic_idx` 轮换 → ②`fetch` 深度搜索（deep_search：官网→论坛→论文）→ ③`store` 提炼入库（写知识文档 + 入向量）→ ④`report` 记录 |
| L3 判定 | 方向内主题轮完 → `dir_idx+1` 切下一方向；搜索结果无有效内容 → 换源重试 1 次 |
| L4 动作 | 结果写 `data/learning.json` + 知识文档 `data/knowledge_docs/`；日志"①方向②缺口③提炼④入库" |
| L5 降级+生命周期 | 搜索失败 → 记日志跳过本轮；连续学习：**学完一个休息 interval(60s) 冷却（LLM 防抖），然后立即学下一个**，不固定总时间；学习记录持久化，重启续学；`stop_continuous` 可停 |

#### 4.2 self_heal（自愈闭环 v12.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 启动自动接线；`run()` 手动触发；错误库新增未修复错误时 |
| L2 处理 | ①`scan`：`error_lib.list` 取"未修复"数，0 则直接结束 → ②`analyze` LLM 分析原因+给修复方案 → ③`verify` 沙盒验证方案 → ④`confirm` 弹窗确认 → ⑤`apply` 应用修复（见 C6）→ ⑥回滚兜底 |
| L3 判定 | 无未修复错误 → 直接结束；方案验证失败 → 不应用、记录失败原因 |
| L4 动作 | 弹窗确认（危险操作钩子）；修复成功把错误标记已修复 |
| L5 降级+生命周期 | LLM 不可用 → 用规则匹配常见错误给建议；应用后冒烟失败 → 自动回滚备份 |

#### 4.3 memory_loop（记忆闭环 v12.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 每次回复后 `_bg` 第⑥步自动调用；手动 `run(user_text, answer)` |
| L2 处理 | ①`summarize` 记忆卡总结（规则级：强信号/情绪/话题切换/轮数）→ ②`schedule` 遗忘曲线排期 → ③`do_review` 到期复习（forgetting_curve.due_review）→ ④`enhance` 检索增强；**run 内自动 `remember_scene`（5 类情景：编程/学习/系统/情感/闲聊 + 时间戳）** |
| L3 判定 | 记忆卡去重 Jaccard≥0.55；复习到期才触发；情景记忆 48h 内活跃 |
| L4 动作 | 卡入库 `memory_cards.jsonl`；复习结果回写遗忘曲线；`recall(query, top_k=3, hours=48)` 综合检索（向量+情景+时间戳）供 prompt 注入 |
| L5 降级+生命周期 | LLM 失败 → 规则提取兜底；复习无到期 → 跳过；遗忘曲线按艾宾浩斯衰减，超期清理 |

#### 4.4 task_loop（任务闭环 v12.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | **触发链**：`_bg` 动词命中（做/写/实现/开发/设计/搭建/整理/制作/创建/生成）且 len≥8 → `smart_router.route` → 意图 `task`（路由 task 关键词：任务/拆/怎么做/帮我做/计划）→ `task_loop.run`；手动 `run(goal)`；系统页按钮 |
| L2 处理 | ①`plan` LLM 拆步 → ②`_pick_agent` 按步骤挑子智能体（代码→小七/分析→小八/策划→小九）→ ③`exec_step` 逐步执行 → ④`verify` 沙盒验证 → ⑤`score` 质量评分 → ⑥`record` 回填 |
| L3 判定 | 每步验证通过才进下一步；步骤失败 → 重试 1 次或标记跳过；总评分决定是否算完成 |
| L4 动作 | 结果入库 `data/tasks.json`；日志"①拆成N步…⑥评分"；断点续做（记录已执行步骤） |
| L5 降级+生命周期 | 无目标 → 返回需要目标；LLM 拆步失败 → 单步整做；结果可复查 |

#### 4.5 skill_loop（技能沉淀闭环 v12.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | `_bg` 第⑦步：触发词命中（帮我写/帮我做/帮我实现/写一个/做一个/实现一个/修复/整理一下）且回答不以（/抱歉/出错了 开头 → 自动捕获；手动 `run(task, result)` |
| L2 处理 | ①`capture` 成功任务→写 SKILL.md（步骤+要点+可复用模板）→ ②`search` 按需检索 → ③`build_prompt` 注入下次 prompt |
| L3 判定 | 仅成功任务捕获；重复技能去重（同名覆盖更新） |
| L4 动作 | SKILL 存 `data/skills/`；prompt 自动带上相关技能 |
| L5 降级+生命周期 | 捕获失败记日志；技能超量按最近使用清理 |

#### 4.6 group_loop（群聊闭环 v12.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | `_bg` 第⑧步：config 群聊模式开时 `evaluate` 异常检测；`run(question, main_answer)` 手动 |
| L2 处理 | ①`route` 路由意图 → ②`compose` 群聊组合：按问题挑子智能体/主智能体回答 + 补充 → ③`evaluate` 异常检测评估（l135）→ ④`feedback` 反馈回写路由 |
| L3 判定 | 路由置信度低 → 主智能体答；回答异常（空/重复/偏离）→ 标记并回写 |
| L4 动作 | 群聊结果入库；路由反馈更新权重 |
| L5 降级+生命周期 | 子智能体模块缺失 → 回退主 LLM 人设回复，不崩 |

---

### 五、功能模块规则（搜索/工具/文件/系统类）

#### 5.1 deep_search（深度搜索 v7.3，103 行实测）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 路由判"联网/最新/官网/论坛/论文"；学习闭环 fetch 调用；用户点"深度搜索"按钮 |
| L2 处理 | **多源顺序**：Bing 国内（gzip 解压）5 条 → 空则 DuckDuckGo 5 条 → 代码类查询（_is_code_query）追加 GitHub → 结果 `_read_page` 读取详情 + LLM 总结 |
| L3 判定 | 官网/官方文档优先；论坛次之；无有效结果 → 换源重试 1 次 |
| L4 动作 | `run` 返回 `{"结果":[...], "总结":..., "数量":n, "查询":...}` |
| L5 降级+生命周期 | 网络失败 → 返回空 + 日志；**节流为建议规则（当前未实现，见 C8）** |

#### 5.2 tool_caller（工具调用 v10.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 聊天主流程经 LLM 判断需要工具时（不靠关键词硬编码） |
| L2 处理 | LLM 决定用哪个工具（天气/计算/日历/搜索/文件…）→ 组装参数 → 调 `trunk.call` |
| L3 判定 | 工具返回无效 → 换工具或明说不能做 |
| L4 动作 | 结果拼回回复；成功经验记录（结果学习） |
| L5 降级 | LLM 不可用 → 关键词路由兜底 |

#### 5.3 code_runner（代码执行·沙盒 v7.0，40 行实测）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 编程回复要验证；自愈/任务闭环验证阶段；用户点"沙盒跑代码" |
| L2 处理 | 代码写入 `data/staging/` 隔离目录 → 子进程执行 → 捕获输出/错误/超时 |
| L3 判定 | 退出码 0 + 无异常 → 通过；超时/报错 → 失败带回显 |
| L4 动作 | 返回 {ok, output, error}；不碰系统真实目录 |
| L5 降级+生命周期 | **默认超时 timeout=10s（可传参）**；危险命令拦截为建议规则（见 C4）；执行超时强杀 |

#### 5.4 computer_controller（电脑控制 v11.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | **主流程第一优先级**：`_reply_inner` 开头 `try_handle(user_input)`；用户明确要求"打开设置/建文件/删文件"等 |
| L2 处理 | 白名单命令（`start` 打开 ms-settings 等）→ 执行前 `trunk.confirm` 弹窗（建议强化白名单，见 C4） |
| L3 判定 | 非白名单/危险操作 → 拒绝并说明 |
| L4 动作 | 真实执行 → LLM 把结果整理成一句中文 → `mem_add` → 直接返回（不进正常回复流程） |
| L5 降级 | 命令不存在 → 返回具体错误；try_handle 未命中 → 正常回复流程 |

#### 5.5 file_upload（文件上传解析 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 用户上传文件/点文件按钮 |
| L2 处理 | 按扩展名分流：PDF（pdfplumber）→ Word（docx）→ Excel（openpyxl）→ TXT → 提取文本 |
| L3 判定 | 无法解析格式 → 明确报错提示 |
| L4 动作 | 文本入上下文/入库，可继续问答 |
| L5 降级 | 大文件截断（限长），二进制跳过 |

#### 5.6 proactive_learner（主动学习 v10.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 定时任务（scheduler 默认周期）；用户点"主动学习" |
| L2 处理 | LLM 找知识缺口 → 定时联网搜 → 提炼评分 → 自动入库 |
| L3 判定 | 评分低于阈值不收录；与已有知识重复跳过 |
| L4 动作 | 入库 `data/learning.json` + 日志报告 |
| L5 降级 | 无网/LLM 失败 → 本轮跳过，下轮再试 |

#### 5.7 rag_engine（知识问答 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 用户问题含知识查询意图/路由判 RAG |
| L2 处理 | 向量检索 → 知识图谱补充 → LLM 总结作答 |
| L3 判定 | 检索无结果 → 转联网或明说无库内知识 |
| L4 动作 | 回答附来源 |
| L5 降级 | LLM 失败 → 直接展示检索原文 |

#### 5.8 reasoning_engine（推理引擎）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 路由判"复杂逻辑/数学/多因素判断" |
| L2 处理 | 真思维链：逐步推理 → 多路径对照 → 结论 |
| L3 判定 | 路径矛盾 → 选证据多的；无把握 → 标不确定 |
| L4 动作 | 分步展示推理过程 |
| L5 降级 | LLM 失败 → 直接给结论不展开 |

#### 5.9 mcp_server（MCP 服务 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 外部 MCP 客户端连接（标准协议） |
| L2 处理 | 暴露程序能力（记忆/知识/搜索）为 MCP 工具 |
| L3 判定 | 校验客户端身份/请求格式 |
| L4 动作 | 返回标准 MCP 响应 |
| L5 降级 | 协议错误 → 拒绝连接记日志 |

#### 5.10 multimodal（多模态 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 用户发图片且要理解内容 |
| L2 处理 | 图片转 base64 → Ollama 视觉模型（qwen3-vl:8b）理解 |
| L3 判定 | 无视觉模型 → 明确提示 |
| L4 动作 | 返回图片内容描述入上下文 |
| L5 降级 | 模型缺失 → 提示"需安装视觉模型" |

#### 5.11 voice（语音 v8.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 语音按钮：TTS（文字转语音）/ STT（语音转文字） |
| L2 处理 | TTS: edge-tts 合成；STT: faster-whisper 识别 |
| L3 判定 | 无网/无模型 → 明确报错 |
| L4 动作 | 播放/转写结果入聊天 |
| L5 降级 | 服务不可用 → 提示安装依赖 |

#### 5.12 plugin_market（插件市场 v1.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 打开插件市场页 / install/uninstall |
| L2 处理 | 扫 `modules/installed` + `modules_repo` 列插件 → 安装校验（语法+接口）→ 失败回滚 → 卸载迁 `data/plugin_backups/` |
| L3 判定 | 重复插件拒绝；语法错误拒绝装 |
| L4 动作 | 装/卸成功后热生效（懒加载可感知）；需要模型的新插件自动 `assign_model` |
| L5 降级+生命周期 | 安装失败自动回滚原文件；卸载可恢复 |

#### 5.13 hot_reload（热重载 v5.1）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 启动自动 `auto_reload()`（每 5 分钟扫 .py 变化）；手动触发 |
| L2 处理 | 新代码先沙盒验证（import 试跑）→ 通过才替换 → 失败弹窗报错不加载 |
| L3 判定 | 语法/导入失败 → 拒绝加载并提示 |
| L4 动作 | 替换模块 + 刷新注册 |
| L5 降级+生命周期 | 验证失败保留旧版；每次更新前自动备份 |

#### 5.14 scheduler（定时任务 v10.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 程序启动自动启动；按配置周期触发（备份/主动学习/巡检/热更新检测/连续学习/到期复习） |
| L2 处理 | 到点调对应模块；任务间不互阻塞（线程） |
| L3 判定 | 单任务失败不影响其他 |
| L4 动作 | 全部记日志 |
| L5 降级+生命周期 | 任务异常 → 记日志跳过本次；配置可改 |

#### 5.15 self_system（自检系统 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 一键自检按钮 / 定时巡检 |
| L2 处理 | 收集：模块注册数/数据库文件/配置/LLM 连接/错误数 → LLM 自我评价 |
| L3 判定 | 缺模块/断连/错误堆积 → 标红提示 |
| L4 动作 | 输出自检报告到聊天/日志 |
| L5 降级 | 单项检查失败不中断其他项 |

#### 5.16 auto_updater（自动更新 v12.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 定时检测新版本 / 手动触发 |
| L2 处理 | 取问题→LLM 分析→编程小匠产补丁→code_runner 隔离副本跑全量检查→弹窗确认→全量备份→替换→hot_reload→失败回滚 |
| L3 判定 | 沙盒验证不过 → 中止；冒烟失败 → 回滚 |
| L4 动作 | 更新结果日志 + 弹窗 |
| L5 降级+生命周期 | 全程备份可回滚；更新前自动备份 |

#### 5.17 auto_trainer（自动训练）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 定时收集聊天记录触发 |
| L2 处理 | 收集对话 → 清洗成训练数据 → 生成微调数据文件 |
| L3 判定 | 无效/超短对话跳过 |
| L4 动作 | 数据存 `data/training/`，供外部微调 |
| L5 降级 | 无新对话 → 跳过 |


---
### 六、L 系列模块规则（认知层）

#### 6.1 self_reflect（自我反思 v7.1）
| 规则项 | 规则 |
|---|---|
| L1 触发 | `_bg` 第③步：每次回复完成后自动（reflect(user_input, answer)） |
| L2 处理 | LLM 给回答打分（0-10）+ 教训 + 改进点 |
| L3 判定 | 打分<6 → 记录教训，影响下次 prompt；≥6 → 只记录 |
| L4 动作 | 教训入 `data/reflections.json`；下次回复注入 |
| L5 降级 | LLM 失败 → 规则打分兜底（空答/超短/报错自动低分） |

#### 6.2 l27_empathy（共情）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 用户文本命中情绪词/求助语 |
| L2 处理 | 先共情回应（语气/关怀）再接问题 |
| L3 判定 | 强负面情绪 → 优先安抚 |
| L4 动作 | 回复带共情前缀 |
| L5 降级 | 无法判断 → 正常回复 |

#### 6.3 forgetting_curve（遗忘曲线 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 记忆入库时排期；复习调度器到期 |
| L2 处理 | 按艾宾浩斯间隔（1/7/30 天）排复习；到期调复习（`due_review`） |
| L3 判定 | 复习成功 → 延长间隔；失败 → 缩短 |
| L4 动作 | 到期提醒/复习任务入队 |
| L5 降级+生命周期 | 超期未复习 → 降权；旧记忆自动衰减 |

#### 6.4 l44_intuition（直觉 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 信息不足但需快速判断（LLM 生成"直觉提示"） |
| L2 处理 | 基于历史相似场景给倾向性建议 |
| L3 判定 | 只作参考不覆盖事实 |
| L4 动作 | 回复附"我的直觉判断" |
| L5 降级 | 无历史 → 不输出直觉 |

#### 6.5 l123_preference（偏好学习 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 对话中检测到偏好表达（我喜欢/我习惯/我常） |
| L2 处理 | LLM 提取偏好 → 记忆 → 回复自适应 |
| L3 判定 | 与旧偏好冲突 → 新的覆盖 |
| L4 动作 | 偏好库更新，回复风格/内容适配 |
| L5 降级 | LLM 失败 → 关键词提取 |

#### 6.6 l124_goal（目标管理 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 对话中出现目标（我要做到/目标是） |
| L2 处理 | LLM 跟踪目标 → 记录进度 → 到期提醒 |
| L3 判定 | 目标过期/完成 → 归档 |
| L4 动作 | 聊天提醒目标进度 |
| L5 降级 | 无法解析 → 不打扰 |

#### 6.7 anomaly_detector（异常检测 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 每次回复生成后（群聊闭环 evaluate 调用） |
| L2 处理 | LLM 判断回答是否异常（空/重复/跑题/幻觉） |
| L3 判定 | 异常 → 标记 + 触发重答 |
| L4 动作 | 异常结果反馈给路由/反思 |
| L5 降级 | LLM 失败 → 规则检查（长度/重复度） |

#### 6.8 l17_causal（因果分析 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 问题含"为什么/导致/因为" |
| L2 处理 | LLM 构建因果链（因→果→影响） |
| L3 判定 | 多因时按相关性排序 |
| L4 动作 | 因果链式回答 |
| L5 降级 | LLM 失败 → 常识规则 |

#### 6.9 personality（人格引擎 v2.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 每次回复组装 prompt 时（强制注入：`full_hint` + `few_shot_examples`）；`_bg` 第④步 `sense_feeling` + `remember_event` |
| L2 处理 | 强指令 + 对话示例 + 心境驱动 + 主动提议 |
| L3 判定 | 心境（积极/平静/谨慎）随对话起伏 |
| L4 动作 | 回复带小6 人格（去 AI 味、口语化、会承认错误） |
| L5 降级 | 无（纯 prompt 规则，无 LLM 依赖） |

---

### 七、其他模块规则

#### 7.1 error_lib（错误库 v10.0，75 行实测）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 任何模块报错时自动记录（`log` 方法） |
| L2 处理 | 存错误信息/时间/来源/堆栈 → `analyze` LLM 分析原因+给修复方案 → `auto_fix` 沙盒验证 |
| L3 判定 | 未修复标红；修复成功标记已修复；**错误上限 500 截 300** |
| L4 动作 | 日志显示；自愈闭环 scan 来源（list→未修复数） |
| L5 降级+生命周期 | 只保存未修复 + 当天错误；修复后删除相关日志；LLM 失败存原始错误 |

#### 7.2 predictive（预测 v7.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 用户消息后预测下一步意图 |
| L2 处理 | LLM 基于上下文给 2-3 个可能下一步 |
| L3 判定 | 高置信预测主动提议 |
| L4 动作 | 回复末尾附"你可能想问…" |
| L5 降级 | 低置信不输出 |

#### 7.3 group_chat（群聊引擎 v16.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 回复组装第 8 步：config 群聊模式开时 `compose(user_input, answer)`；群聊闭环 compose 调用 |
| L2 处理 | 按路由挑子智能体组队 → 组合多角色回答 |
| L3 判定 | 问题类型决定参与角色（编程→小七等） |
| L4 动作 | 多角色分段回复（群聊感） |
| L5 降级 | 子智能体缺失 → 主 LLM 全答 |

#### 7.4 smart_router（智能路由 v10.0，87 行实测）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 每条用户消息进入主流程；`_bg` 第⑧步任务判定 |
| L2 处理 | **路由链：缓存 → 关键词计分 → LLM 判断 → 缓存写回**；10 意图表：code/analysis/planner/search/task/tool/causal/reflect/emotion/greet → 模块映射 |
| L3 判定 | **关键词命中≥2 → 高置信直走（方法=keyword）**；否则 LLM 判断（方法=llm）；**无 0.6 数值阈值**（建议加置信度，见 C1） |
| L4 动作 | 路由到：小6/小七/小八/小九/任务闭环/联网；**仅 keyword 结果写缓存**（500 上限截 200，防 LLM 错误固化）；LLM 结果不落盘 |
| L5 降级+生命周期 | LLM 失败 → 返回 greet；`feedback` 反馈学习：权重 +0.1 + 删缓存 |

#### 7.5 task_planner（任务规划 v10.0）
| 规则项 | 规则 |
|---|---|
| L1 触发 | task_loop plan 调用；复杂目标 |
| L2 处理 | LLM 拆多步 → 并行执行 → 子智能体委派 → 断点续做 |
| L3 判定 | 步骤依赖检查；每步可独立验证 |
| L4 动作 | 步骤清单回填任务闭环 |
| L5 降级 | 拆步失败 → 单步整做 |

#### 7.6 skill_capture（技能捕获）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 任务成功完成（_bg 第⑦步触发词命中） |
| L2 处理 | 记录任务/步骤/产出 → 写 SKILL.md |
| L3 判定 | 仅成功/有复用价值任务 |
| L4 动作 | SKILL 入库供检索 |
| L5 降级 | 捕获失败忽略 |

#### 7.7 memory_cards（记忆卡 v2 规则级）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 4 类信号：轮数%5==0 / 强信号词(30+)/ 情绪词 / 话题切换(交集≤3)；`_bg` 第⑤步 + 记忆闭环调用 |
| L2 处理 | LLM 分类提取（偏好/计划/事实/情感/关系）→ 失败规则提取兜底 |
| L3 判定 | Jaccard≥0.55 判重复跳过；分类标签必带 |
| L4 动作 | 入 `memory_cards.jsonl`；hint 时间衰减检索（7 天内优先+价值加权）带 3 张卡入 prompt |
| L5 降级+生命周期 | LLM 失败规则卡；线程锁防并发；超量按时间清理 |

#### 7.8 enhanced_memory（增强记忆）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 记忆闭环/检索增强调用 |
| L2 处理 | 多维度记忆整合（短期+长期+情景） |
| L3 判定 | 相关度排序取 top_k |
| L4 动作 | 注入 prompt 上下文 |
| L5 降级 | 空记忆返回空 |

---

### 八、交叉规则（总线调用矩阵）

| 调用方 | 经 trunk 调 | 触发条件 |
|---|---|---|
| 聊天主流程 | computer_controller.try_handle（第一优先级）→ smart_router → 子智能体/task_loop/联网 | 每条消息 |
| 回复组装 | vector_store + memory_loop.recall + knowledge_graph + personality + llm | 每条消息固定顺序 |
| 回复完成后 _bg | vector_store + knowledge_graph + self_reflect + personality + memory_cards + memory_loop + skill_loop + group_loop + smart_router→task_loop | 每次回复后 8 步 |
| 任务闭环 | task_planner + agent_* + code_runner + skill_capture | 路由意图 task |
| 学习闭环 | deep_search + rag_engine + proactive_learner | 定时/手动 |
| 自愈闭环 | error_lib + agent_coder + code_runner + hot_reload + backup | 扫描到未修复错误 |
| 定时任务 | backup + proactive_learner + self_system + hot_reload + learning_loop + forgetting_curve | scheduler 周期 |
| 自更新 | error_lib + agent_coder + code_runner + backup + hot_reload | 检测到更新 |

---

### 九、C 组新增优化规则（建议，待落地规则引擎参数化）

| # | 规则 | 现状 | 规则设计 |
|---|---|---|---|
| C1 | **LLM 路由置信度** | 关键词≥2 直走 / 否则 LLM，无置信度字段 | LLM 判断时输出 0-1 置信度；`置信度 < 0.6` → 回主 LLM 兜底不硬路由；可调参数 `router.conf_threshold=0.6` |
| C2 | **情景记忆直接接线** | 只经记忆闭环 run 间接记录 | `_bg` 直接调 `memory_loop.remember_scene`，记忆闭环被禁时情景记忆不断线 |
| C3 | **技能沉淀加"确认有用"门** | 触发词+回答正常就捕获 | 回复后用户点"有用"→ 才 `skill_loop.capture`；未确认只暂存待定区；防垃圾技能堆积 |
| C4 | **电脑控制安全白名单** | try_handle 在主流程最前，无白名单边界 | 白名单：`start * / 打开ms-settings / 读文件 / 写 data/ 目录`；删文件/写系统目录/关机 → 必须 `trunk.confirm` 弹窗，未确认不执行 |
| C5 | **top_k 参数统一** | trunk=3 / vector_store 默认 5 / 记忆闭环=3 | 统一配置项 `retrieval.top_k`，一处改全局生效 |
| C6 | **自愈 apply 落点明确** | verify 后 apply 未明确"应用什么" | 二选一：①真改代码（先备份目标文件 → hot_reload → 失败回滚）；②仅标记已修复。默认②，升级到①需弹窗确认 |
| C7 | **群聊模式开关统一传播** | 仅 group_chat/group_loop 用 config 群聊模式 | 开关同时控制：群聊组合 + 异常评估 + 子智能体参与，统一入口 config["群聊模式"] |
| C8 | **嵌入请求节流** | 每次向量 search 都调 Ollama embedding | 查询缓存命中直接返回；embedding 请求 200ms 最小间隔；短时间重复查询不重复调 |

---

### 十、可调参数总表（落地后进 data/rules/*.json）

| 参数 | 默认 | 作用 |
|---|---|---|
| 记忆卡 min_rounds | 5 | 轮数触发阈值 |
| 记忆卡 dup_threshold | 0.55 | 去重 Jaccard 阈值 |
| 记忆卡 hint_limit | 3 | 注入最大卡数 |
| 记忆卡 decay_days | 7 | 时间衰减高优先级窗口 |
| 学习 interval | 60s | 连续学习轮间 LLM 冷却 |
| 模型 idle_timeout | 120s | 空闲卸载（llm watchdog） |
| 模块 idle_timeout | 120s | 非核心模块空闲卸载（躯干） |
| 路由关键词阈值 | 2 | 关键词命中数≥2 直走 |
| 路由 conf_threshold | 0.6（建议） | LLM 置信度下限（C1） |
| 任务触发长度 | 8 | 动词命中且 len≥8 进路由 |
| 任务重试次数 | 1 | 步骤失败重试 |
| code_runner 超时 | 10s | 沙盒强杀上限 |
| 向量衰减半衰期 | 60 天 | score *= exp(-age/60) |
| 向量数据上限 | 2000/截1000 | 容量截断 |
| 查询缓存 | 200/截100 | 缓存容量 |
| 备份保留数 | 2 | 自动清理旧备份 |
| 记忆每人上限 | 200 | mem_add 截断 |
| 历史注入轮数 | 5 | mem_recent 默认 |
| 情景记忆窗口 | 48h | 活跃记忆 |

> 本文档 v2.0 为唯一事实源（已对齐实际代码）。C 组规则确认后落地 `core/rules_engine.py` + `data/rules/*.json`。

---

### 文档同步记录（2026-10-19 / v25.2.23）

本次同步内容：

- UI 简单/高级模式、头像 5 项菜单、高级模式更多菜单。
- 统一任务中心、任务结果卡片和失败下一步引导。
- 左栏滚动与模块（N）数量提示。
- 自动补报误报修复；日志摘要只读取最近一次启动后的 faulthandler。
- 验证：1026 passed，2 skipped；按钮预算 119/119；静默失败 341/372。

---

## 第二部分：API 参考

## 小6智能体  API 文档

版本：v25.2.23  
更新日期：2026-10-19

### 一、核心入口

```python
from core.trunk import Trunk

t = Trunk()
t.reply("你好")
t.call("deep_search", "search", "今天天气")
t.get_cfg("model_mode", "本地路由")
t.get_llm()
t.get_permission_center()
t.get_net_guard()
t.get_task_runtime()
```

### 二、安全相关 API

#### PermissionCenter

```python
pc = t.get_permission_center()

pc.authorize("code_run", info={"confirm": True, "danger": True}, args={})
pc.approve("tool:fs_edit", scope="session")
pc.revoke("perm_xxx")
pc.lockdown(True)
pc.list_rules()
pc.list_audit(limit=100)
```

#### NetGuard

```python
ng = t.get_net_guard()

d = ng.check("https://open.bigmodel.cn/...", module="llm_client",
             purpose="cloud_model")
ng.open(url, module="deep_search", purpose="web_search", max_bytes=2 * 1024 * 1024)
ng.approve("example.com", scope="once")
ng.list_recent(100)
```

默认拦截：

- `file://` / `ftp://` / 非 HTTP(S)
- 私有 IP、回环地址、云元数据地址
- 未授权域名

本地模型/MCP 端口通过 `purpose="local_model"` / `"local_mcp"` 放行。

#### 代码沙箱

```python
from core.sandbox import run_python

r = run_python("print(1 + 1)", timeout=10)
# {"ok": True, "stdout": "2\n", "stderr": "", "returncode": 0, ...}
```

#### 审计

```python
from core.audit_log import AuditLog

a = AuditLog(t.base)
a.append({"subject": "tool:fs_edit", "decision": "allow", "result": "ok"})
a.list_recent(100)
a.export_redacted("data/security/audit_export.json")
```

### 三、任务运行时

```python
rt = t.get_task_runtime()

task = rt.create("整理项目里的重复记忆")
rt.plan(task["id"])
rt.start(task["id"])
rt.pause(task["id"])
rt.resume(task["id"])
rt.cancel(task["id"])
rt.retry_step(task["id"], "step_1")
rt.list_tasks()
rt.get_task(task["id"])
```

任务落盘：`data/task_runtime/{task_id}.json`

### 四、文档与检索

```python
from core.document_parser import parse, chunk_text
from core.retrieval import HybridRetriever

r = parse("docs/30_模块规则与API参考.md")
chunks = chunk_text(r["text"], chunk_size=800, overlap=120)

idx = HybridRetriever(t.base)
idx.add("小6 是一个桌面智能体", source="README.md")
hits = idx.search("小6", top_k=5)
```

### 五、记忆与工作区

```python
from core.memory_manager import MemoryManager
from core.workspace import Workspace

mm = MemoryManager(t)
rec = mm.add("用户喜欢简洁回答", source="对话", confidence=0.9)
mm.edit(rec["id"], text="用户喜欢直接、简洁的回答")
mm.forget(rec["id"])

w = Workspace(t, "work")
w.knowledge_dir()
w.path("notes", "todo.txt")
```

### 六、模型、用量与插件治理

```python
from core.model_registry import ModelRegistry
from core.usage_tracker import UsageTracker
from core.plugin_governance import PluginGovernance

mr = ModelRegistry(t)
mr.register("qwen2.5:3b", kind="local", context=4096)
mr.health("qwen2.5:3b")

UsageTracker(t.base).summary(days=7)

PluginGovernance(t.base).history()
```

### 七、模块调用约定

```python
# 普通模块调用
t.call("module_name", "method_name", arg1, arg2)

# 工具调用必须经过 tool_caller / PermissionCenter
tc = t._load_lazy("tool_caller")
tc._dispatch(info, args, query, tool_name)
```

模块之间不要互相 import；通过 `Trunk.call()` 走星型拓扑。

### 八、LAZY_MAP 与能力

- 模块登记：`core/lazy_config.py` 的 `LAZY_MAP`，当前 72 个。
- 规则定义：`core/rules_engine.py`，当前 63 条。
- 能力注册：`core/module_caps.py`，当前 49 条。
- 插件清单：`modules_repo/manifest.json`，当前 48 条。

新增能力时：

1. 在模块源码里写 `TOOLS`，或在 `core/core_caps.py` 声明；
2. 同步更新 `docs/30_模块规则与API参考.md` 的能力数；
3. 跑 `tests/test_docs_consistency.py`。

---

### 文档同步记录（2026-10-19 / v25.2.23）

本次已与当前代码同步，重点变化：

- **UI 双模式**：简单模式保留聊天、任务、资料、设置和输入区；高级模式恢复全部低频入口。
- **头像菜单固定 5 项**：切换模式、检查更新、设置、登录/切换账号、帮助。
- **更多菜单**：高级模式显示，按任务 / 资料 / 工具 / 安全 / 插件-MCP / 开发 / 帮助分组，并自动去重。
- **左侧栏可滚动**：模块区显示模块（N）；无模块按钮时显示暂无模块按钮。
- **统一任务中心**：输入框聊天/任务切换、复杂请求提示、任务结果卡片、失败下一步引导。
- **自动补报误报修复**：先快照旧 `.running`，再写当前进程标记，并检查 pid 是否存活；日志摘要只读取最近一次启动后的 faulthandler。
- **验证基线**：1026 passed，2 skipped；按钮预算 136/136；静默失败检查 339/372。


### GUI / 任务运行时新增接口（2026-10-19）

```python
# UI 模式
from gui.ui_mode import UIModeManager, get_ui_mode, set_ui_mode
from core.feature_registry import (
    SIMPLE, ADVANCED, primary_features, feature_ids_for_mode,
    AVATAR_MENU_IDS, MORE_MENU_GROUPS,
)

# 任务运行时
rt = trunk.get_task_runtime()
task = rt.create("整理资料并生成报告")
rt.plan(task["id"])
rt.start(task["id"])
rt.increase_budget(task["id"], seconds=120, steps=4, tokens=5000)
```

说明：

- `trunk.get_task_runtime()` 是全局唯一任务运行时入口。
- `TaskRuntime.increase_budget()` 用于超时/预算不足后的增加预算并继续。
- `gui/guidance.py` 提供失败状态到唯一下一步的映射。
- 头像菜单只用 `AVATAR_MENU_IDS`（4 个：update/settings/login/tutorial）；其余入口由 `MORE_MENU_GROUPS` 分组生成。
- `FEATURES` 共 41 个，`MORE_MENU_GROUPS` 只收录 28 个，剩 13 个走主界面按钮。
- 不加 `MORE_MENU_GROUPS` 时 Ctrl+K 命令面板能搜到，但"更多"菜单里看不到。


### 新增 UI 入口的正确写法（2026-10-22）

加一个新窗口入口需要同时改 4 个地方，少一个都看不到或报错：

```python
# 1. core/feature_registry.py 的 _FEATURES list 末尾 append：
Feature("deep_research", "深度研究", "🔬", "资料", (ADVANCED,), 235,
        False, "多跳联网研究，带引用报告", "", "open_research_dialog"),

# 2. MORE_MENU_GROUPS 对应分组的 tuple 里加 id（不加则菜单里看不到）：
("资料", ("knowledge_base", "history", "memory", "search", "stats",
          "knowledge_graph", "deep_research")),   # ← 加在这里

# 3. core/lazy_config.py 的 LAZY_MAP 加一行：
"deep_research": ("deep_research", "DeepResearch", "深度研究"),

# 4. 新 GUI 窗口 gui/xxx_dialog.py：
#    - 子线程不碰 Qt 控件（check_threads.py 会拦）
#    - 按钮数触发 check_buttons.py 棘轮（只许降不许升）
#    - 新文件不超 600 行（check_file_sizes.py）
#    - 新工具必须声明 hints 字段（check_tools.py 强制）
```

注意：
- `SIMPLE_PRIMARY_IDS` 固定 7 个（简单模式首屏按钮），不要随便加。
- `AVATAR_MENU_IDS` 固定 4 个，不要随便加。
- 按钮预算是棘轮：新文件不在 per_file 里直接报"新增"失败。确认必要后跑 `check_buttons.py --rebase` 重建基线，不是手动加配额。
- 新增 `except Exception: pass` 必须在上方写 `# 静默是故意的：<理由>`，否则 check_silent 失败。


### 提交前 14 步门禁（check.bat）

每批交付前跑 `check.bat`，共 14 步，全绿才能提交：

```
 1  compileall 语法检查
 2  pytest tests/
 3  密钥合规检查（私钥不能随程序分发）
 4  check_version.py（权威来源 core/version.py）
 5  check_buttons.py + check_tools.py
 6  check_threads.py
 7  check_repo_sync.py
 8  check_lazy_imports.py
 9  check_types.py（Ruff + Mypy）
10  run_agent_e2e.py
11  check_file_sizes.py
12  check_plugin_api.py
13  check_runtime_compat.py
14  migrate_data.py --dry-run
```

动了 modules/installed/ 还要走：
```
  tools/rebuild_modules_repo.py --apply   （必须加 --apply，默认 dry-run）
  tools/sign_modules.py
  tools/sync_plugin_repo.py --apply
  tools/check_plugin_repo.py
```


---

## 新增 Agent / 代码 / 电脑 API（2026-10-19）

### Agent 状态与错误

```python
from core.agent_harness import get_run_registry, normalize_error

reg = get_run_registry()
reg.active_count()
reg.list_runs(limit=20)
env = normalize_error(Exception("权限被拒绝"))
# env = {code, title, message, cause, next_action, technical_detail}
```

### 工作区与 patch

```python
idx = trunk.get_workspace_index()
idx.rebuild()
idx.find_symbols("build_ui")
idx.related_tests("gui/build_ui.py")

from core.patch_engine import file_patch, validate_patch, apply_patch, rollback
patch = file_patch("a.py", "old text", "new text", "说明")
validate_patch(trunk.base, patch)
r = apply_patch(trunk.base, patch)
rollback(r["backup_manifest"])
```

### 代码 Agent

```python
from core.code_agent import CodeAgent
agent = CodeAgent(trunk, trunk.base,
                  test_commands=["pytest -q"],
                  lint_commands=["ruff check ."])
r = agent.run("修复设置保存问题", approved_cb=lambda patch: True)
```

### 电脑 Agent

```python
from core.computer_agent import ComputerAgent
from core.action_schema import make_action

ca = ComputerAgent(trunk)
snap = ca.observe()
hits = ca.ground("点击保存按钮", snap)
actions = ca.plan_goal("打开记事本并保存", snap)
r = ca.run_actions(actions)
```

### 录制回放

```python
from core.computer_recorder import ComputerRecorder
rec = ComputerRecorder(trunk.base)
rec.start("my_task")
rec.record(action)
path = rec.stop()
rec.replay(ca, path)
```

---

## 插件公共 API v1.0 与数据迁移（2026-10-20）

### 插件公共 API

```python
from core.plugin_api import (
    PLUGIN_API_VERSION,          # "1.0"
    PUBLIC_CORE_MODULES,
    manifest_api_version,
    validate_plugin_source,
    validate_plugin_manifest,
)
```

清单要求：

```json
{
  "name": "my_plugin",
  "file": "my_plugin.py",
  "api_version": "1.0",
  "first_party": false
}
```

- 第三方插件只能 import `PUBLIC_CORE_MODULES` 中的模块；
- 永远禁止 `core.trunk`、`core.data_schema`、`core.data_migrations`、
  `core.secret_store`、`core.release_sign`、`core.auth`、`core.pipeline`
  以及 `from core import *`；
- 官方随包模块由清单 `first_party: true` 标记，可依赖少量审计过的集成层；
- 安装、下载、本地 `.py` 安装都在执行/落盘前调用
  `validate_plugin_manifest()`，失败直接拒绝；
- `tools/check_plugin_api.py` 是发版前守卫。

### 数据迁移 API

```python
from core import data_schema
from core.data_migrations import migrate_all, migrate_file

data_schema.check(trunk.base)        # 返回 warning/info/unknown/migratable
migrate_all(trunk.base, dry_run=True)
migrate_all(trunk.base)
```

迁移约定：v0→v1→v2 不跳步；先备份；JSONL 坏行保留 `.bad_lines`；
SQLite 事务 + `x6_meta`；失败不覆盖原文件。

详见 `docs/70_兼容性与数据迁移.md`。


## 2026-10-20 第二阶段新增核心 API

这些是 core 层能力，不改变 LAZY_MAP 模块数和工具注册数：

### 模型

- `core.llm_providers.build_chat_request(provider, model, messages, ...)`
- `core.llm_providers.parse_chat_response(provider, data)`
- `core.model_router.route_model(...)`
- `core.model_router.capability_report(provider, model, ...)`
- `LLMClient.route_request(requirements=None, local_failed=None)`

### RAG

- `core.rag_pipeline.KnowledgeBase.ingest_file(path, acl_roles=...)`
- `KnowledgeBase.ingest_directory(...)`
- `KnowledgeBase.search(query, role=..., top_k=...)`
- `KnowledgeBase.delete_source(source)`
- `KnowledgeBase.stats()`

### 插件

- `core.plugin_registry.manifest_product_info(meta, ...)`
- `core.plugin_registry.select_update(current, candidates, ...)`
- `core.plugin_registry.InstallLedger(base)`
- `core.plugin_installer.apply_update(pm, meta)`
- `plugin_market.check_updates(online=None)`

### 团队

- `core.team_policy.TeamStore(base)`
- `TeamStore.check(user, permission)`
- `TeamStore.set_central_config(values, requester=...)`
- `TeamStore.export_audit(out_path, requester=...)`
- `Auth.login(...)` 返回角色，`Auth.has_permission(permission)`

### GUI Agent / 用量

- `core.gui_agent_quality.DualChannelLocator`
- `verify_snapshot(before, after, expectation)`
- `repair_strategy(action, result, attempt=0)`
- `core.model_pricing.estimate_cost(model, tokens_in, tokens_out, ...)`

---

## 新增模块 API（2026-10-22）

### core/startup_consent.py

```python
CONSENT_ITEMS = ("agreement", "onboarding", "mcp_trust", "plugin_caps")
ALWAYS_ASK = ("覆盖文件", "删除文件", ..., "按控件名点击")

load(base) -> dict                 读取记录
save(base, consents) -> (ok, err)  原子写入
is_granted(base, item) -> bool
grant(base, item, detail="") -> (ok, err)
revoke(base, item=None) -> (ok, err)
summary(base) -> {"granted": [...], "pending": [...], "always_ask": [...]}
should_ask(base, item) -> bool      ALWAYS_ASK 永远返回 True
```

### core/mcp_trust.py

```python
command_hash(command) -> str       sha256(cmd)[:16]
trust_path(base) -> str            含旧路径迁移
load_trusted(base) -> set[str]
save_trusted(base, hashes) -> (ok, err)
is_trusted(base, command) -> bool
```

### core/auth.py 新增

```python
remember_session(username) -> bool        只存账号名
last_user() -> str
restore_session() -> (ok, user, reason)   重新验签，失败即未登录
forget_session() -> dict
```

### gui/workbench_dialog.py

```python
WorkbenchWindow(trunk, parent=None)
    .editor_open_files() -> list[str]     当前打开的文件
    .open_path(path) -> bool
    .set_goal(text)
    .toggle_ai()               Ctrl+J
    .toggle_ai_popup()         弹出/收回 AI 面板
    .toggle_fullscreen()       F11

AgentDock(workbench)
    .current_goal() -> str
    .can_start() -> bool
    .start() / toggle_pause() / cancel()
```

### gui/mcp_trust_view.py

```python
MCPTrustPanel(trunk, parent=None)
    .refresh()        不加载 mcp_client 时读配置兜底
    .trust_all()      一键永久信任
    .revoke_all()     撤销全部
```

---

## 局域网信任 API（2026-10-22）

### core/lan_trust.py

```python
entry_of(url) -> str                # "http://192.168.1.2:11434" -> "192.168.1.2:11434"
current_hosts(trunk) -> list[str]
trust_host(trunk, url=None) -> (ok, msg)
revoke_host(trunk, entry) -> (ok, msg)
describe(trunk) -> str              # 给界面用的一行摘要
```

`trust_host()` 在 `save_config()` 返回 False 时**必须**返回失败，
不能假装成功（否则用户以为信任了，下次仍连不上）。

### core/net_guard.py 新增

```python
_trusted_lan_hosts() -> set[str]
_is_trusted_lan(host, port) -> bool
```

### core/llm_cloud.py 新增

```python
local_model_purpose(trunk, url) -> "local_model" | "cloud_model"
```

按主机名匹配 `ollama_url` / `local_url` / `local_base_url`，
避免用字符串前缀判断导致的误判。

---

## 网段放行 API（2026-10-22）

### core/net_guard.py 新增

```python
_lan_cidrs() -> list[str]            # 读 security.allow_lan_cidrs
_in_lan_cidr(host) -> bool           # 判断 host 是否落在私有网段声明内
_is_trusted_lan(host, port) -> bool  # CIDR 或精确主机，任一命中即 True
```

`_in_lan_cidr()` 的两道保护：

```python
ip = ipaddress.ip_address(host)        # 域名会先 gethostbyname 解析
if not (ip.is_private and not ip.is_loopback):
    return False                        # 公网 IP 永不进入此分支
```
