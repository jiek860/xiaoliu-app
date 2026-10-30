# 小6智能体  模块规则与 API 参考

> **文档分类**：模块规则与 API（模块规则、智能体、插件标准、插件审计）
> **状态**：合订本（2026-10-30 合并，原零散文件已并入本文）
> **合并来源**：31_三个智能体使用手册.md、MODULE_STANDARD.md、PLUGIN_STANDARD.md、PLUGIN_SDK.md、plugin_audit_v21.md、plugin_audit_v21_batch1.md、plugin_audit_v21_batch2.md、91_插件质量门禁修复记录_2026-10-22.md
> **维护要求**：新内容先判断归属，属于本类的追加到文末对应章节，不再新建同级 md/txt（详见 docs/109 第十三节）。

版本：v25.2.29
更新日期：2026-10-25
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
> | `core/rules_engine.py` | 规则定义 | **75 条规则** |
> | `core/core_caps.py` | core 侧能力声明 | 19 条 |
> | `core/module_caps.py` | 能力注册表（合并两来源） | 64 条能力 |
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

> 三个智能体的工具链参数、返回字段、示例和降级：见 `31_三个智能体使用手册.md`。
> 人设对话走 `reply()`；`TOOLS` 里的分析/沙箱/工作流能力走命令面板或 `trunk.call()`，两者不是同一条路径。

#### 3.1 agent_coder（编程小匠·小七）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 智能路由判 `code` / 群聊 ROLE_MOD 命中编程 / 用户点名小七 / 命令面板搜“写代码并运行” |
| L2 处理 | LLM 只出代码块 → `code_runner` 沙箱执行 → 失败回传 stderr 最多再修 2 轮；`review` 只做 compile + 静态审查 |
| L3 判定 | 代码正确性靠沙箱跑通（`运行成功`）；非 Python 只生成、不执行 |
| L4 动作 | 工具：`agent_code_solve` / `agent_code_run` / `agent_code_review`；聊天框回复代码块 |
| L5 降级 | LLM 不可用 → `PLUGIN_NOT_AVAILABLE`；`code_runner` 不可用 → 明确报不可用，不直接 exec |

#### 3.2 agent_analyst（分析官·小八）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 路由 `analysis` / 群聊分析类问题 / 命令面板搜“分析一下”“对比” |
| L2 处理 | `deep_search` 取外部证据 + `graph_rag` 取本地三元组 → 数值配对（差值/变化率）→ LLM 结论与风险 |
| L3 判定 | 结论给证据和风险；无证据时明确标注“主要来自推理”，不编造百分比 |
| L4 动作 | 工具：`agent_analyze` / `agent_compare`；结构化回复（结论+依据+建议） |
| L5 降级 | 无 LLM → 结构化兜底（`llm=false`）；搜索/图谱失败 → 记 `警告`，不阻断分析 |

#### 3.3 agent_planner（策划师·小九）
| 规则项 | 规则 |
|---|---|
| L1 触发 | 路由 `planner` / 群聊方案策划 / 命令面板搜“做个计划” |
| L2 处理 | LLM 输出 JSON 步骤（action 限定 search/llm/code/set/wait）→ 校验依赖 → 可落成 `workflow_runner` 工作流 |
| L3 判定 | 每步有动作、参数和 `done_when`；依赖只保留真实存在的 id |
| L4 动作 | 工具：`agent_plan` / `agent_plan_workflow` / `agent_plan_next`；复杂目标可交 `task_loop` |
| L5 降级 | LLM/JSON 失败 → 4 步通用模板 + `警告`；同名工作流默认不覆盖（`PLUGIN_BAD_INPUT`） |

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

**接口（v25.4.0 起）**：`voice.listen(seconds=5, sample_rate=16000, stop_event=None)`。
`stop_event` 由 GUI 传入，录音循环每 1024 帧检查一次；用户松开按钮即置位，
因此"按住说话"不会硬等 5 秒。没录到任何帧时返回
`{"ok": False, "error": "没有录到声音"}`，而不是静默返回空文本。
`gui/speech.py::listen_once` 对旧签名做了 `TypeError` 回退，老插件不会被打断。

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

版本：v25.2.29
更新日期：2026-10-25

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
- 规则定义：`core/rules_engine.py`，当前 75 条（批次 48 新增 F 组 12 条）。
- 能力注册：`core/module_caps.py`，当前 64 条。
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

### 活动中心数据源（2026-10-25 / v25.2.30）

```python
from core.agent_harness import get_run_registry, DEFAULT_MAX_RUNS
from gui.workers import _reg_start, _reg_finish, _log_path

# 任何长任务统一登记，失败必须带原因
rid = _reg_start("background", "索引重建", _log_path(trunk))
_reg_finish(rid, "completed")            # 或 ("failed", "失败原因")

# 注册表只保留最近 DEFAULT_MAX_RUNS(200) 条已结束活动，运行中的不淘汰
# 活动中心：运行中 / 失败 / 最近完成 分组；失败行可点「查看日志」
BgWorker(fn, "索引重建", trunk=trunk)     # trunk 用于定位 data/logs/app.log
```

### 工作区与 patch

```python
idx = trunk.get_workspace_index()
idx.rebuild()
idx.find_symbols("build_ui")                       # 精确 > 后缀 > 前缀 > 子串
idx.find_symbols("open", kind="method", file="gui/workbench_dialog.py")
idx.related_tests("gui/build_ui.py")
idx.stats()["symbol_engines"]                      # {"ast": n, "tree-sitter": n, "regex": n}

from core.patch_engine import (file_patch, validate_patch, dry_run_patch,
                               apply_patch, rollback)
patch = file_patch("a.py", "old text", "new text", "说明")
validate_patch(trunk.base, patch)                  # 只校验结构/base_hash
dry = dry_run_patch(trunk.base, patch)             # 内存整体预演，不写盘
# dry = {"ok": bool, "files": [...], "errors": [...]}
r = apply_patch(trunk.base, patch)                 # 默认先 dry-run，失败整批不落盘
rollback(r["backup_manifest"])
```

符号索引：Python 由 `core/symbol_parser.py` 走 AST；JS/TS 优先
`tree_sitter_languages`，未安装时正则降级。每个符号带
`kind / line / end_line / engine / confidence`，用 `engine` 判断可信度。

### 代码 Agent

```python
from core.code_agent import CodeAgent
from core.code_agent_policy import resolve_max_rounds

agent = CodeAgent(trunk, trunk.base,
                  test_commands=["pytest -q"],
                  lint_commands=["ruff check ."])
r = agent.run("修复设置保存问题",
              max_rounds=resolve_max_rounds(),       # 默认 12，夹取 1~15
              approved_cb=lambda patch: True,
              resume_state=None,                     # 断点续跑
              checkpoint_cb=lambda state: None)      # 每轮落盘
# r 额外返回 stop_reason / rounds_used / max_rounds
# stop_reason: tests_green | no_progress | max_rounds

# 回修时可选传入上一轮 diff，让模型在原改动上继续修
patch = agent.propose_patch(goal, context, previous_error="",
                            previous_diff="上一轮已经落盘的 diff")
```

- patch 生成/校验失败（JSON 不合法、`hunk.old` 匹配不到、空改动）不再直接
  结束任务，而是记录原因后进入下一轮；`no_progress` 仍是连续两轮同错误时终止。
- `CodeAgent._failure_digest()`：把测试/lint 失败整理成“失败用例名 + 输出尾部”，
  比直接拼接完整输出更容易让模型定位。
- 断点状态里的 `last_diff` 会随 checkpoint 落盘，续跑后继续用于回修提示。

### 聊天流式渲染

```python
from gui.chat_view import ChatView

anchor = chat.append_thinking()                       # 思考占位 + 首个流式锚点
anchor = chat.stream_render(anchor, partial, "小6")   # 重绘一帧，返回新锚点
# ChatMixin 按 0.12s 节流调用；结束时 render_reply() 覆盖为正式渲染
```

- `stream_render()` 先删掉上一帧再整体渲染，生成过程中就能看到 Markdown；
- `MarkdownRenderer.render()` 在围栏数为奇数时自动补一个结束围栏，
  流式途中的半截代码块也能正常显示。

### 聊天取消（Esc 真停止）

```python
from core.cancel_token import CancelToken

token = CancelToken()
thread = threading.Thread(target=llm.stream_chat,
                          args=(messages,), kwargs={
                              "on_token": on_token,
                              "cancel_token": token})
thread.start()
# GUI 线程（Esc）：
token.cancel()        # 置位 + close 已登记的流响应
```

- `CancelToken.cancel()` 会关闭 `bind()` 登记的资源（如 stream response），
  把阻塞在 `iter_lines()` 的读线程叫醒，及时释放 Ollama 串行锁；
- `stream_chat(..., cancel_token=)` 取消后返回已收到的内容，不再走云端兜底、
  非流式重试；
- `trunk.reply(..., cancel_token=)` / `ReplyPipeline.run()` /
  `legacy_reply.run()` / `LLMDispatcher.dispatch()` 全部透传；
  取消后跳过记忆写入、群聊合并、代码沙盒验证和后台队列；
- `StreamWorker.stop()` 调用 `cancel()`，取消后不再 emit token / done，
  活动中心把该 run 记为 `cancelled`；
- 云端流式同样接入取消：`_try_cloud_stream(message, on_token, cancel_token)`
  在 `iter_lines()` 前 `bind(r.close)`，取消后返回已收到内容。

### 首字超时与云端流式配置

```python
# config.json（都可省略，省略时用默认值）
{
  "本地首字超时": 25,          # 或 local_first_token_timeout，5~300 秒
  "云端首字超时": 60           # 或 cloud_first_token_timeout，5~300 秒
}
```

- 本地 `/api/chat` 流式请求超时为 `(5, 本地首字超时)`：首字迟迟不出时
  回调 `（本地首字超时，切云端...）`，随后直接走云端流式；
- 本地刚超时后不会再调用一次非流式本地接口（避免二次等待）；
- `model_mode` 为云端时优先 `_try_cloud_stream`（按 `cloud_provider`
  发 `stream=True`，用 `parse_stream_chunk` 解析 openai/azure/anthropic/gemini
  的 SSE）；流式返回空才回退一次性 `_try_cloud`；
- `core/llm_shared.config_seconds(config, keys, default)` 负责读取并夹取
  秒级配置（非法值/空值回退默认）。

### 任务队列与断点续跑

```python
from core.code_task_queue import get_code_queue

q = get_code_queue(trunk.base)
job_id = q.enqueue("修复设置保存问题", meta={"rounds": 12})
q.mark_running(job_id)
q.checkpoint(job_id, {"round": 3, "last_error": "...",
                      "fingerprints": [...], "patches": [...], "backups": [...]})
q.mark_paused(job_id)
state = q.checkpoint_of(job_id)      # 传给 CodeAgent.run(resume_state=...)
q.mark_done(job_id, ok=True)
```

### 双角色 Agent

```python
from core.code_roles import two_role_enabled, explore_project

two_role_enabled({})                          # 默认 True
result = explore_project(agent, "修复保存问题", context)
# {"report": "...", "files": [...], "patch": {...}|None, "tools": [...]}
# 探索阶段只读（read_file / grep / list_files / find_symbols / run_command）
```

### 计划审批（复杂任务先出计划）

```python
from core.code_plan import (
    plan_enabled, needs_plan, build_plan, plan_text, confirm_plan,
)

plan_enabled(trunk)                    # 默认 True；X6_CODE_AGENT_PLAN=0 关闭
needs_plan("重构 core 模块并补测试", files)   # 复杂关键词/长目标/多文件
plan = build_plan(agent, goal, context)
# {"summary", "steps":[{"title","purpose","files","risk"}], "risks", "tests"}
print(plan_text(plan))                 # 审批弹窗/时间线文本

gate = confirm_plan(agent, goal, context, plan_cb)
# {"required", "proceed", "rejected", "plan", "reason"}
```

`CodeAgent.run(..., plan_cb=...)` 只有在传入 `plan_cb` 时才启用计划阶段；
拒绝后返回 `{"ok": False, "cancelled": True, "rejected_plan": True}`，
不生成也不应用 patch。代码生成统一走 `agent._llm_chat()`：模型有
`stream_chat` 时接入 `CancelToken`，取消后立即抛 `AgentCancelled`。

### GitHub PR 闭环

```python
from core.github_pr import GitHubClient, PRFlow

client = GitHubClient(repo="owner/repo")        # Token: 参数/环境/凭据管理器
flow = PRFlow(trunk, trunk.base, client=client)
r = flow.run(files,                            # [(相对路径, 文本)]
             title="feat: ...", branch="x6/xxx",
             wait_ci=True, merge=True)
# r: {"ok", "branch", "commit", "pr", "ci", "merge"}
# 失败时 r["error"]；CI 状态可经 PRFlow.ci_feedback(r) 回灌 Agent
```

写操作只走 `api.github.com`（本机 `git push` 到 github.com:443 会被 RST）；
`commit_files` 按 blob→tree→commit→ref 提交，`ref_sha()` 遇到 404 返回空串表示分支不存在。

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
from core.action_recorder import ActionRecorder
rec = ActionRecorder(trunk)          # 已注册为懒加载模块 "action_recorder"
rec.start("my_task")
rec.add_action("open_app", app="notepad")
r = rec.stop()                       # {"ok": True, "path": ..., "count": n}
rec.play("my_task")                  # 回放走 trunk.modules["computer_controller"]
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
    .reload_editor_path(path)             已开着就刷新，新文件直接打开并聚焦
    .set_goal(text)
    .toggle_ai()               Ctrl+J；同步 QDockWidget 可见性
    .toggle_ai_popup()         AI 面板浮动/收回（QDockWidget.setFloating）
    .toggle_fullscreen()       F11
    .ai_host                   QDockWidget，右侧 Secondary Side Bar
    ._editor                   CodeEditorDialog（含 tabs / bottom / fs_model）

AgentDock(workbench)
    .current_goal() -> str
    .can_start() -> bool
    .start() / toggle_pause() / cancel()
    .start_sc                  Ctrl+Enter 快捷键（QShortcut，不占按钮预算）

resolve_explicit(goal) -> "code" | None
    工作台默认代码 Agent；/chat、/pc、/computer 前缀返回 None 交给路由
```

### gui/ide_editor_shell.py

```python
EditorTabs(header=None)         QTabBar + 面包屑 + QStackedWidget
    .addTab(w, title) / .removeTab(i)
    .widget(i) / .count() / .currentWidget() / .currentIndex()
    .set_secondary(w) / .clear_secondary() / .has_secondary()

BottomPanel(output, root=".")     终端页逻辑在 gui/ide_terminal.py 的 TerminalMixin
    .set_problems([(line, msg)])   兼容 (行,描述) 与 (行,列,规则码,描述)
                                   问题页双击发 jumpRequested(int)
    .show_diff(rel, text)          差异页按 +/- 着色并切过去（索引 3）
    .diff / .diff_index            差异页控件与页签索引
    .select(index)                 0=输出 1=问题 2=终端 3=差异
```

### gui/ide_terminal.py

终端这一块（ANSI 清洗、编码、shell 生命周期、PTY 适配）从 `ide_editor_shell.py`
拆出来，既让上层文件回到 600 行预算内，也方便单独测。`BottomPanel`
继承 `TerminalMixin`，下面这些方法仍是它的 API。

```python
pty_available() -> bool             Windows + 装了 pywinpty 才 True（失败静默返回 False）
PtyShellProcess(parent=None)        pywinpty/ConPTY 后端，接口对齐 TerminalMixin 用到的 QProcess 子集
    .start(program, args) / .write(str|bytes) / .readAllStandardOutput() -> str
    .state() / .kill() / .waitForFinished(ms) / .errorString()
    readyReadStandardOutput / finished(code, status)  由后台读线程发出（线程里不碰控件）

TerminalMixin
    .run_terminal(text=None)       cd / pwd / cls 本地处理，其余写进常驻 shell
    ._ensure_shell()               懒启动：装了 pywinpty 走 ConPTY，否则 cmd.exe /q /k
                                   （Unix /bin/sh -i）；失败返回 None
    ._write_shell(cmd)             PTY 写 "cmd\r"；管道按 Windows OEM 代码页编码（936=GBK）
    ._shell_alive()                shell 进程是否还活着（退出后回车自动重启）
    ._append_raw(text)             流式追加；只在贴底时跟随滚动，不会粘上一行
    .shutdown()                    关闭工作台时调用：杀掉 shell，不留孤儿进程

_clean_ansi(text)                 去掉 CSI/OSC 转义序列（ConPTY 还会改窗口标题）
_decode_shell_bytes(data, carry)  先 UTF-8、失败退 OEM/GBK；尾部半个汉字留在 carry
_shell_encoding()                 GetOEMCP() → "cp936"；不能用 locale（UTF-8 模式恒 utf-8）
```

两种后端对上层是同一套调用：`_shell_kind` 记 `"pty"` / `"pipe"`。PTY 是"屏幕画面"
（控制台自己回显、含光标/颜色序列），所以不再补 `$ cmd` 回显，输出先 `_clean_ansi`；
提示符用环境变量 `PROMPT=@x6@` 设（省一次按键），首次输出要等哨兵出现才显示。

### gui/code_editor_widget.py

```python
ruff_command(path)             [ruff|python -m ruff] check --output-format=json
parse_ruff_json(text)          JSON → [(行, 列, 规则码, 描述)]；非 JSON 返回 None
ast_problems(code)             兜底：只报第一条 SyntaxError（同为 4 元组）

python_symbols(code)           ast 提取 def/class/import as/赋值目标；解析失败退回正则
js_symbols(code)               function/class/const/let/var 的名字
completion_words(code, path)   关键字 + 内置名 + 本文件符号（.js/.ts 自动换表）

CodeEditWidget()
    .filepath = p              setter 即"打开/保存"，会触发一次静态检查
    .check_problems()          ruff 走 QProcess 后台（5s 超时，失败退回 ast）
    .problems()                [(行, 列, 规则码, 描述)]
    ._try_complete(force)      本地补全弹窗；Ctrl+Space / Ctrl+) 是 force=True
    problemsChanged(list)      问题列表变化（编辑中退回 ast，保存后是 ruff）
    syntaxErrorChanged(int)    问题条数，供状态栏
```

### gui/editor_parts.py

```python
_PyHighlighter(doc)   Python 关键字/字符串/注释/数字高亮
_LineNumberArea(editor)   行号区（paint_line_numbers 由主控件画）
_MiniMap(editor)     右侧缩略图：行密度色块 + 当前位置框，点击/拖动跳转
```

`gui/code_editor_widget.py` 直接 re-export 这三个名字，旧导入路径不变。

### gui/ide_sidebar.py / gui/ide_explorer.py

```python
activity_icon(kind)            explorer/search/scm/run/extensions/ai 单色图标
SearchPanel(root)              .run_search()；openRequested(path, line)
                               .case_sensitive / .use_regex（Aa / .* 开关）
                               .replace_all() 全部替换（备份+原子写，返回处数）
                               ._matcher(q) / ._rg_args(q) 两条搜索路径共用
                               ._text_files()  跳过 .git / 非文本 / >1MB
ScmPanel(root)                 .refresh() / .stage(rel) / .stage_all()
                               .unstage(rel) / .discard(rel) / .commit(msg)
                               .emit_diff(rel=None)
    discard(rel)               放弃改动：?? 删文件；A 先 rm --cached 再删；
                               其余 checkout HEAD -- rel（连暂存区一起退回 HEAD）
    diffRequested(rel, text)   右键「查看差异」→ 已暂存优先 --cached，否则工作区
    commitDone(sha)            提交成功后发短 sha
    openRequested(path)        双击改动
    hint                       一行操作结果提示（refresh 会先重置它）
SidebarHost(root, parent)      .attach(explorer, splitter) 三页侧栏
                               .diffRequested / .commitDone 直接转发 ScmPanel
CommandCenterMixin             ._run_command() / ._focus_command()
GitFileModel()                 .refresh_git(root, mapping=None) 文件名着色
ExplorerMenuMixin              .refresh_git_marks() / 右键新建·重命名·删除·定位
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

---

## 新增模块 API 参考（2026-10-23，按当前代码校正）

### core/skill_registry.py

统一技能注册表：扫描 `.x6skill` 目录、自学习捕获的 markdown、待确认技能。

```python
from core.skill_registry import SkillRegistry

reg = SkillRegistry(trunk)

reg.list_all()                 # 返回 [{name, source, path, enabled, verified}]
reg.load("skill_name")        # 返回 {prompt, tools, source}；禁用时返回 None
reg.get_enabled_prompts()     # 供聊天 system prompt 注入
reg.install_from_file("path/to/skill.x6skill")
reg.export_to_file("skill_name", "out.x6skill")
reg.enable("skill_name")
reg.disable("skill_name")
reg.delete("skill_name")
```

说明：`verified` 是本地 MD5 完整性记录，不是 RSA 签名；远程市场下载另行做 SHA256 校验。

---

### core/skills_market.py

技能目录与下载。优先远程固定 GitHub raw 地址，失败回退 `core/skills_catalog.json`；下载后必须通过目录中的 sha256。

```python
from core.skills_market import fetch_remote_catalog, download_skill

catalog = fetch_remote_catalog()
result = download_skill("web_research")
# result["zip_path"] 交给 SkillRegistry.install_from_file()
```

---

### gui/plan_confirm_dialog.py

```python
from gui.plan_confirm_dialog import PlanConfirmDialog

dialog = PlanConfirmDialog(plan_text="计划内容", goal="任务目标", parent=parent)
dialog.exec_()
if dialog.is_approved():
    edited_plan = dialog.get_edited_plan()
```

---

### gui/skills_dialog.py

```python
from gui.skills_dialog import SkillsDialog

dialog = SkillsDialog(trunk, parent)
dialog.exec_()
```

主按钮只保留：`导入`、`导出`、`更多操作`、`关闭`。
确认/拒绝/删除/刷新/市场安装收进「更多操作」菜单，降低界面复杂度。

---

### modules/installed/api_server.py

```python
from modules.installed.api_server import ApiServer

server = ApiServer(trunk, host="127.0.0.1", port=8765)
info = server.start()
# info["url"] 带一次性 token，例如 http://127.0.0.1:8765/?token=...
server.stop()
```

端点：

- `GET /`：聊天页
- `GET /tasks`：任务列表页
- `POST /v1/chat`：聊天
- `POST /v1/tasks`：创建并启动真实 TaskRuntime 任务
- `GET /v1/tasks/{id}`：查询真实任务
- `GET /v1/ws`：WebSocket 任务推送；需要安装 `websockets`

鉴权：支持 `?token=...` 或 `Authorization: Bearer ...`；`/v1/health` 不鉴权。

---

### modules/installed/web_agent.py

```python
from modules.installed.web_agent import WebAgent

agent = WebAgent(trunk)
result = agent.browse("https://example.com", "找到登录按钮并点击", max_steps=5)
```

支持动作：`click(selector)`、`type(selector, text)`、`scroll()`、`back()`、`done()`。
动作失败会返回 `{"ok": False, "error": ...}`，不会静默当成成功。

---

### modules/installed/coder_pro.py

```python
from modules.installed.coder_pro import CoderPro

coder = CoderPro(trunk)
result = coder.run_task(
    goal="修复登录 bug",
    project_path="E:/myproject",
    plan_mode=True,
)
```

流程：生成计划 → `Trunk.confirm_plan()` → 用户编辑/批准 → 计划拼入 CodeAgent goal → 执行。
`plan_mode=False` 可跳过计划确认。

---

### modules/installed/multimodal.py

```python
from modules.installed.multimodal import Multimodal

mm = Multimodal(trunk)
result = mm.describe_image("path/to/image.png")
```

图片会以 base64 传入 `LLMClient.chat_with_image()`；请求格式按 OpenAI、Anthropic、Gemini、Ollama 分别转换。
当前聊天历史不保存原图，只保存描述结果。

---

## 大文件拆分后的模块边界（v25.2.31）

拆分只搬代码，对外 API 不变；下表是"新文件放什么、旧入口还能怎么用"。

| 原文件 | 新文件 | 对外兼容 |
|---|---|---|
| `modules/installed/plugin_market.py` | `modules/support/plugin_market_online.py`（`PluginMarketOnlineMixin`） | `PluginMarket` 仍有 `list_online/download/check_updates` |
| `modules/installed/tool_caller.py` | `modules/support/tool_catalog.py`（`BUILTIN_TOOLS`） | `ToolCaller(...).tools` 仍包含全部内置工具 |
| `gui/settings_dialog.py` | `settings_model_page.py`（`build_model_page`） | 模型配置页行为不变 |
| `gui/mcp_dialog.py` | `mcp_catalog.py`（`DEFAULT_PRESETS/REFERENCE/valid_presets/load_presets`） | `gui.mcp_dialog.PRESETS` 仍可用 |
| `gui/workbench_dialog.py` | `workbench_ai_dock.py`（`AgentDock`） | `from gui.workbench_dialog import AgentDock` 仍可用 |
| `gui/mixins/dialog_mixin.py` | `mixins/background_tasks_mixin.py`（`BackgroundTaskMixin`） | `DialogMixin` 继承后方法名不变 |

### 工程工具 API

```powershell
# 发布（只走 api.github.com，不打印 token）
py -3 tools\github_api_push.py --message-file msg.txt --pr-title "..." --wait-ci --merge

# 性能基线（CI 只报警）
py -3 tools\perf_baseline.py --check --tolerance 0.10 --warn-only --json-out data\perf_current.json

# Agent 回归基线（20 道固定本地样本）
py -3 tools\run_eval.py --out data\eval_result.json --markdown docs\92_Agent回归基线.md
```

---

## 窗口单实例 API（v25.2.33）

`gui/mixins/dialog_mixin.py` 统一了主窗口的弹窗入口，避免连点叠窗。

| API | 说明 |
|---|---|
| `_singleton_window(key, factory, focus=None)` | 非模态窗口：已开着就 `show/raise_/activateWindow` 并返回同一实例；关闭后下次重建 |
| `_run_modal_once(key, opener)` | 模态窗口：同一 key 正在打开时第二次调用返回 `None`，不再建窗 |
| `_open_simple_dialog(modname, clsname, modal=True)` | `(trunk, parent)` 签名窗口的通用打开器；模态走守卫，非模态走单例 |
| `TaskCenterDialog.show_task(task_id)` | 复用的任务中心切到指定任务并刷新 |

- 新窗口必须选其一，不要直接 `QDialog(...).show()` / `.exec_()`。
- 关闭主窗口时 `JarvisWindow.closeEvent` 会先关闭所有 `QDialog` 子窗口，
  让任务中心 / 活动中心注销运行时订阅、停掉定时器。
- 守卫：`tests/test_dialog_singleton.py`（静态检查 + 真实连点），
  详见 `docs/10_开发流程与工程手册.md`「窗口单实例」。

---

## 附录：三个智能体使用手册

> 原文件 `docs/31_三个智能体使用手册.md`，2026-10-30 合并入本文。

# 三个子智能体使用手册

> 适用版本：v25.2.33（2026-10-27）
> 覆盖模块：`agent_analyst` / `agent_coder` / `agent_planner`（均为 v1.1.0）
> 文档定位：怎么用、参数是什么、返回什么、失败时怎么办。模块规则与能力全景见 `30_模块规则与API参考.md`。

---

## 一、先分清两条使用路径

三个智能体有两种“说话方式”，能力不是一回事：

| 路径 | 入口 | 走什么 | 适合 |
|---|---|---|---|
| 人设对话 | 聊天 / 群聊的小七、小八、小九 | `reply()`，只调用 LLM 人设 | 闲聊、补充观点、快速问答 |
| 专属工具链 | 命令面板 `Ctrl+K`，或代码 `trunk.call()` | 模块声明的 `TOOLS`，带搜索/图谱/沙箱/工作流 | 要证据、要跑代码、要可执行步骤 |

> 群聊里的“小七/小八/小九”不会自动跑沙箱或写工作流；要跑工具链，请用 `Ctrl+K` 或下面的 API 示例。

### 1.1 命令面板（普通用户）

1. 按 `Ctrl+K` 打开命令面板；
2. 输入下表中的提示词之一，选中对应能力；
3. 按弹窗逐个填参数（`confirm=True` 的能力会先弹确认）；
4. 结果在面板下方输出，执行走 `tool_caller._dispatch`，带权限中心审计，界面不卡。

| 想要 | 搜这些词 | 能力名 |
|---|---|---|
| 有证据的分析 | 分析一下 / 深度分析 / 利弊 / 风险分析 | `agent_analyze` |
| A/B 或数据对比 | 对比一下 / 哪个好 / 方案对比 / 数据对比 | `agent_compare` |
| 写代码并跑通 | 写代码并运行 / 代码验证 / 帮我跑一下 / 修 bug | `agent_code_solve` |
| 只跑一段代码 | 运行代码 / 跑 Python / 沙箱运行 | `agent_code_run` |
| 只审查不执行 | 代码审查 / review 代码 / 看看有没有 bug | `agent_code_review` |
| 拆解目标 | 做个计划 / 拆解目标 / 执行步骤 / 方案步骤 | `agent_plan` |
| 计划变成工作流 | 计划变工作流 / 生成可执行工作流 / 自动执行计划 | `agent_plan_workflow` |
| 看下一步做什么 | 下一步做什么 / 计划执行到哪 / 哪些步骤能做 | `agent_plan_next` |

### 1.2 Python / 自动化（开发者）

```python
r = trunk.call("agent_analyst", "analyze", "问题或对象", baseline="对比基准")
```

`trunk.call(模块名, 方法名, *位置参数, **关键字参数)`，返回 Python dict；
工具调用路径返回同样的 dict，失败时统一带 `ok=False` 与 `error.code`。

---

## 二、agent_analyst（分析专家）

### 2.1 它做什么

1. 用 `deep_search` 取外部证据（取前 5 条）；
2. 用 `graph_rag` 取本地知识三元组（取前 8 条）；
3. 本地做数值配对（差值、变化率），不依赖模型算数；
4. 交给 LLM 输出结论、利弊、风险和建议；
5. 无 LLM 时仍然返回结构化结果，不会空答。

**不负责**：替用户做最终决策、改知识图谱、写长期记忆、选模型。

### 2.2 `agent_analyze(topic, baseline="")`

| 参数 | 必填 | 说明 |
|---|---|---|
| `topic` | 是 | 要分析的问题、对象或方案 |
| `baseline` | 否 | 对比基准；填了才会做左右数值配对 |

```python
r = trunk.call(
    "agent_analyst", "analyze",
    "本地部署：延迟 2.0 秒，成本 0 元/次",
    baseline="云端部署：延迟 1.2 秒，成本 0.02 元/次",
)
print(r["分析"], r["风险"], r["数据对比"])
```

返回字段：

| 字段 | 说明 |
|---|---|
| `ok` | 成功为 `True` |
| `主题` / `基准` | 回显输入 |
| `证据` | 搜索摘要 + 图谱三元组，最多 3000 字 |
| `数据对比` | `[{"序号","左","右","差值","变化率"}]` |
| `分析` | LLM 结论；无 LLM 时为结构化兜底 |
| `风险` | 风险清单（含“需人工复核”） |
| `llm` | 本次是否真的用了 LLM |
| `警告` | 搜索/图谱失败等非阻断问题 |

> **数值配对规则**：按“第 N 个数字”一一对应。两边数字顺序要一致、单位要一致，否则差值没有意义。
> 正则会把型号/版本里的数字也当成数据（例如 `7B`、`Qwen2.5`），所以对比金额/延迟时，最好把型号写到括号外或保证两边数字顺序一致、数量相同。

### 2.3 `agent_compare(left, right, dimensions="")`

| 参数 | 必填 | 说明 |
|---|---|---|
| `left` / `right` | 是 | 两个方案或两组数据 |
| `dimensions` | 否 | 对比维度，逗号分隔；默认“目标契合、成本、风险、可维护性” |

```python
r = trunk.call(
    "agent_analyst", "compare",
    "方案A：月成本 3000 元，交付 30 天",
    "方案B：月成本 4500 元，交付 20 天",
    dimensions="成本,交付周期,风险",
)
```

返回字段：`左`、`右`、`维度`、`数据对比`、`分析`、`风险`、`证据`、`llm`、`警告`。
无 LLM 时按“右侧大于左侧的项数”给兜底结论（B 更优 / A 更优 / 数据不足）。

### 2.4 失败与降级

| 情况 | 表现 |
|---|---|
| 缺 `topic` / `left` / `right` | `ok=False`，`error.code=PLUGIN_MISSING_ARG` |
| `deep_search` 或 `graph_rag` 没装/查询失败 | 分析继续，`警告` 里记录原因 |
| LLM 不可用 | 仍返回 `ok=True`，`llm=False`，给结构化兜底 |

---

## 三、agent_coder（编程小匠）

### 3.1 它做什么

1. LLM 只输出代码块；
2. 可选拼上你给的测试代码；
3. 交给 `code_runner` 的进程级沙箱执行；
4. 失败把 stderr 回传给模型，最多再修 2 轮（总共最多 3 次尝试）；
5. `review` 只做语法检查 + 静态审查，**从不执行代码**。

**不负责**：改项目文件（那是 `coder_pro`）、保证业务规范、沙箱本身的安全边界。

### 3.2 `agent_code_solve(task, language="python", tests="")`

| 参数 | 必填 | 说明 |
|---|---|---|
| `task` | 是 | 要实现的功能或要修的 bug |
| `language` | 否 | 默认 `python`；`py` 等价；其它语言只生成不运行 |
| `tests` | 否 | 追加在生成代码后面的测试/校验代码 |

```python
r = trunk.call(
    "agent_coder", "solve",
    "实现 is_palindrome(s)：忽略大小写和空格判断回文",
    tests='assert is_palindrome("A man a plan a canal Panama")',
)
print(r["运行成功"], r["轮次"], r["代码"])
```

返回字段：

| 字段 | 说明 |
|---|---|
| `代码` | 最终采用的一版代码 |
| `运行` | `code_runner` 原始结果（`成功`/`输出`/`错误`/`stdout`/`stderr`/`returncode`） |
| `运行成功` | 沙箱是否跑通；非 Python 为 `None` |
| `轮次` | 实际尝试次数（1~3） |
| `修复记录` | 每轮 `{轮次, 成功, 错误}` |
| `llm` | 是否用了 LLM |

注意：

- `solve` 使用 `code_runner` 当前超时（默认 10 秒）。长时间代码请改用 `agent_code_run` 显式传 `timeout`。
- 非 Python 语言返回 `运行成功=None` 和“非 Python 不在沙箱执行”，不会偷偷执行。
- LLM 不可用：`ok=False`，`PLUGIN_NOT_AVAILABLE`。
- 生成内容里没有可用代码：`ok=False`，`PLUGIN_INTERNAL_ERROR`。

### 3.3 `agent_code_run(code, timeout=None)`

只执行，不生成、不审查：

```python
r = trunk.call("agent_coder", "run_code", "print(sum(range(10)))", timeout=3)
print(r["运行"]["输出"], r["运行成功"])
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `code` | 是 | 要运行的 Python 代码 |
| `timeout` | 否 | 秒；不填沿用 `code_runner.timeout`（默认 10） |

返回：`ok`、`运行`、`运行成功`。

### 3.4 `agent_code_review(code)`

只审查，不执行：

```python
r = trunk.call("agent_coder", "review", "def f(x):\n    return x / 0\n")
print(r["问题"], r["审查"])
```

返回：

| 字段 | 说明 |
|---|---|
| `问题` | `compile()` 发现的语法错误（没有则为空列表） |
| `审查` | LLM 列出的语法/逻辑/边界/安全/可读性问题与最小修改建议 |
| `llm` | 是否用了 LLM；无 LLM 时只做 `compile` 检查并说明 |

### 3.5 失败与边界

| 情况 | 表现 |
|---|---|
| 缺 `task` / `code` | `PLUGIN_MISSING_ARG` |
| `code_runner` 不可用 | `PLUGIN_NOT_AVAILABLE` |
| 沙箱超时 | `运行.成功=False`，`运行.错误` 说明超时 |
| 沙箱执行异常 | 返回 `{"成功": False, "错误": ...}`，不会直接 `exec` 用户代码 |
| 代码审查 | 即使代码有副作用也不会执行；只读 |

> 安全分级：`agent_code_solve` / `agent_code_run` 为 `confirm=True, danger=True, risk=exec`；
> 命令面板会先弹确认，聊天触发也走权限中心和审计。

---

## 四、agent_planner（策划专家）

### 4.1 它做什么

1. LLM 输出 JSON 计划：`id / title / action / args / depends_on / done_when`；
2. 校验动作只能是 `search / llm / code / set / wait`；
3. 依赖只保留真实存在且不是自己的 id；
4. `plan_to_workflow` 把计划摊平成 `workflow_runner` 字段，写入 `data/workflows/`；
5. `next_steps` 按依赖算出“现在能做 / 被阻塞 / 还剩什么”。

**不负责**：替用户批准执行、具体工具实现、项目排期与资源管理。

### 4.2 `agent_plan(goal, constraints="")`

| 参数 | 必填 | 说明 |
|---|---|---|
| `goal` | 是 | 要达成的目标 |
| `constraints` | 否 | 约束、资源、截止时间 |

```python
r = trunk.call(
    "agent_planner", "plan",
    "两周内完成本地模型切换的评估与灰度",
    constraints="只有 1 台测试机；不能影响线上；预算 0",
)
for step in r["步骤"]:
    print(step["id"], step["action"], step["title"], step["depends_on"])
```

步骤格式（LLM 输出，模块会规范化）：

```json
[
  {"id": "s1", "title": "明确验收标准", "action": "set",
   "args": {"value": "延迟≤2.5s，成本≤0.01元/次"},
   "depends_on": [], "done_when": "标准可量化"},
  {"id": "s2", "title": "收集基线", "action": "search",
   "args": {"query": "本地 7B 部署 延迟 成本"},
   "depends_on": ["s1"], "done_when": "至少 3 条有效资料"}
]
```

动作与参数约定：

| action | `args` 必填键 | 说明 |
|---|---|---|
| `search` | `query` | 交给 `deep_search` |
| `llm` | `prompt` | 交给 `llm.chat` |
| `code` | `code` | 交给 `code_runner`；缺代码会降级为 `llm` |
| `set` | `value` | 只写变量，不调外部模块 |
| `wait` | `seconds` | 等待；非数字按 0 处理 |

返回：`ok`、`目标`、`约束`、`步骤`、`llm`、`警告`。
无 LLM 时返回 4 步通用模板（set → search → llm → wait），并带 `警告`；
LLM 有回复但 JSON 无法解析时同样回退到通用模板（原因记在模块的 `_last_error`，
此时 `llm` 仍可能是 `true`、`警告` 可能为空，属于已知边界）。

### 4.3 `agent_plan_workflow(goal, name="", run=False, overwrite=False)`

| 参数 | 必填 | 说明 |
|---|---|---|
| `goal` | 是 | 目标 |
| `name` | 否 | 工作流名；只保留中文/字母/数字/`_`/`-`，最长 40；不填生成 `agent_plan_时间戳` |
| `run` | 否 | `true` 写完立即交给 `workflow_runner.start_async` 后台跑 |
| `overwrite` | 否 | 同名文件默认不覆盖；要覆盖必须显式 `true` |

```python
r = trunk.call(
    "agent_planner", "plan_to_workflow",
    "整理一份本地 7B vs 云端 32B 的对比简报",
    name="local_vs_cloud",
    run=False,
)
print(r["文件"], r["步骤"], r["已启动"])
```

返回：`ok`、`目标`、`工作流`、`文件`、`步骤`、`已启动`、`计划`。
同名文件已存在且未允许覆盖：`ok=False`，`PLUGIN_BAD_INPUT`。

转换规则（计划 → 工作流）：

- `search` → `query`；`llm` → `prompt`；`code` → `code`；`set` → `value`；`wait` → `seconds`；
- 只有一个依赖时写成 `when: 前一步的标题`（`workflow_runner` 的条件只支持单依赖）；
- 多个依赖不会被展开成并行/扇入，执行时按顺序跑；
- 写入用临时文件 + `os.replace`，失败返回 `PLUGIN_INTERNAL_ERROR`。

### 4.4 `agent_plan_next(steps, done="")`

| 参数 | 必填 | 说明 |
|---|---|---|
| `steps` | 是 | 步骤列表；工具调用时传 JSON 字符串，Python 里可直接传 list |
| `done` | 否 | 已完成的 id，逗号分隔；Python 里也可传 list |

```python
r = trunk.call("agent_planner", "next_steps", plan["步骤"], done="s1")
print("现在能做:", r["可执行"])
print("被阻塞:", r["阻塞"])
print("还剩:", r["剩余"])
```

返回：`ok`、`可执行`、`阻塞`、`剩余`、`已完成`。
`done` 里不存在的 id 会原样出现在 `已完成`；步骤里不存在的依赖会被忽略。

### 4.5 失败与边界

| 情况 | 表现 |
|---|---|
| 缺 `goal` | `PLUGIN_MISSING_ARG` |
| `steps` 不是合法 JSON / 不是列表 | `PLUGIN_BAD_INPUT` |
| 同名工作流已存在 | `PLUGIN_BAD_INPUT`（提示 `overwrite=true`） |
| `workflow_runner` 不可用 | 文件仍写入，`已启动=False` |
| LLM 不可用 | 使用通用 4 步模板，`llm=False` + `警告` |
| LLM 有回复但 JSON 无法解析 | 同样回退通用模板；`llm` 可能仍为 `true`，原因见 `_last_error` |

---

## 五、端到端示例：从目标到工作流

```python
# 1) 拆计划
plan = trunk.call("agent_planner", "plan", "给项目补一份发布前检查清单")
steps = plan["步骤"]

# 2) 看当前能做什么
now = trunk.call("agent_planner", "next_steps", steps, done="")
print(now["可执行"], now["阻塞"])

# 3) 落成工作流（不自动跑）
wf = trunk.call("agent_planner", "plan_to_workflow",
                "给项目补一份发布前检查清单", name="release_checklist")
print(wf["文件"])

# 4) 后台运行并查状态
trunk.call("workflow_runner", "start_async", "release_checklist", {"input": "发布前检查"})
print(trunk.call("workflow_runner", "status"))
```

对应的 GUI 入口：`Ctrl+K` → 搜“日历待办”（打开「实用工具」对话框）→ 切到「工作流」tab
（`gui/tools_dialog.py` 内复用，不新增按钮）→ 选择 `release_checklist` → 运行。

---

## 六、常见问题

**Q1：Ctrl+K 里搜不到某个工具？**
先确认模块已安装（设置 → 扩展 → 插件市场），再试上表里的提示词（匹配靠 `hints`，不是只认工具名）。三个模块的 `TOOLS` 会自动进入能力注册表，不需要重启程序。

**Q2：提示「agent_xxx」没装好 / 功能不可用？**
检查 `modules/installed/` 是否有对应文件，以及 `modules_repo` / `plugin_repo` 是否同步。发布前可用：

```powershell
py -3 tools/check_repo_sync.py
py -3 tools/check_plugin_repo.py
```

**Q3：没有配模型，还能用吗？**

- 分析：能用，返回 `llm=False` 的结构化兜底；
- 编码：`solve` 返回 `PLUGIN_NOT_AVAILABLE`；`review` 仍返回 `compile` 检查结果（`llm=False`，说明里注明没做静态审查）；`run_code` 照常在沙箱执行；
- 规划：返回 4 步通用模板，`llm=False` + `警告`。

**Q4：计划写进 `data/workflows/` 了，但没跑起来？**
看 `workflow_runner.status` 的 `running` / `last.error`；确认工作流文件名与 `name` 一致（`.yaml` 或 PyYAML 缺失时的 `.json`），以及 `run=true` 是否真的传了。定时触发需要工作流里写 `schedule`（cron 5 段）。

**Q5：沙箱超时怎么办？**
`agent_code_solve` 沿用 `code_runner.timeout`（默认 10 秒）；需要更久就用 `agent_code_run` 显式传 `timeout`（秒）。不要靠死循环长时间占用。

**Q6：对比结果为什么没有变化率？**
变化率以“左侧”为分母；左侧为 0 时只给差值，变化率留空。两边数字数量不一致时，只配对能对上的部分。

---

## 七、相关文件

| 文件 | 作用 |
|---|---|
| `modules/installed/agent_analyst.py` | 分析专家：证据、数值对比、风险 |
| `modules/installed/agent_coder.py` | 编程小匠：生成、沙箱执行、自动修、审查 |
| `modules/installed/agent_planner.py` | 策划专家：JSON 计划、工作流、下一步 |
| `modules/installed/workflow_runner.py` | 执行计划生成的工作流 |
| `modules/installed/code_runner.py` | 进程级 Python 沙箱 |
| `modules/installed/deep_search.py` / `graph_rag.py` | 分析与计划的外部/本地证据 |
| `gui/command_palette.py` | `Ctrl+K` 能力入口 |
| `tests/test_lowcov_modules_extra.py` | 三个智能体的主路径回归用例 |
| `tests/test_agents_toolchain.py` | 三个智能体的分支/降级/错误码单元测试（假 LLM/搜索/沙箱，不联网） |

---

## 附录：模块标准

> 原文件 `docs/MODULE_STANDARD.md`，2026-10-30 合并入本文。

# 模块级程序标准（Module-Level Program Standard）v1.0

> 本文件是外部给的通用模块标准原文，作为对照基线保留。
> 小6 的落地情况与差异见本文「附录：插件标准 v2.1」第五节对照表，
> 用户版见根目录 `插件标准.txt`。

适用范围：单个可独立开发、测试、发布、复用的模块级程序，包括库、插件、
MCP 服务、Agent 工具等。

分级说明：必须（MUST）= 硬性要求；应当（SHOULD）= 默认要求，例外需说明；
建议（MAY）= 推荐实践。

---

## 一、接口契约

1.1 模块必须具有单一、明确的职责，并在文档中声明其边界与不负责的事项。
1.2 模块必须提供明确入口点，例如 `__init__.py`、`index.ts`、main 入口、
MCP 初始化接口或插件 manifest。
1.3 对外接口必须声明名称、参数类型、返回类型、异常/错误类型和副作用。
1.4 对外接口应当遵循接口隔离原则，只暴露调用方需要的方法，不强迫依赖无关能力。
1.5 输入输出应当使用稳定、可序列化的数据格式；跨进程/协议边界必须使用纯 JSON
可序列化类型。
1.6 基于协议的模块必须遵守对应协议规范；MCP 服务必须符合 JSON-RPC 2.0 的消息、
请求 ID、result/error 二选一等规则。
1.7 接口变更必须遵循语义化版本或等价兼容性策略，破坏性变更必须提升主版本并记录
迁移说明。

## 二、封装与边界

2.1 模块必须隐藏内部实现细节，外部只能通过公开接口访问。
2.2 模块必须遵循统一访问原则：同一能力只通过一致的公开入口暴露。
2.3 模块应当保持最小暴露面，不公开不必要的函数、类、配置项和内部数据结构。
2.4 模块不得要求调用方依赖其内部文件路径、私有变量或未声明的实现细节。
2.5 模块边界必须清晰：不得越过边界直接读写其他模块的持久层、缓存或内部状态。

## 三、依赖管理

3.1 模块必须在清单文件中显式声明运行时依赖、开发依赖和可选依赖。
3.2 模块必须禁止循环依赖；跨模块依赖必须通过显式导入或显式协议调用完成。
3.3 模块应当保持高内聚、松耦合：内部元素高度相关，模块之间尽量独立。
3.4 模块不得隐式依赖全局状态、环境变量或未声明的外部服务；如需要，必须显式配置
并文档化。
3.5 依赖版本必须可锁定或可复现；发布物应当附带锁定文件或等价依赖约束。

## 四、生命周期与协议

4.1 模块必须定义初始化、运行、关闭/销毁的生命周期，并说明各阶段可执行的操作。
4.2 需要资源释放的模块必须提供清理机制，例如 close、dispose、shutdown 或上下文管理器。
4.3 基于协议的模块必须实现连接初始化、能力协商、会话控制和错误终止流程。
4.4 协议模块必须校验消息格式、必填字段、类型和请求 ID；非法消息必须返回结构化错误。
4.5 模块必须定义超时、重试、取消和并发安全策略；不适用时必须明确说明。

## 五、配置与安全

5.1 模块必须提供标准化配置入口，例如 Config 对象、配置文件、环境变量或命令行参数，
并声明优先级。
5.2 配置项必须文档化，包括名称、类型、默认值、是否必填、敏感性和影响范围。
5.3 模块不得硬编码密钥、令牌、密码等敏感信息；敏感配置必须通过安全注入方式提供。
5.4 模块必须对输入进行校验和边界检查，防止注入、路径穿越、反序列化等风险。
5.5 模块应当遵循最小权限原则，只申请完成职责所需的最小权限。

## 六、错误处理与可观测性

6.1 模块必须使用结构化错误，包含错误码、错误消息和必要的上下文；不得只返回无意义字符串。
6.2 模块必须区分可恢复错误与不可恢复错误，并说明调用方应如何处理。
6.3 模块应当提供标准日志接口，日志必须包含时间、级别、模块标识和关键上下文。
6.4 模块应当支持遥测或监控接入点，例如指标、追踪或健康检查；不适用时需说明。
6.5 模块不得吞掉异常；捕获异常后必须处理、转换或重新抛出并保留上下文。

## 七、文档标准

7.1 模块根目录必须包含 README，说明用途、安装、快速开始、配置和示例。
7.2 模块必须包含接口文档或 API 参考，覆盖所有公开接口、参数、返回值和错误。
7.3 模块应当包含 SPEC 或技术规格文档，说明架构、边界、依赖和设计约束。
7.4 面向 Agent/自动化调用的模块应当包含 AGENTS.md 或等价代理指南。
7.5 文档必须与代码版本同步；破坏性变更必须提供迁移指南。
7.6 模块应当提供可运行的最小示例，示例不得依赖未文档化的内部实现。

## 八、测试与验证

8.1 模块必须包含单元测试，覆盖所有公开接口和关键分支。
8.2 模块必须包含契约合规性测试，验证其是否真正实现声明的接口和协议。
8.3 模块应当包含集成测试，验证与依赖模块、外部服务或协议客户端的交互。
8.4 模块必须包含错误路径测试，包括非法输入、超时、依赖失败和资源耗尽场景。
8.5 发布前必须通过静态检查、类型检查、依赖漏洞检查和质量门禁。
8.6 测试必须可重复执行，不得依赖未声明的外部状态；需要外部服务时应提供 mock 或
容器化环境。

## 九、版本、发布与交付

9.1 模块必须具有唯一名称和语义化版本号。
9.2 发布物必须包含源码或可执行产物、依赖清单、许可证、README 和变更日志。
9.3 模块必须声明兼容的运行环境，例如语言版本、操作系统、协议版本和平台限制。
9.4 模块必须提供变更日志，记录新增、修复、弃用和破坏性变更。
9.5 模块应当提供可复现构建方式，例如构建脚本、容器或锁文件。
9.6 插件形态的模块必须遵循目标平台的 manifest、加载、卸载和权限规范。
9.7 MCP 形态的模块必须提供 MCP 服务配置、工具列表发现和协议版本声明。

## 十、质量门禁检查清单

- [ ] 职责单一且边界清晰
- [ ] 有明确入口点和公开接口契约
- [ ] 输入输出类型明确且可序列化
- [ ] 内部实现已封装，暴露面最小
- [ ] 依赖显式声明，无循环依赖
- [ ] 生命周期和资源释放已定义
- [ ] 协议消息符合规范并校验
- [ ] 配置项完整文档化，敏感信息未硬编码
- [ ] 错误结构化，日志可观测
- [ ] README、API 文档、SPEC/AGENTS 文档齐全
- [ ] 单元测试、契约测试、集成测试、错误路径测试通过
- [ ] 版本、许可证、变更日志、兼容环境已声明
- [ ] 构建可复现，质量门禁全部通过

## 附：模块交付最小文件集

```text
README.md
SPEC.md 或 API.md
AGENTS.md（面向 Agent 调用时）
依赖清单文件
配置文件示例
CHANGELOG.md
LICENSE
测试目录
构建/发布脚本
插件 manifest 或 MCP 服务配置（按形态提供）
```


---

## 对照结论（2026-10-22 现状）

本文件是外部《模块级程序标准 v1.0》原文，作为基线保留。
小6 的实际落地见本文「附录：插件标准 v2.1」与根目录 `插件标准.txt`。

### 落地情况摘要

| 条款组 | 状态 | 落地位置 |
|---|---|---|
| 1.x 接口契约 | ✅ | `core/tool_contract.py` + manifest |
| 2.x 封装边界 | ✅ | `PUBLIC_CORE_MODULES` 白名单 |
| 3.x 依赖管理 | 🟡 | 全局锁文件有；插件级 `requires` 待补 |
| 4.x 生命周期 | ✅ | `core/module_lifecycle.py`（start/stop/health） |
| 5.x 配置安全 | ✅ | capabilities + `get_secret` 代理 |
| 6.x 错误可观测 | ✅ | `core/plugin_errors.py`（18 个错误码）+ 审计 |
| 7.x 文档 | 🟡 | 全局文档齐全；插件级 README/AGENTS 待补 |
| 8.x 测试 | ✅ | 框架级 + 插件级双层契约测试 |
| 9.x 版本发布 | ✅ | SemVer 三段式 + RSA 签名 + 仓库 LICENSE 待补 |

### 门禁命令

```powershell
py -3 tools/check_plugin_quality.py     # 48 模块，error 必须为 0
py -3 tools/check_plugin_tier.py        # L1/L2/L3 推导一致
py -3 tools/check_plugin_deps.py --ast  # 依赖边界 + 环检测
py -3 tools/check_plugin_security.py    # 配置/路径/密钥/L3 专项
py -3 tools/verify_signature.py --all   # RSA 签名 + 公钥位数
```

---

## 附录：插件标准

> 原文件 `docs/PLUGIN_STANDARD.md`，2026-10-30 合并入本文。

# 小6插件标准 v2.1（模块级程序标准整合修订版）

> [MUST]/[SHOULD]/[MAY] 分级 · [全]/[PY]/[MCP]/[L3] 形态标记 · L1/L2/L3 插件分级

- **适用版本**：v25.2.23 起
- **状态**：已落地并强制执行（不是建议稿）
- **更新日期**：2026-10-21

## 事实源（代码即标准）

| 源文件 | 对应标准 |
|---|---|
| `core/plugin_api.py` | 插件 API v1.0、公共模块白名单、依赖边界 |
| `core/plugin_capabilities.py` | 能力声明 schema、风险分级 |
| `core/plugin_errors.py` | 结构化错误码（标准 6.1/6.2） |
| `core/module_lifecycle.py` | 生命周期状态机（标准 4.1/4.2/6.4） |
| `core/tool_contract.py` | 工具接口契约（标准 1.3/1.5） |
| `core/plugin_broker.py` | 运行时权限代理（标准 5.5） |
| `core/plugin_registry.py` | 版本/兼容/信任等级 |
| `modules_repo/manifest.json` | 官方插件清单（RSA 签名） |

## 自动门禁

```powershell
py -3 tools/check_plugin_quality.py            # 质量门禁（error 必须为 0）
py -3 tools/check_plugin_quality.py --strict   # 连 warn 也算失败
py -3 tools/check_plugin_api.py                 # API 边界
py -3 tools/check_plugin_repo.py               # 签名与哈希
py -3 -m pytest tests/test_plugin_standard.py tests/test_module_standard.py -q
```

---

## 一、适用范围

本程序里的"插件"包括：

1. `modules/installed/` 里的功能模块（42 个官方模块）
2. 第三方插件（未来通过插件市场安装）
3. 以插件形态封装的 Agent 工具 / MCP 客户端

**不适用于**：`core/` 内核模块、`gui/` 界面代码（它们另有 file_size / thread 等守卫）。

---

## 二、与《模块级程序标准 v1.0》的对应关系

本标准 = 模块级程序标准（通用）+ 插件安全标准（本程序特有）。

- **第 1 层**　模块级程序标准　管"是不是一个合格模块"
- **第 2 层**　插件标准（本文）　管"作为插件是否安全可装、可运行"
- **第 3 层**　运行时权限模型　管"运行时实际能做什么"（broker 强制）

逐条对照（M=必须 S=应当 Y=建议）：

| 模块级标准条款 | 本程序状态 | 落地位置 |
|---|---|---|
| 1.1 职责单一 + 声明边界 | 已落地 | `BaseModule.describe()` / `NOT_RESPONSIBLE` |
| 1.2 明确入口点 | 已落地 | `BaseModule.run()` + `manifest.json` |
| 1.3 接口契约（类型/返回/错误/副作用） | 已落地 | `core/tool_contract.py`（contract 字段） |
| 1.4 接口隔离 | 已落地 | `PUBLIC_CORE_MODULES` 白名单 |
| 1.5 纯 JSON 可序列化 | 已落地 | broker/worker JSON-RPC + `is_json_serializable` |
| 1.6 遵循协议规范（MCP/JSON-RPC） | 已落地 | `core/mcp_stdio.py`（2024-11-05） |
| 1.7 语义化版本 + 兼容策略 | 已落地 | `api_version` + `min/max_host_version` |
| 2.1 隐藏内部实现 | 已落地 | broker 只暴露受限 ctx |
| 2.2 统一访问原则 | 部分 | 存在多入口，见第六节待改进 |
| 2.3 最小暴露面 | 已落地 | 能力白名单 + 权限代理 |
| 2.4 不依赖内部路径 | 已落地 | 禁止 `core.trunk` / `secret_store` 等前缀 |
| 2.5 不越界读写他人持久层 | 已落地 | 插件只能写 `data/plugin_data/<名>/` |
| 3.1 显式声明依赖 | 部分 | 全局 lock 有，插件级待补 |
| 3.2 禁止循环依赖 | 已落地 | `check_shapes` 星型拓扑检查 |
| 3.3 高内聚低耦合 | 部分 | 靠评审 |
| 3.4 不隐式依赖全局状态 | 部分 | 质量门禁 warn（环境变量/global/相对路径） |
| 3.5 依赖可锁定 | 已落地 | `requirements-*.lock` |
| 4.1 生命周期定义 | 已落地 | `core/module_lifecycle.py` |
| 4.2 资源释放机制 | 已落地 | `stop/close/shutdown`（幂等） |
| 4.3 连接/协商/会话/错误终止 | 已落地 | MCP 客户端实现 |
| 4.4 协议消息校验 | 已落地 | JSON-RPC 校验 + 结构化错误 |
| 4.5 超时/重试/取消/并发 | 已落地 | broker 超时、MCP timeout、Job Object |
| 5.1 配置入口与优先级 | 部分 | 见第五节配置优先级 |
| 5.2 配置项文档化 | 部分 | docs/30 汇总，插件级待补 |
| 5.3 不硬编码密钥 | 已落地 | `check_secrets` + 质量门禁扫描 |
| 5.4 输入校验与路径穿越防护 | 已落地 | `safe_join` / `safe_plugin_filename` |
| 5.5 最小权限 | 已落地 | capabilities + 风险分级 |
| 6.1 结构化错误 | 已落地 | `core/plugin_errors.py` |
| 6.2 可恢复/不可恢复区分 | 已落地 | `error.retryable` |
| 6.3 标准日志接口 | 部分 | `trunk._log`，插件未强制 |
| 6.4 遥测/指标/健康检查 | 已落地 | `BaseModule.health()`/`stats()` |
| 6.5 不吞异常 | 已落地 | `check_silent` + 质量门禁（带理由豁免） |
| 7.1 模块 README | 未落地 | 见第七节待补 |
| 7.2 接口文档/API 参考 | 部分 | 全局 docs/30，插件级待补 |
| 7.3 SPEC 技术规格 | 部分 | 本文「附录：插件标准 v2.1」 |
| 7.4 AGENTS.md 代理指南 | 未落地 | 见第七节待补 |
| 7.5 文档与代码同步 | 已落地 | `tests/test_docs_consistency.py` |
| 7.6 最小可运行示例 | 部分 | `docs/examples/plugins/hello_plugin.py` |
| 8.1 单元测试 | 部分 | 内置模块有，插件级不完整 |
| 8.2 契约合规测试 | 已落地 | `tests/test_plugin_standard.py` |
| 8.3 集成测试 | 部分 | 见第七节待补 |
| 8.4 错误路径测试 | 部分 | 见第七节待补 |
| 8.5 静态/类型/漏洞/门禁 | 已落地 | Ruff+Mypy+Bandit+pip-audit+SBOM+质量门禁 |
| 8.6 测试可重复 | 已落地 | conftest 隔离 + mock |
| 9.1 唯一名称 + 语义化版本 | 部分 | 名称有；部分插件 version 非三段式 |
| 9.2 发布物含许可证/README/变更日志 | 未落地 | 仓库无 LICENSE，见第七节 |
| 9.3 声明兼容运行环境 | 已落地 | docs/70 兼容矩阵 |
| 9.4 变更日志 | 部分 | 全局 CHANGELOG，插件级待补 |
| 9.5 可复现构建 | 已落地 | `xiao6.spec` + lock 文件 |
| 9.6 manifest/加载/卸载/权限规范 | 部分 | 卸载仍改源码，见第六节 |
| 9.7 MCP 服务配置/工具发现/协议声明 | 已落地 | `tools/list` + `protocolVersion` |
| 第十节 质量门禁清单 | 已落地 | `tools/check_plugin_quality.py` |

---

## 三、本程序特有的强制标准（模块级标准没有覆盖）

### S-SIGN　RSA 签名 + sha256 校验

- 清单每条必须有 `sha256` 与 `signature`
- `plugin_repo/.gitattributes` 固定 `* -text`，防止换行转换破坏哈希
- 远程安装：HTTPS + 主机白名单 + 验签，任一不满足即拒绝
- 远程插件即使开 `allow_unsigned_plugins` 也拒绝

### S-TRUST　信任等级

- `official` = `first_party=true` 且签名有效
- `signed` = 第三方且签名有效
- `unsigned` = 无签名（远程一律拒绝，本地默认拒绝）

### S-UPDATE　更新与回滚

- 更新前自动备份到 `data/plugin_backups/`
- 安装/更新记录写入 `data/plugin_ledger.json`
- 只提供与宿主版本、API 版本兼容的更新

### S-ISOLATE　运行时隔离

- 插件在受限 worker 中运行，只拿 `ctx.files` / `network` / `process` / `config` / `audit`
- 每次能力调用经 broker 授权，超出声明即拒绝
- 网络只允许 http/https 且必须在声明域名内
- 子进程只允许 manifest 中固定 argv

### S-RISK　风险自动分级

- `high` = `process` 或 `ui_control` 或 `config.read_secrets`
- `medium` = `network` 或 `filesystem.write`
- `low` = 其余

---

## 四、能力声明（capabilities）标准

5 个分段必须齐全，缺一段即不合格：

```json
"capabilities": {
  "network":    {"enabled": true,  "domains": ["api.example.com"], "methods": ["GET"]},
  "filesystem": {"read": ["data/plugin_data/<插件名>/notes"],
                 "write": ["data/plugin_data/<插件名>/cache"]},
  "process":    {"enabled": false, "allow_argv": []},
  "ui_control": {"enabled": false},
  "config":     {"read_secrets": false, "public_keys": ["theme"]}
}
```

规则要点：

- `network.enabled=true` 必须给 `domains` 与 `methods`（默认 `GET`）
- 域名只接受合法域名；额外允许回环地址 `localhost` / `127.0.0.1` / `::1`
  （插件连本地模型、MCP、浏览器调试端口需要）；带端口的地址不允许
- `filesystem` 路径必须落在 `data/plugin_data/<插件名>/` 内，
  绝对路径、`..`、盘符路径一律拒绝
- `process.allow_argv` 必须是固定 argv 数组，禁止 `; & | < > ` $ % 换行`，
  禁止 `cmd / powershell / bash / wscript / cscript` 包装器
- `config.public_keys` 不得出现 `key/token/secret/password/credential/private`

---

## 五、工具接口契约（contract 字段）

标准 1.3 要求声明名称、参数类型、返回类型、错误类型和副作用。
工具声明里可选加 `contract`（写了就强校验，没写计入"未声明契约"）：

```json
{
  "name": "weather_query",
  "method": "query",
  "desc": "查天气",
  "contract": {
    "params": {"city": {"type": "string", "required": true, "max_len": 64}},
    "returns": {"type": "object",
                "properties": {"temp": {"type": "number"},
                               "desc": {"type": "string"}}},
    "errors": ["PLUGIN_BAD_INPUT", "PLUGIN_UPSTREAM_ERROR", "PLUGIN_TIMEOUT"],
    "side_effects": ["network:GET wttr.in"],
    "idempotent": true,
    "timeout_ms": 8000,
    "concurrency_safe": true,
    "description": "按城市名查询实时天气",
    "not_responsible": ["预报", "历史数据"]
  }
}
```

- **类型白名单**：`string` / `integer` / `number` / `boolean` / `array` / `object` / `null`
- **副作用白名单**：`network` / `filesystem_read` / `filesystem_write` / `process` / `ui_control` / `config_write`

---

## 六、结构化错误（标准 6.1 / 6.2）

统一格式：

```json
{"error": {"code": "PLUGIN_TIMEOUT",
           "message": "天气服务 8 秒内没有响应",
           "retryable": true,
           "context": {"module": "weather", "upstream": "wttr.in"},
           "schema_version": "1.0"}}
```

错误码表（新增必须登记到 `core/plugin_errors.ERROR_CATALOG`）：

| 错误码 | 含义 | 可恢复性 |
|---|---|---|
| `PLUGIN_BAD_INPUT` | 参数不合法 | 不可恢复 |
| `PLUGIN_MISSING_ARG` | 缺少必填参数 | 不可恢复 |
| `PLUGIN_BAD_PATH` | 路径不合法 | 不可恢复 |
| `PLUGIN_PERMISSION_DENIED` | 能力未授权 | 不可恢复 |
| `PLUGIN_NEEDS_CONFIRM` | 需要用户确认 | 可恢复 |
| `PLUGIN_UNSUPPORTED_CAPABILITY` | 不具备该能力 | 不可恢复 |
| `PLUGIN_MISSING_DEPENDENCY` | 缺少依赖 | 不可恢复 |
| `PLUGIN_NOT_AVAILABLE` | 依赖服务不可用 | 可恢复 |
| `PLUGIN_TIMEOUT` | 执行超时 | 可恢复 |
| `PLUGIN_CANCELLED` | 已取消 | 可恢复 |
| `PLUGIN_BUSY` | 繁忙，稍后重试 | 可恢复 |
| `PLUGIN_UPSTREAM_ERROR` | 上游返回错误 | 可恢复 |
| `PLUGIN_RATE_LIMITED` | 被限流 | 可恢复 |
| `PLUGIN_RESOURCE_EXHAUSTED` | 资源耗尽 | 可恢复 |
| `PLUGIN_BAD_OUTPUT` | 返回格式不符合契约 | 不可恢复 |
| `PLUGIN_NOT_IMPLEMENTED` | 尚未实现 | 不可恢复 |
| `PLUGIN_INTERNAL_ERROR` | 插件内部错误 | 不可恢复 |
| `PLUGIN_UNKNOWN` | 未知错误 | 不可恢复 |

**迁移**：历史 `return {"错误": "..."}` 可继续工作，
用 `core.plugin_errors.normalize_error()` 统一转换（会自动推断错误码）。

---

## 七、生命周期标准（标准 4.1 / 4.2 / 6.4）

状态机：`new -> started -> stopped`（可 `restart`）

接口（`BaseModule` 已默认实现，子类按需覆盖钩子）：

| 接口 | 说明 |
|---|---|
| `start()` | 一次性准备；失败会自动回滚到 stopped |
| `run()` | 真正干活，可并发调用 |
| `stop()` | 幂等；重复调用返回 `already_stopped` 且**不再执行清理逻辑** |
| `close()` / `shutdown()` | `stop()` 的别名 |
| `health()` | 快速返回 `{ok, stage, uptime_s, start_count, stop_count}` |
| `describe()` | 返回 `{name, version, purpose, not_responsible}` |

子类只需覆盖 `_on_start()` / `_on_stop()`，不必自己管状态机。

---

## 八、质量门禁（标准第十节落地）

命令：`py -3 tools/check_plugin_quality.py [--strict] [--json]`

检查项（error 级，必须为 0）：

1. 清单必填字段齐全
2. `api_version` 在支持列表
3. capabilities 5 段齐全
4. 已签名 + 有 `sha256`
5. 源码存在
6. 依赖边界（只能 import 公共 core 模块）
7. 无硬编码密钥
8. 无未标注理由的 `except pass`
9. 有入口 `run()`
10. 工具 contract 合法（写了就校验）

检查项（warn 级，逐步收敛）：

- 未声明 `stop()`/`close()`
- 未声明"不负责的事项"
- 模块缺 docstring
- 工具未声明 contract
- 直接读环境变量 / `global` / 相对路径 / 模块级可变容器
- 返回 `{"错误": ...}` 旧式文本
- `version` 非语义化三段式

当前实测（2026-10-22）：

```text
模块 48 · error 0 · warn 142 → 门禁通过
```

---

## 九、交付最小文件集（对模块级标准附录）

单个插件建议目录结构：

```text
<插件名>/
    README.md          用途、安装、快速开始、配置、示例
    API.md             公开接口、参数、返回值、错误码
    AGENTS.md          面向 Agent 的调用指南（标准 7.4）
    SPEC.md            架构、边界、依赖、设计约束
    CHANGELOG.md       插件级变更记录
    manifest.json      清单（本程序格式）
    <插件名>.py        实现
    examples/          可运行最小示例
    tests/             单元 + 契约 + 错误路径测试
```

注：官方 48 个模块当前为"平铺 + 统一 manifest"形态，
上面的目录结构是**新增插件**的推荐形态，存量模块逐步迁移。

---

## 十、发布流程

```powershell
# 1. 模块放入 modules/installed/，在 core/lazy_config.py 登记
# 2. 同步到仓库（自动生成标准 capabilities）
py -3 tools/rebuild_modules_repo.py --apply
# 3. 签名
set X6_KEY_VAULT=E:\xiao6-keys
py -3 tools/sign_modules.py
# 4. 发布到 GitHub 公共镜像
py -3 tools/sync_plugin_repo.py --apply
# 5. 全量验证
py -3 tools/check_plugin_quality.py
py -3 tools/check_plugin_api.py
py -3 tools/check_plugin_repo.py
py -3 -m pytest tests/test_plugin_standard.py tests/test_module_standard.py -q
```

---

## 十一、官方模块合规现状（2026-10-21）

```text
模块总数                42
声明 capabilities       42 / 42
5 段齐全                42 / 42
已签名                  42 / 42
api_version = 1.0       42 / 42
清单+源码校验通过       42 / 42
legacy（未声明能力）    0
质量门禁 error          0
质量门禁 warn           81（逐步收敛，不阻塞发布）
```

高风险显式声明：

| 模块 | 声明 |
|---|---|
| `computer_controller` | `ui_control.enabled = true` |
| `code_runner` | `process.enabled = true`，`allow_argv = [["python"],["py"]]` |
| `weather` | `network.enabled = true`（wttr.in / open-meteo） |
| `deep_search` | `network.enabled = true`（duckduckgo / bing / brave） |
| `browser`, `mcp_client` | `network` 仅回环地址 |

---

## 十二、已知差距与后续计划

**P0（影响"合格模块"判定）**

1. 插件级依赖声明：manifest 增加 `requires` / `optional_requires` / `system`
2. 插件级 README / API.md 生成与校验
3. 插件级单元测试与错误路径测试覆盖
4. 仓库 LICENSE

**P1**

5. AGENTS.md 规范与模板
6. 配置优先级显式化：
   `config.default.json -> data/config.json -> data/team/central_config.json -> 环境变量（仅明确列出的键）`
7. 卸载改为 manifest 驱动，不再修改 `core/lazy_config.py` 源码
8. 插件级 CHANGELOG

**P2**

9. 遥测/指标统一出口（Prometheus 或 JSON 指标）
10. 插件目录结构迁移（平铺 -> 目录化）
11. 全量工具 contract 覆盖（当前多数工具未声明）

---

## 十三、v2.1 落地：分级、审计、熔断、密钥与门禁（2026-10-21）

### 13.1 插件分级 L1/L2/L3（自动推导）

- 推导函数 `core/plugin_tier.py::derive(capabilities)`
- **L3 系统型**：`process.enabled` 或 `ui_control.enabled` 或 `config.read_secrets`
- **L2 IO 型**：`network.enabled` 或 `filesystem.write` 非空
- **L1 计算型**：其余（豁免 N4.3/N4.4/N4.5/N6.4/N8.3）
- manifest 的 `plugin_tier` / `risk_level` 由 capabilities 自动写入，
  手写值与推导值不一致时以推导值覆盖并告警。
- 当前分布：**L1 = 36，L2 = 4，L3 = 2**（code_runner / computer_controller）

### 13.2 审计日志（N15）

- `core/plugin_audit.py`
- 每条记录字段：`ts`(ISO-8601 UTC) / `plugin` / `version` / `action` /
  `capability` / `allowed` / `detail` / `session_id`
- 敏感字段写盘前由 `core/redaction` 脱敏；写失败只计数不阻断。
- 默认保留 **90 天**，`purge_expired()` 清理过期记录。

### 13.3 熔断与资源上限（N13）

- `core/plugin_limits.py`
- **熔断**：连续失败 **5 次** → 熔断，冷却 **60 秒**，错误码 `PLUGIN_CIRCUIT_OPEN`
- **限额**：单次调用 30s / 单插件内存 512MB / 单次写 100MB / 网络 60 次每分钟
- 超限错误码 `PLUGIN_RESOURCE_EXHAUSTED`

### 13.4 凭据读取（S3/S7）

插件必须在 `capabilities.config` 声明 `read_secrets=true` 与 `secret_names` 列表，
经 `ctx.config.get_secret(name)` 由 broker 代理读取；
未声明即拒绝；审计只记录凭据"名字"，不记录值。

### 13.5 签名算法明细（S5）

- RSA ≥ **2048**（实测 2048）/ RSASSA-PKCS1-v1_5 / SHA-256 / Base64 无换行
- 校验证书链与吊销列表：`config/plugin_key_revocation.json`
- 工具：`py -3 tools/verify_signature.py --all`

### 13.6 回环端口规则（S3）

允许 `localhost:8080` / `127.0.0.1:5000` / `[::1]:3000` 这类回环+端口写法；
非回环域名一律禁止带端口。

### 13.7 版本规范（N9.1）

- `version` 必须三段式语义化；历史 `"1.0"`/`"5.1"` 已统一补成 `"1.0.0"`/`"5.1.0"`。
- `api_version` 与 `version` 语义分离：前者精确匹配，后者语义化。

### 13.8 manifest v2.1 新增字段

- **必填**：`license` / `author` / `min_host_version` / `plugin_tier` / `risk_level`
- **条件必填**：`dev_depends` / `optional_depends` / `homepage` / `changelog_url` / `data_version`
- 当前实测：**48/48** 全部具备

### 13.9 发布与门禁命令（全部必须通过）

```powershell
py -3 tools/check_plugin_repo.py
py -3 tools/check_plugin_api.py
py -3 tools/check_plugin_quality.py
py -3 tools/check_plugin_tier.py
py -3 tools/check_plugin_deps.py --ast
py -3 tools/check_plugin_security.py
py -3 tools/verify_signature.py --all
py -3 -m pytest tests/test_plugin_standard.py tests/test_plugin_standard_v21.py tests/test_plugin_contract.py -q
```

### 13.10 插件级契约测试（N8.2b）

- `tests/test_plugin_contract.py`　框架级批量契约测试（48 模块）
- `templates/plugin_contract_test.py`　单个插件的契约测试模板
- 覆盖：入口可实例化 / tools 方法存在 / 生命周期幂等 / stats JSON 可序列化

### 13.11 当前实测（2026-10-22）

```text
模块 48 · 质量门禁 error 0 · 分级一致 48/48 · 依赖无环
签名有效 48/48（RSA 2048） · 安全检查 error 0
测试：test_plugin_standard 17 · v21 19 · contract 29 全通过
```

---

## 十四、仍待补齐（诚实清单）

- **P0**　仓库 LICENSE 文件；插件级 README/API/AGENTS 文档；插件级依赖声明字段落地
- **P1**　配置优先级显式化；manifest 驱动卸载；插件级 CHANGELOG；密钥吊销接口
- **P2**　遥测指标出口；插件目录化；工具 contract 全覆盖（当前多数未声明）

---

> 文档同步：2026-10-21 / 插件标准 v2.1 / 事实源以代码为准
>
> 相关文档：本文「附录：插件 SDK」（开发指南）、本文「附录：模块标准」（模块级标准对照）
>
> 用户版权威事实源：根目录 `插件标准.txt`

---

## 附录：v1.0 版保留的参考细节（与 v2.1 正文不冲突，备查）

> 以下内容来自本文件 v1.0 版，v2.1 正文未逐条重述，但仍为实现事实，保留备查。

### 附录 A　manifest 清单必填字段示例

每个模块在 `modules_repo/manifest.json` 里必须有：

```json
{
  "name": "weather",
  "title": "天气查询",
  "file": "weather.py",
  "cls": "Weather",
  "desc": "查询实时天气",
  "group": "联网检索",
  "version": "1.0",
  "api_version": "1.0",
  "first_party": true,
  "needs_model": false,
  "depends": [],
  "tools": [],
  "size": 3029,
  "sha256": "…",
  "signature": "…",
  "capabilities": { … }
}
```

缺任何一项都按不合格处理（`tests/test_plugin_standard.py` 会红）。

API 版本常量：

```python
PLUGIN_API_VERSION = "1.0"
SUPPORTED_PLUGIN_API = {"1.0"}
```

- 不写 `api_version` → `legacy=True`，只给警告，但**新发布必须写**。
- 写了不支持的版本 → 直接拒绝安装。
- 版本号是硬比较，不做范围匹配。

### 附录 B　依赖边界白名单与禁止前缀

第三方插件只能依赖 `PUBLIC_CORE_MODULES` 里的公共模块，例如：

```text
core.safe / core.error_text / core.path_safety / core.document_parser
core.net_guard / core.permission_center / core.audit_log / core.retrieval
core.fts_index / core.plugin_api / core.lazy_config / core.plugin_signer
```

**永远禁止**（`FORBIDDEN_CORE_PREFIXES`）：

```text
core.trunk*  core.data_schema  core.data_migrations  core.secret_store
core.default_secrets  core.license_*  core.auth  core.pipeline
core.release_sign  core._deprecated
```

另外：

- 禁止 `from core import *`。
- 禁止从 core 导入下划线开头的私有符号。
- 官方模块（`first_party: true`）可额外依赖少量审计过的集成层
  （`core.computer_*` / `core.mcp_stdio` 等），但私有实现同样禁止。

检查方式：AST 解析源文件，**不执行插件代码**。

### 附录 C　v1.1 / v2.1 早期落地备注

- `core/plugin_errors.py`：18 个结构化错误码 + `retryable` + `context`
- `core/module_lifecycle.py`：`start/stop/health` 幂等状态机
- `core/tool_contract.py`：工具 contract 字段校验
- `tools/check_plugin_quality.py`：48 模块质量门禁（error 必须为 0）
- 基类升级：`BaseModule` 继承 `LifecycleMixin`，新增 `NOT_RESPONSIBLE` 与 `describe()`；
  `agent_generic` 同步继承 `BaseModule`。
- 门禁首跑发现的真实问题：3 个 agent 模块缺 run；3 处 except pass 无理由；
  localhost 无法通过域名白名单；生成能力时漏 filesystem 段。均已修复。
- 早期实测：模块 42 · error 0 · warn 125 · 全部已签名 · 0 个 legacy。

新增模块与工具（v2.1 早期登记，后并入正文第十三节）：

| 模块 | 职责 |
|---|---|
| `core/plugin_tier.py` | L1/L2/L3 分级与 risk_level 自动推导 |
| `core/plugin_audit.py` | N15 审计日志（8 字段 + 脱敏 + 保留期） |
| `core/plugin_limits.py` | N13 熔断 + 资源上限 + 限流 |

| 工具 | 作用 |
|---|---|
| `tools/check_plugin_tier.py` | 分级一致性校验 |
| `tools/check_plugin_deps.py` | 依赖语法 + 环检测 + AST 边界 |
| `tools/check_plugin_security.py` | 配置/路径/密钥/审计/L3 专项 |
| `tools/verify_signature.py` | RSA 签名 + 公钥位数 + CRL |

| 测试 | 覆盖 |
|---|---|
| `tests/test_plugin_contract.py` | 48 模块批量契约（29 项） |
| `tests/test_plugin_standard_v21.py` | v2.1 组件单测（19 项） |
| `templates/plugin_contract_test.py` | 单插件模板 |


---

## 13. v2.1 落地核对（2026-10-22）

| 条款 | 落地 | 位置 |
|---|---|---|
| §0.3 分级 L1/L2/L3 | ✅ | `core/plugin_tier.py` |
| S1 manifest 必填 | ✅ 48/48 | `modules_repo/manifest.json` |
| S2 api_version | ✅ | `core/plugin_api.py` |
| S3 capabilities + 回环端口 | ✅ | `core/plugin_capabilities.py` |
| S4 依赖边界 | ✅ | AST 扫描 + `check_plugin_deps.py` |
| S5 签名 RSA2048 | ✅ 48/48 | `tools/verify_signature.py` |
| S6 路径越界 | ✅ | `check_plugin_security.py --paths` |
| S7 运行时隔离 | ✅ | `core/plugin_broker.py` |
| S8 信任等级 | ✅ | `core/plugin_registry.py` |
| N6 结构化错误 | ✅ | `core/plugin_errors.py` |
| N8 双层契约测试 | ✅ | `test_plugin_standard.py` + `test_plugin_contract.py` |
| N13 熔断/限额 | ✅ | `core/plugin_limits.py` |
| N15 审计 | ✅ | `core/plugin_audit.py` |

### 当前实测

```text
模块 48 · 质量门禁 error 0
分级一致 48/48
签名有效 48/48（RSA 2048）
依赖无环
```

### 仍未落地（P0）

1. 仓库 LICENSE 文件
2. 插件级 README / API.md / AGENTS.md
3. manifest `requires` 依赖声明字段

---

## 附录：插件 SDK

> 原文件 `docs/PLUGIN_SDK.md`，2026-10-30 合并入本文。

# Isolated Plugin SDK

> 完整的强制性规范（清单必填字段、能力 5 段、依赖边界、签名、风险等级）
> 见本文 **「附录：插件标准 v2.1」**。本文只讲怎么写一个插件。

Plugins run through a broker/worker boundary. They do not receive `trunk`,
`os`, `subprocess`, raw filesystem paths or API keys.

## Manifest

```json
{
  "name": "hello",
  "file": "hello.py",
  "cls": "HelloPlugin",
  "version": "1.0.0",
  "api_version": "1.0",
  "first_party": false,
  "publisher": "example",
  "min_host_version": "25.0.0",
  "capabilities": {
    "filesystem": {"read": ["notes"], "write": ["notes"]},
    "network": {"enabled": true, "domains": ["api.example.com"]},
    "process": {"enabled": false},
    "config": {"public_keys": ["theme"]}
  },
  "sha256": "...",
  "signature": "..."
}
```

## Capability Rules

- `filesystem`: only plugin-scoped `data/plugin_data/<name>/` paths
- `network`: HTTPS only, declared host allowlist
- `process`: fixed argv only, no shell, bounded output/time
- `config`: public keys only
- `ui_control`: requires explicit user confirmation
- `secrets`: never returned to plugin code

## Trust Tiers

- `official`: first-party + valid signature
- `signed`: third-party + valid signature
- `unsigned`: denied for remote installs and denied by default locally

## Versioning

The host checks `api_version`, `min_host_version` and `max_host_version`.
Updates are only offered when compatible. The market keeps a rollback copy
before applying an update.

## Example

See `docs/examples/plugins/hello_plugin.py`.


---

## 插件运行时能力（2026-10-22 更新）

### 可用的上下文对象

```python
ctx.files.read(path, max_bytes=65536)
ctx.files.write(path, text, append=False)
ctx.network.request(url, method="GET", headers=None, body=None, timeout=10)
ctx.process.run(argv, timeout=15)
ctx.config.get_public(key)
ctx.config.get_secret(name)      # 需 capabilities.config.read_secrets
ctx.audit.record(event)
```

### 网络与局域网

插件只能访问 `capabilities.network.domains` 里声明的域名。
若插件需要连本机服务，声明回环地址：

```json
"network": {
  "enabled": true,
  "domains": ["127.0.0.1:5000", "localhost:8080"],
  "methods": ["GET"]
}
```

非回环域名**不允许带端口**。局域网私有地址（192.168.x.x）
即使声明也会被网络守卫拒绝 —— 那是宿主的 `allow_lan_*` 策略，
不开放给插件。

### 资源上限（v2.1 N13）

| 限制 | 默认值 |
|---|---|
| 单次调用 | 30s |
| 内存 | 512MB |
| 单次写盘 | 100MB |
| 网络频率 | 60 次/分钟 |
| 熔断 | 连续失败 5 次 → 冷却 60s |

---

## 附录：插件审计 v2.1（总表）

> 原文件 `docs/plugin_audit_v21.md`，2026-10-30 合并入本文。

# 插件标准 v2.1 合规审计总报告（42 模块全量）

- **审计日期**：2026-10-21
- **权威标准**：《小6插件标准 v2.1》（`E:\xiaoliu\插件标准.txt`，14 节，MUST/SHOULD/MAY 分级）
- **审计对象**：`E:\xiaoliu\modules\installed\` 下 42 个官方插件模块（agent_analyst ~ weather，voice 的清单条目名为 stt）
- **判定口径**：仅以强制项（MUST）为准——manifest 必填字段、version 三段式、capabilities 5 段合规、tier/risk 推导一致、依赖边界、无硬编码密钥、无未标注裸吞异常、入口 run()、contract 合法、生命周期接口；第 12 节已知差距 P0/P1/P2 与第 14 节仍待补齐项（插件级 README/API/AGENTS、LICENSE、requires 字段、单测、CHANGELOG、配置优先级、manifest 驱动卸载、密钥吊销、遥测出口、目录化、工具 contract 全覆盖）允许未落地，warn 级问题不改。
- **基线**：审计前质量门禁 error=0、warn=125。

---

## 一、总览

| 结论 | 数量 | 说明 |
|---|---|---|
| ✅ 符合（无需修改） | 26 | 强制项全部通过 |
| 🔧 符合（已修复） | 14 | 审计发现问题并就地修复，修复后门禁复验通过 |
| ❌ 不符合（未修） | 2 | memory_cards、personality——数据文件被 core/gui 按旧路径共享，迁移须联动非插件代码，超出本轮修改边界，建议纳入主流程数据布局迁移 |

**42 个模块 = 40 符合 + 2 不符合未修（有明确原因与后续建议）**。

## 二、修复清单（14 个模块）

### 2.1 数据文件沙箱迁移（13 个，批次 2）

将模块私有持久化从 `data/` 根目录迁入 `data/plugin_data/<插件名>/` 沙箱（对应 manifest filesystem 声明目录），全部带旧路径一次性迁移（os.replace / os.rename，失败静默不阻断）：

| 模块 | 改动 |
|---|---|
| notes.py | notes.json → data/plugin_data/notes/ |
| todo.py | todo.json → data/plugin_data/todo/ |
| memory_loop.py | memory_loop.json、episodic_memory.json → data/plugin_data/memory_loop/ |
| multimodal.py | temp_frame.jpg、camera.jpg → data/plugin_data/multimodal/ |
| self_reflect.py | reflect_history.json → data/plugin_data/self_reflect/ |
| skill_capture.py | skills/、skills_pending/ → data/plugin_data/skill_capture/ |
| smart_router.py | router_cache.json → data/plugin_data/smart_router/ |
| task_loop.py | task_loop.json → data/plugin_data/task_loop/ |
| task_planner.py | tasks/ → data/plugin_data/task_planner/ |
| mcp_server.py | mcp_tools.json → data/plugin_data/mcp_server/ |
| mcp_client.py | mcp_trust.json → data/plugin_data/mcp_client/ |
| tts.py | 输出 mp3 → data/plugin_data/tts/ |
| voice.py | 临时 wav → data/plugin_data/stt/（与清单声明目录一致） |

已独立复核：core/、gui/、libs/ 均无对上述旧路径的引用，迁移不破坏集成。

### 2.2 裸异常加固（1 个，批次 1）

- **deep_search.py**：`_read_page()` 裸 `except:` 收窄为 `except Exception:` 并补注释——裸 except 会连 KeyboardInterrupt/SystemExit 一并吞掉，违反标准 6.5「不吞异常」。

### 2.3 门禁豁免注释（10 个，复验轮）

rebuild 后质量门禁复验发现 10 个模块（mcp_client/mcp_server/memory_loop/notes/self_reflect/skill_capture/smart_router/task_loop/task_planner/todo）的迁移逻辑 `except OSError: pass` 未标注理由，按门禁规则（pass 行前 3 行内出现「静默是故意的」或「nosec」即豁免）补注 `# 静默是故意的：旧数据（目录）迁移失败不阻断主流程`。修复后门禁 error=0。

## 三、不符合未修（2 个，需联动 core/gui）

| 模块 | 违反条款 | 原因 | 建议 |
|---|---|---|---|
| memory_cards | 第 4 节 filesystem 沙箱约束 | `data/memory_cards.jsonl` 被 core/memory_organizer.py、gui/stats_dialog.py、gui/memory_view_dialog.py 按旧路径直读，且登记在 core/data_schema.py 并由 core/data_migrations.py 管理版本迁移 | 纳入主流程统一数据布局迁移（需同轮改 core/gui） |
| personality | 第 4 节 filesystem 沙箱约束 | `data/personality.json` 是 core 级共享资产（data_schema 登记、data_migrations v0→v1→v2 迁移、growth_report 读取、personality_market 写入） | 同上 |

## 四、能力声明滞后观察项（登记备查，不影响强制项判定）

代码实际行为与 manifest 声明 capabilities 之间的差距（修复点在 manifest 重新推导，本次按修改边界未动 manifest，未做破坏功能的代码裁剪）：

1. **image_ocr**：`requests.post` 直连 open.bigmodel.cn、从 config 读 cloud_api_key，但声明 network=false / read_secrets=false → 建议升 L3/high
2. **deep_search**：除声明域名外还命中 cn.bing.com / www.sogou.com / api.github.com
3. **hot_reload / auto_updater**：subprocess 沙盒验证/重启，process 未声明
4. **task_loop**：verify() 以 subprocess 跑 py_compile；**mcp_client**：stdio 按配置拉起子进程；**scheduler**：巡检直连 127.0.0.1:11434；**tts**：edge-tts 出网；**mcp_server**：127.0.0.1 起 HTTP 服务——运行时行为 vs 清单声明差异
5. **cache / calendar / error_lib / forgetting_curve / group_loop / learning_loop**：实际写 `data/*.json`，声明 filesystem.write=[]

> 说明：manifest 内部自洽（tier/risk 由声明 capabilities 推导，0 mismatch）；上述差异属标准第 12 节已知差距的同类收敛项，不阻塞发布。

## 五、门禁与发布终态（2026-10-21 实测）

| 门禁 | 结果 |
|---|---|
| check_plugin_quality.py | ✅ error=0（warn 125，与标准记录一致） |
| check_plugin_api.py | ✅ failed=[] |
| check_plugin_tier.py | ✅ 42/42 分级与风险推导一致 |
| check_plugin_deps.py --ast | ✅ error 0，无循环依赖 |
| check_plugin_security.py | ✅ error 0 / warn 0 |
| check_plugin_repo.py | ✅ 42 个已签名文件核验通过 |
| verify_signature.py --all | ✅ 42/42 RSA 2048 签名与 sha256 有效 |
| pytest（standard 17 + v21 19 + contract 29） | ✅ 65 passed |

**发布管线**（按标准第十节）：
- `rebuild_modules_repo.py --apply`：42 个模块入库，manifest 重建（version 三段式、capabilities 标准生成、tier/risk 自动推导）
- `sign_modules.py`：42/42 签名写回
- `sync_plugin_repo.py --apply`：42 个已签名文件发布至下载源 `E:\xiaoliu\plugin_repo`，`--check` 与仓库门禁通过
- `sync_package.py`：打包源 `E:\xiao6-package` 同步 30 个更新文件、0 删除，同步后校验「已完全一致 + 安全检查通过」，含 modules/、modules_repo/、插件标准.txt 等随包文件（4579 个文件，202.4 MB）
- 一致性终检：modules_repo / plugin_repo / xiao6-package 三处 manifest.json 字节一致；修复模块已落位打包目录；42 条全部三段式版本且 sha256+签名齐全

## 六、详细记录

- 批次 1（agent_analyst ~ learning_loop，21 个）：本文末尾「附录：插件审计 v2.1（第一批）」
- 批次 2（mcp_client ~ weather，21 个）：本文末尾「附录：插件审计 v2.1（第二批）」

## 七、遗留事项

1. memory_cards / personality 数据布局迁移（需联动 core/gui，等待用户决策）
2. 能力声明滞后项（见第四节，建议随下次 manifest 推导统一收敛）
3. git 提交/推送未执行：下载源本地镜像已同步，但发布到 GitHub 公共下载源需 git commit + push，按约定待用户确认后执行


---

## 审计后续（2026-10-22）

审计发现的差距中，本轮已补:

| 项 | 状态 |
|---|---|
| 分级与风险自动推导 | ✅ `core/plugin_tier.py` |
| 结构化错误码 | ✅ `core/plugin_errors.py` |
| 生命周期幂等 | ✅ `core/module_lifecycle.py` |
| 工具 contract 校验 | ✅ `core/tool_contract.py` |
| 审计日志格式 | ✅ `core/plugin_audit.py` |
| 熔断与资源上限 | ✅ `core/plugin_limits.py` |

仍待补（与 `插件标准.txt` 第十五节一致）：

```text
P0  LICENSE / 插件级 README / requires 字段
P1  配置优先级 / manifest 驱动卸载 / 插件 CHANGELOG
P2  遥测出口 / 插件目录化 / 工具 contract 全覆盖
```

---

## 附录：插件审计 v2.1（第一批）

> 原文件 `docs/plugin_audit_v21_batch1.md`，2026-10-30 合并入本文。

# 插件标准 v2.1 合规审计报告 — 批次 1

- **审计日期**：2026-10-21
- **权威标准**：`E:\xiaoliu\插件标准.txt`（v2.1，14 节，含 S-* / capabilities / contract / 错误码 / 生命周期 / 门禁清单）
- **清单事实源**：`E:\xiaoliu\modules_repo\manifest.json`（42 条，本批次抽取 21 条）
- **审计对象**：`E:\xiaoliu\modules\installed\<名>.py`，共 **21 个**
  agent_analyst, agent_coder, agent_planner, anomaly_detector, auto_updater, browser,
  cache, calendar, code_runner, computer_controller, deep_search, error_lib, file_upload,
  forgetting_curve, group_chat, group_loop, group_parallel, hot_reload, image_ocr,
  knowledge_qa, learning_loop
- **判定口径**：仅以 8 项 MUST 为准；第 12 节 P0/P1/P2 与第 14 节待补齐项（插件级 README/API/AGENTS、LICENSE、requires 字段、单测、CHANGELOG、配置优先级、manifest 驱动卸载、密钥吊销、遥测出口、目录化、工具 contract 全覆盖）**不判不合格**；warn 级问题（未声明 stop()、未声明不负责事项、工具未声明 contract、旧式 `{"错误":...}` 返回等）**不改**。
- **修改边界**：仅可改本批次 21 个 `.py`；未动 core/、gui/、templates/、docs/、tests/、tools/、manifest.json、plugin_repo/、其他批次模块、`__init__.py`；未运行 rebuild/sign/sync/pytest 等集中脚本；未做 git 操作；未删除任何文件。
- **基线**：质量门禁 error=0、warn=125（warn 不阻塞）。

---

## 一、汇总

| 状态 | 数量 | 模块 |
|---|---|---|
| ✅ 符合（无需修改） | 20 | 除 deep_search 外的全部 |
| 🔧 已修复 | 1 | deep_search |
| ❌ 不符合未修 | 0 | — |

**修复明细**：仅 `deep_search.py` 一处——`_read_page()` 的裸 `except:`（连带吞掉 `KeyboardInterrupt/SystemExit` 且无理由标注）收窄为 `except Exception:` 并补注释。已通过 `ast.parse` 语法自检。

> 说明：代码行为与 manifest 能力声明之间存在若干「声明滞后」观察项（见附录 A），其修复点在 manifest 重新推导（`rebuild_modules_repo`/`sign_modules`），属主流程统一执行范围，本次不改代码、不改 manifest，仅登记。

---

## 二、通用结论（适用于全部 21 个模块）

1. **manifest 必填字段**：21/21 均含 name/file/cls/version/api_version/license/author/min_host_version/plugin_tier/risk_level/capabilities/sha256/signature（另含 title/desc/group/first_party）。✅
2. **version 三段式语义化**：21/21 均为 `X.Y.Z`（1.0.0 / 5.0.0 / 5.1.0 / 7.0.0 / 7.1.0 / 10.0.0 / 11.0.0 / 16.0.0 等）。✅
3. **capabilities 五段齐全**：21/21 均含 network/filesystem/process/ui_control/config。
   - network.enabled=true 的仅 browser（localhost/127.0.0.1，GET/POST，无端口）与 deep_search（duckduckgo.com / html.duckduckgo.com / www.bing.com / api.search.brave.com，GET，非回环域名均无端口）——合法。✅
   - filesystem 声明读路径全部落在 `data/plugin_data/<名>/`，无绝对路径/`..`/盘符。✅
   - process.enabled=true 仅 code_runner，allow_argv=`[["python"],["py"]]`，固定 argv 数组，无 cmd/powershell/bash/wscript/cscript 包装器，无 `; & | < > \` $ % 换行。✅
   - config：read_secrets 全为 false；public_keys 全为空，无 key/token/secret/password/credential/private。✅
4. **tier/risk 推导一致**：用 `core/plugin_tier.check_manifest` 程序化核对，21/21 声明值与推导值一致，0 mismatch。
   - L3/high：code_runner（process）、computer_controller（ui_control）。
   - L2/medium：browser、deep_search（network）。
   - L1/low：其余 17 个。✅
5. **依赖边界**：21/21 的 import 全部为标准库 / `modules.base` / 白名单 core（core.safe、core.diagnostics、core.path_safety、core.agent_generic、core.net_guard、core.screen_geometry、core.error_text、core.sandbox、core.document_parser、core.retrieval、core.fts_index）/ 首方集成层（core.auto_update_*、core.computer_*）；grep 复核无 `core.trunk`/`core.secret_store`/`core.data_schema`/`core.pipeline` 等禁止前缀。✅
6. **硬编码密钥**：grep 复核 `api_key/token/secret/password="..."`、`sk-...`、`BEGIN PRIVATE KEY` 三类模式 0 命中。✅
7. **裸 except: pass**：仅两处裸 `except:`——computer_controller:108 为 `except: pass  # 静默是故意的…`（已标注理由，门禁豁免，合规）；deep_search:102 为 `except: return ""`（已就地收窄为 `except Exception:`，见下）。其余吞异常均为 `_x6_swallowed(__name__, e[, reason])` 约定式带因豁免。✅
8. **入口 run()**：21/21 均有 `run()`（agent_analyst/coder/planner 经 `AgentGeneric.run` 继承，已确认基类存在 run/reply）。✅
9. **contract 字段**：本批次 TOOLS 均未写 `contract` 子字段（写了才强校验，未写记 warn），无非法 contract。✅
10. **生命周期**：21/21 均继承 `modules.base.BaseModule`（其经 `LifecycleMixin` 提供 start/run/stop/close/shutdown/health/describe，stop 幂等）；browser 自实现 `shutdown()` 并做 hasattr 判空 + 置空引用，幂等。✅
11. **结构化错误**：旧式 `return {"错误": ...}` 多处存在，按基线口径属 warn，不改；无「明显破坏 JSON 可序列化契约」的返回。✅

---

## 三、逐模块审计结论

### 1. agent_analyst.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：继承 `core.agent_generic.AgentGeneric`（白名单），经基类获得 `run()/reply()`；无 secret、无裸 except；manifest L1/low 与推导一致。

### 2. agent_coder.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：同上（`core.agent_generic` 白名单）；入口继承自基类；L1/low 一致。

### 3. agent_planner.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：同上；L1/low 一致。

### 4. anomaly_detector.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.safe`（白名单）+ `modules.base`；自实现 `run()`；无 secret、无未标注 except；声明读路径在 `data/plugin_data/anomaly_detector/`；L1/low 一致。（代码内 `VERSION="1.0"` 为模块属性，对外以 manifest `7.0.0` 三段式为准，不判。）

### 5. auto_updater.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.auto_update_*` 属首方集成层（`_FIRST_PARTY_INTEGRATION`），非禁止前缀；`core.diagnostics` 白名单；自实现 `run()`；无硬编码密钥、无未标注 except。（其编排行为涉及 subprocess/文件替换，能力声明见附录 A 观察项，本次不改。）

### 6. browser.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.safe`/`core.diagnostics` 白名单；`run()` 齐备；自实现 `shutdown()` 幂等（hasattr 判空 + 引用置空 + atexit 注册）；吞异常均带因 `_x6_swallowed`；network 声明仅回环 localhost/127.0.0.1（GET/POST，无端口）合法；L2/medium 与推导一致。

### 7. cache.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.safe`/`core.diagnostics` 白名单；`run()` 齐备；吞异常走 `_x6_swallowed`（带因豁免）；L1/low 一致。（实际持久化路径 `data/cache.json` 为既有实现，能力声明读路径在插件目录内，见附录 A。）

### 8. calendar.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.safe`/`core.diagnostics` 白名单；`run()` 齐备；TOOLS 无非法 contract；L1/low 一致。

### 9. code_runner.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.safe`/`core.sandbox`（均白名单）；`run()` 齐备；process.enabled=true、allow_argv=`[["python"],["py"]]` 固定 argv、无 shell 包装器/元字符；L3/high 与推导一致。（`{"错误":...}` 旧式返回属 warn，不改。）

### 10. computer_controller.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.computer_*` 首方集成层 + `core.path_safety`/`core.error_text`/`core.screen_geometry`/`core.diagnostics` 白名单；`run()` 齐备；ui_control.enabled=true → L3/high 与推导一致；文件操作走 `is_within` 白名单。108 行 `except: pass  # 静默是故意的…` 已标注理由、门禁豁免，不属未标注裸吞。

### 11. deep_search.py
- 状态：✅ 符合（已加固一处）
- 修改：已修改——`_read_page()` 第 102 行裸 `except:` 收窄为 `except Exception:`，并补「best-effort 单页抓取失败当无摘要」注释。原因：裸 `except:` 会连 `KeyboardInterrupt/SystemExit` 一并吞掉，违反标准 6.5「不吞异常」；收窄后对普通异常行为不变。
- 其余检查项：`core.safe`/`core.diagnostics`/`core.net_guard`（均白名单）；网络走 `net_guard.check` 授权；声明域名 4 个均合法无端口；L2/medium 一致。（代码实际还会命中 cn.bing.com / www.sogou.com / api.github.com，超出声明域名，见附录 A。）

### 12. error_lib.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.safe`/`core.diagnostics` 白名单；`run()` 齐备；吞异常带因；无 secret；L1/low 一致。

### 13. file_upload.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.safe`/`core.path_safety`/`core.diagnostics` 白名单；文件名经 `safe_join`+`safe_name` 防穿越；`run()` 齐备；L1/low 一致。

### 14. forgetting_curve.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：白名单依赖；`run()` 齐备；吞异常带因；L1/low 一致。

### 15. group_chat.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：白名单依赖；`run()` 齐备；子角色编排走 `trunk.call`；吞异常均带因；L1/low 一致。

### 16. group_loop.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：白名单依赖；`run()` 齐备；状态键缺省补齐；TOOLS 无非法 contract；L1/low 一致。

### 17. group_parallel.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：白名单依赖；`run()` 齐备；TOOLS 无非法 contract；L1/low 一致。

### 18. hot_reload.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.diagnostics` 白名单 + 标准库；`run()` 齐备；临时文件清理 `except OSError: pass # 静默是故意的…` 已标注理由、豁免；L1/low 一致。（其 `subprocess` 沙盒验证/重启行为的 process 能力声明见附录 A。）

### 19. image_ocr.py
- 状态：✅ 符合（强制项口径）
- 修改：无需修改
- 检查项：`core.safe` 白名单；`run()` 齐备；无硬编码密钥（`cloud_api_key` 从 config 读取而非字面量）；TOOLS 无非法 contract；manifest L1/low 与「声明 capabilities」推导一致。
- 观察项（见附录 A）：代码 `requests.post` 直连 open.bigmodel.cn、并从 config 读 `cloud_api_key`，而 manifest 声明 network.enabled=false、config.read_secrets=false——声明滞后，需主流程 rebuild 重新推导（预计升 L3/high）。本次不改为代码（会整体移除 OCR 功能）。

### 20. knowledge_qa.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.safe`/`core.path_safety`/`core.document_parser`/`core.retrieval`/`core.fts_index`/`core.diagnostics` 白名单；`core.rag_pipeline`/`core.untrusted_content` 非禁止前缀（首方模块仅禁 FORBIDDEN 前缀）；`run()` 齐备；路径经 `safe_join`/`safe_name`；TOOLS 无非法 contract；L1/low 一致。

### 21. learning_loop.py
- 状态：✅ 符合
- 修改：无需修改
- 检查项：`core.diagnostics` 白名单 + 标准库；`run()` 齐备；联网经 `trunk.call("deep_search",…)` 委派而非直连；吞异常带因；TOOLS 无非法 contract；L1/low 一致。

---

## 附录 A：能力声明滞后观察项（移交主流程 rebuild/sign，本次不改代码、不改 manifest）

以下为「代码实际行为」与「manifest 声明 capabilities」之间的差距。修复点在 manifest 重新推导（`rebuild_modules_repo --apply` → `sign_modules`），属主流程统一执行；本次按修改边界不动 manifest，也不做会破坏功能的代码裁剪，仅登记备查：

| 模块 | 代码行为 | 当前声明 | 建议主流程重新推导 |
|---|---|---|---|
| image_ocr | `requests.post` 直连 `open.bigmodel.cn`；从 `trunk.config` 读 `cloud_api_key` | network.enabled=false；read_secrets=false | network.enabled=true + domains=[open.bigmodel.cn]；config.read_secrets=true + secret_names=["cloud_api_key"]；预计升 L3/high |
| deep_search | 除声明的 duckduckgo/bing/brave 外，还命中 cn.bing.com、www.sogou.com、api.github.com | network.domains 仅 4 个 | rebuild 时补登实际检索域名（或收敛代码） |
| hot_reload | `subprocess.run([sys.executable,…])` 沙盒验证、重启 GUI | process.enabled=false | 若 broker 对首方进程亦强制，则需声明固定 argv |
| auto_updater | 编排层经 mixin 下载/替换/沙盒（子进程） | process/network/write 均未声明 | 随 rebuild 一并重新推导 |
| cache / calendar / error_lib / forgetting_curve / group_loop / learning_loop | 实际写 `data/*.json`，声明 filesystem.write=[] | write=[]（故 L1） | rebuild 时按真实写路径补 write 声明（可能影响 L1/L2 推导） |

> 说明：这些不影响本次 8 项 MUST 的判定——manifest 内部自洽（tier/risk 由声明 capabilities 推导，0 mismatch），代码层无硬编码密钥、无禁止 import、无未标注裸吞、入口/生命周期齐备。

## 附录 B：自检
- 已修改文件：`deep_search.py`。
- 语法自检：`py -3 -c "import ast; ast.parse(open(r'...\deep_search.py', encoding='utf-8').read())"` → 通过。
- 未运行 rebuild_modules_repo / sign_modules / sync_plugin_repo / sync_package / pytest（按要求留待主流程）。

---

## 附录：插件审计 v2.1（第二批）

> 原文件 `docs/plugin_audit_v21_batch2.md`，2026-10-30 合并入本文。

# 插件标准 v2.1 合规审计报告 —— 批次 2（21 个模块）

- 审计日期：2026-10-21
- 权威标准：《小6插件标准 v2.1》（E:\xiaoliu\插件标准.txt，14 节）
- 清单事实源：E:\xiaoliu\modules_repo\manifest.json（42 条，RSA 签名）
- 批次范围（21 个，均在 E:\xiaoliu\modules\installed\）：
  mcp_client, mcp_server, memory_cards, memory_loop, multimodal, notes, personality,
  plugin_market, realtime_chat, scheduler, self_reflect, skill_capture, smart_router,
  task_loop, task_planner, todo, tool_caller, translate, tts, voice(manifest 条目名 stt), weather

## 汇总

- 符合：19（其中 13 个已就地修复、6 个无需修改）
- 已修复：13
- 不符合未修：2（memory_cards、personality —— 原因见各自小节，均因数据文件被 core/gui 共享，迁移超出本批次修改边界）
- 自检：13 个被修改模块均通过 `py -3 -c "import ast; ast.parse(...)"` 语法检查。
- 未触碰：core/、gui/、templates/、docs/（除本报告）、tests/、tools/、manifest.json、plugin_repo/、其他批次模块、__init__.py；未运行 rebuild/sign/sync/pytest 等集中脚本。

### 全局核对结论（21 个模块共用）

| 检查项 | 结论 |
|---|---|
| manifest 条目存在且必填字段齐全（name/file/cls/version/api_version/license/author/min_host_version/plugin_tier/risk_level/capabilities/sha256/signature） | 全部通过；voice 模块对应 manifest 条目 name=stt（file=voice.py, cls=Voice） |
| version 三段式语义化（13.7 N9.1） | 全部通过（1.0.0 / 7.0.0 / 7.1.0 / 10.0.0） |
| capabilities 5 段齐全 | 全部通过；network 仅 mcp_client（localhost/127.0.0.1 回环，POST）与 weather（wttr.in、api.open-meteo.com、geocoding-api.open-meteo.com，无端口，GET）声明启用，域名合法；config.public_keys 均为空，无 read_secrets |
| plugin_tier / risk_level 与 13.1 推导一致 | 全部通过：mcp_client、weather 因 network.enabled=true 为 L2/medium；其余 19 个 L1/low，与推导值一致 |
| 依赖边界（门禁[6]，仅 import 标准库 / modules.base / 公共 core 模块） | 全部通过；未发现 import core.trunk / core.secret_store 等内部实现模块（与质量门禁 error=0 基线一致） |
| 无硬编码密钥（门禁[7]） | 全部通过；mcp_server 鉴权 token 为运行时 secrets.token_urlsafe() 生成，不落盘 |
| 无未标注理由的 except pass（门禁[8]） | 全部通过；各模块的 except 均走 _x6_swallowed 记录或返回错误值，无裸 `except: pass` |
| 入口 run()（门禁[9]） | 全部通过 |
| contract 合法（门禁[10]） | 全部通过：声明 tools 未带 contract 字段属 warn 级收敛项，按基线不改 |
| 生命周期（第 7 节） | 全部继承 BaseModule；scheduler.stop() 置 running=False 幂等；mcp_client.stop() 重复调用安全；mcp_server.stop_http() 重复调用返回"未运行"幂等 |
| 结构化错误（第 6 节） | 旧式 `{"错误": ...}` 返回属 warn 级，按基线不改 |

### 观察项（不判不合格，留待主流程在 manifest 再生/签名时收敛）

- task_loop.verify() 实际以 subprocess 跑 `py_compile`；mcp_client stdio 传输会按用户配置拉起子进程；scheduler 巡检直连 `127.0.0.1:11434`（Ollama）；tts 经 edge-tts 出网；mcp_server 在 127.0.0.1 起 HTTP 服务。这些"运行时行为 vs 清单声明"的差异需在 manifest 重新生成时补 process/network 声明并重签名，本批次无权改 manifest、也不能重跑集中脚本，故仅记录。

---

## 1. mcp_client

- 状态：✅ 符合
- 修改：已修改
- 修改点：`_trust_path()` 由 `data/security/mcp_trust.json` 迁至 `data/plugin_data/mcp_client/mcp_trust.json`，含旧路径一次性迁移（os.replace，失败静默跳过）。
- 其他核对：manifest L2/medium 与 network.enabled（回环域名）推导一致；stop() 幂等（先置 _stopped 再收 stdio 子进程）；鉴权 token 同进程内存读取，不落盘。

## 2. mcp_server

- 状态：✅ 符合
- 修改：已修改
- 修改点：`self.path` 由 `data/mcp_tools.json` 迁至 `data/plugin_data/mcp_server/mcp_tools.json`（对应清单 filesystem.read 声明目录），含旧文件一次性迁移。
- 其他核对：HTTP 服务强制绑 127.0.0.1 + Host/Origin 校验 + Bearer 鉴权；危险工具默认禁用；stop_http() 幂等。

## 3. memory_cards

- 状态：❌ 不符合（违反条款：标准 4 节 filesystem 沙箱约束 / 门禁[对应 capabilities 段]）
- 修改：未修改（修改边界不允许）
- 原因：`CARDS_PATH = data/memory_cards.jsonl` 越出 `data/plugin_data/memory_cards/`。但该文件被 core/memory_organizer.py、gui/stats_dialog.py、gui/memory_view_dialog.py 按旧路径直接读取，且登记在 core/data_schema.py 并由 core/data_migrations.py 管理版本迁移。迁路径必须联动 core/gui/数据迁移体系，本批次只准改插件 .py，故标记为不符合未修，建议纳入主流程统一数据布局迁移。

## 4. memory_loop

- 状态：✅ 符合
- 修改：已修改
- 修改点：`memory_loop.json`、`episodic_memory.json` 由 `data/` 迁至 `data/plugin_data/memory_loop/`，两文件均含旧路径一次性迁移。
- 其他核对：自身无 network/process；经 trunk.call 编排 memory_cards/forgetting_curve/vector_store。

## 5. multimodal

- 状态：✅ 符合
- 修改：已修改
- 修改点：`temp_frame.jpg`（视频抽帧）与 `camera.jpg`（摄像头拍照默认落点）由 `data/` 迁至 `data/plugin_data/multimodal/`（__init__ 建 self.sandbox）。调用方显式传入的 save_path 属调用方责任，未改。
- 其他核对：whisper/cv2 为可选依赖，ImportError 时返回安装提示；旧式 `{"错误":...}` 为 warn 级不改。

## 6. notes

- 状态：✅ 符合
- 修改：已修改
- 修改点：`data/notes.json` → `data/plugin_data/notes/notes.json`，含旧文件一次性迁移；写入走 core.safe.atomic_write_json。

## 7. personality

- 状态：❌ 不符合（违反条款：标准 4 节 filesystem 沙箱约束）
- 修改：未修改（修改边界不允许）
- 原因：`self.path = data/personality.json` 越出沙箱。但该文件是 core 级共享资产：core/data_schema.py 登记其 schema、core/data_migrations.py 有 v0→v1→v2 迁移、core/growth_report.py 读取、core/personality_market.py 写入。迁移需联动 core，超出本批次边界，标记为不符合未修。

## 8. plugin_market

- 状态：✅ 符合
- 修改：无需修改
- 核对：模块职责即插件安装/卸载/验签/备份，对 modules/installed、modules_repo、data/plugin_backups 的读写是其固有功能；远程安装强制验签（RSA）+ sha256 + 主机白名单，符合 S-SIGN/S-TRUST。其"卸载改 core/lazy_config 源码"属标准 12 节 P1 已知差距（manifest 驱动卸载），允许不落地。清单 L1/low 自洽。

## 9. realtime_chat

- 状态：✅ 符合
- 修改：无需修改
- 核对：无自有文件持久化；start() 防重入、stop() 有未启动守卫；依赖 core.realtime 公共模块。

## 10. scheduler

- 状态：✅ 符合
- 修改：无需修改
- 核对：无自有文件持久化；start() 防重入、stop() 置 running=False 幂等；巡检项全部经模块调用与 net_guard 守卫（Ollama 巡检见观察项）。

## 11. self_reflect

- 状态：✅ 符合
- 修改：已修改
- 修改点：`data/reflect_history.json` → `data/plugin_data/self_reflect/reflect_history.json`，含旧文件一次性迁移。

## 12. skill_capture

- 状态：✅ 符合
- 修改：已修改
- 修改点：`data/skills/`、`data/skills_pending/` → `data/plugin_data/skill_capture/skills|skills_pending`，含旧目录一次性 os.rename 迁移（先建父目录）。core/trunk_background.py 仅调用 capture()，不直接读目录，迁移安全。

## 13. smart_router

- 状态：✅ 符合
- 修改：已修改
- 修改点：`data/router_cache.json` → `data/plugin_data/smart_router/router_cache.json`，含旧文件一次性迁移；写盘仍走 core.safe.atomic_write_json。

## 14. task_loop

- 状态：✅ 符合
- 修改：已修改
- 修改点：`data/task_loop.json` → `data/plugin_data/task_loop/task_loop.json`，含旧文件一次性迁移。
- 观察：verify() 的 subprocess py_compile 属运行时能力差异，见全局观察项。

## 15. task_planner

- 状态：✅ 符合
- 修改：已修改
- 修改点：`data/tasks/` → `data/plugin_data/task_planner/tasks`，含旧目录一次性 os.rename 迁移（先建父目录）。

## 16. todo

- 状态：✅ 符合
- 修改：已修改
- 修改点：`data/todo.json` → `data/plugin_data/todo/todo.json`，含旧文件一次性迁移；写入走 core.safe.atomic_write_json。

## 17. tool_caller

- 状态：✅ 符合
- 修改：无需修改
- 核对：无自有持久化文件；危险工具统一经 security_policy 分类 + permission_center 授权 + 用户确认；分发执行委托给目标模块。

## 18. translate

- 状态：✅ 符合
- 修改：无需修改
- 核对：纯内存历史，无文件读写、无网络；翻译走 llm 模块。

## 19. tts

- 状态：✅ 符合
- 修改：已修改
- 修改点：输出 mp3 由系统临时目录（tempfile.gettempdir()）迁至 `data/plugin_data/tts/xiao6_tts.mp3`（__init__ 建 sandbox 目录）。
- 观察：edge-tts 出网属运行时能力差异，见全局观察项。

## 20. voice（manifest 条目：stt）

- 状态：✅ 符合
- 修改：已修改
- 修改点：`data/_listen_tmp.wav` → `data/plugin_data/stt/_listen_tmp.wav`（与清单 filesystem.read 声明目录一致；临时文件用完即删逻辑保留）。
- 核对：裸 except（返回错误值而非 pass）不属门禁[8]；idle 卸载守护线程为模块内部资源管理。

## 21. weather

- 状态：✅ 符合
- 修改：无需修改
- 核对：network.domains=wttr.in/api.open-meteo.com/geocoding-api.open-meteo.com 合法无端口，methods=GET，与 L2/medium 推导一致；请求经 core.net_guard 策略检查 + core.safe_http；无文件持久化。

---

## 修改清单（13 个文件）

| 模块 | 改动 |
|---|---|
| notes.py | 数据文件迁入 data/plugin_data/notes/ |
| todo.py | 数据文件迁入 data/plugin_data/todo/ |
| memory_loop.py | 两个 json 迁入 data/plugin_data/memory_loop/ |
| multimodal.py | 临时产物迁入 data/plugin_data/multimodal/ |
| self_reflect.py | 历史 json 迁入 data/plugin_data/self_reflect/ |
| skill_capture.py | skills/skills_pending 目录迁入 data/plugin_data/skill_capture/ |
| smart_router.py | 路由缓存 json 迁入 data/plugin_data/smart_router/ |
| task_loop.py | 状态 json 迁入 data/plugin_data/task_loop/ |
| task_planner.py | tasks/ 目录迁入 data/plugin_data/task_planner/ |
| mcp_server.py | mcp_tools.json 迁入 data/plugin_data/mcp_server/ |
| mcp_client.py | mcp_trust.json 迁入 data/plugin_data/mcp_client/ |
| tts.py | 输出 mp3 迁入 data/plugin_data/tts/ |
| voice.py | 临时 wav 迁入 data/plugin_data/stt/ |

注：13 个文件被改后，manifest 中的 size/sha256/signature 将失效，需由主流程统一执行 rebuild_modules_repo + sign_modules + sync 后重新过门禁（error=0 基线）。

---

## 附录：插件质量门禁修复记录（2026-10-22）

> 原文件 `docs/91_插件质量门禁修复记录_2026-10-22.md`，2026-10-30 合并入本文。

# 插件质量门禁修复记录（2026-10-22）

## 背景
check_plugin_quality.py 初始报 142 条 warn、8 条 error。
用户给出三步方案：修新模块 → 改写检查器规则 → 修高价值存量。

## 修复成果

| 阶段 | error | warn | 说明 |
|---|---|---|---|
| 初始 | 8 | 142 | 刚跑出来的结果 |
| 第一步：修 6 个新模块 | 0 | 134 | 加 docstring + contract |
| 第二步：资源识别（stop()） | 0 | 102 | 只有持有资源的模块才要求 stop() |
| 第二步：模块级容器正则修正 | 0 | 82 | 只匹配模块级变量，不匹配类属性 |
| 第三步：修新模块剩余警告 | 0 | 81 | _PROVIDERS 移类里 + workflow_runner docstring |
| **最终** | **0** | **81** | **减了 61 条假警告** |

## 做了什么

### 第一步：修 6 个新模块
- 给 deep_research / coder_pro / graph_rag / workflow_runner / web_agent / api_server 加了 docstring "不负责的事项"
- 给 3 个有 TOOLS 的模块加了 contract（正确的 error code + side_effect kind）
- contract 合法 error code：PLUGIN_TIMEOUT / PLUGIN_UPSTREAM_ERROR / PLUGIN_INTERNAL_ERROR / PLUGIN_NEEDS_CONFIRM / PLUGIN_NOT_AVAILABLE
- contract 合法 side_effect：network / filesystem_read / filesystem_write / process / ui_control / config_write

### 第二步：改写检查器规则
1. **资源识别（标准 4.2）**
   - 之前：所有模块都要求 stop()/close() → 40 条假警告
   - 现在：只有持有 threading.Thread / socket / subprocess / sqlite3 / HTTPServer / webdriver 等资源的模块才要求 stop()
   - 结果：stop() 警告从 40 → 8

2. **模块级容器正则修正（标准 3.4）**
   - 之前：`^\s*[A-Z_]+\s*=\s*(\{|\[)` 匹配到类属性 TOOLS = [
   - 现在：`^[A-Z_]+\s*=\s*(\{|\[)` 只匹配真正的模块级变量（不缩进）
   - 结果：减了 20 条假警告

3. **警告基线棘轮**
   - 新增 tools/plugin_quality_baseline.json
   - 老模块警告数只许降不许升
   - 新模块 strict 模式（后来调整为基线模式）

### 第三步：修新模块剩余警告
- workflow_runner：加了"不负责的事项" docstring
- deep_research：_PROVIDERS 从模块级移到类里（DeepResearch._PROVIDERS）
- web_agent / api_server / graph_rag：全部 0 警告

## 剩下的 81 条 warn（存量技术债）

| 类别 | 数量 | 说明 |
|---|---|---|
| 旧式错误返回 {'错误': ...} | ~70 | 建议改用 core.plugin_errors |
| 未声明"不负责的事项" | ~10 | 老模块 docstring 补边界 |
| 有资源但未声明 stop() | 8 | cache / hot_reload / stt / task_loop / tool_caller / mcp_server / learning_loop / coder_pro |
| 其他（环境变量 / cwd / 模块级容器） | ~3 | 合理设计选择 |

## 后续计划
- 逐步把旧式 {'错误': ...} 返回改成 core.plugin_errors 标准错误码
- 给 8 个有资源的模块加 stop() 方法
- 老模块 docstring 补"不负责的事项"

## 最终复核（2026-10-23）

- check_plugin_quality.py：模块 48，error=0，warn=81，低于基线 102
- 全量测试：136 个测试文件，1632 passed / 2 skipped / 0 failed
- 插件仓库：48/48 清单一致、48/48 验签通过
- 插件安全：error=0，warn=0

结论：门禁与全量回归均通过，可以提交 GitHub。
