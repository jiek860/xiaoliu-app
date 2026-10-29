# 版本变更记录

## v25.2.39 - 2026-10-29

**工作台自然语言命令层（批次 44）**
（`nl.intent_v2` 默认 shadow：命令中心行为与 v25.2.38 完全一致，只记影子日志）

**统一意图（44.1）**
- `core/nl/intent.py`：`intent / targets / scope / constraints / risk` 五字段
  schema；10 类工作台意图；斜杠命令 `/open /test /explain /fix /code
  /refactor /search /undo /plan /chat`。
- 三段式路由：规则档（斜杠/路径/符号/测试名，≥0.78 不调模型）→
  小模型档（注入 `model_call`，解析 JSON，坏输出回退）→ 追问档
  （低于阈值只问一个最关键的问题）。
- 撤销短语优先于「改」；`undo / refactor` 固定高风险，出现删除/格式化/
  全项目等字样升级为高风险；破坏性意图 `auto_execute` 恒为 False。
- `core/agent_router.route_goal(..., trunk=...)` 叠加 NL：`off` 完全走旧
  三词表，`shadow` 只记影子日志，`on` 仅在带明确文件/符号目标且置信度
  ≥0.8 时升级为 code，绝不抢占电脑域。

**实体解析（44.2）**
- `core/nl/entities.py`：文件（精确 > 路径后缀 > 同名 > 前缀 > 子串）、
  符号（复用 `workspace_index.find_symbols`）、测试名、本地分支
  （读 `.git/refs/heads` 与 `packed-refs`，不跑子进程）；解析不到给
  ≤5 个候选；无索引时文件退回磁盘遍历。

**澄清与计划卡（44.3）**
- `core/nl/clarify.py`：缺 target / test / query 时只问一句；当前文件、
  选区、最近报错可补槽位；候选不唯一时给出 ≤5 个选项；回答可直接并回
  意图（补文件/符号/测试/关键词/全部测试）。
- 计划卡复用 `core/code_plan`：步骤统一带 `done=False`、`index`，附
  风险/测试/回退提示，界面可直接渲染成可勾选清单。

**命令中心（44.4）**
- 新增 `gui/ide_command_center.py`，`gui/ide_sidebar.py` 从 591 行降到
  510 行并 re-export 旧入口；执行顺序仍为「精确命令 → 模糊命令 →
  NL 意图 → 按文件名打开」。
- `core/nl/command.py`：`@file` / `@symbol` 直引；动作仅 open /
  run_test / search / ai / undo；撤销读 `data/patch_backups` 最新清单并
  调 `patch_engine.rollback`，无清单明确提示。
- shadow 时 `_run_nl()` 只写 `nl_intent` 影子日志并回退旧逻辑；`off`
  不记录；`on` 才执行。未新增任何按钮（仍 60/60）。

**冻结期名额**
- 合并 rebase：core 219 → 222（entities/clarify/command）、gui 100 → 101
  （ide_command_center），同提交 `check_feature_freeze.py --rebase --force`；
  Feature / 按钮预算不变。

**测试**
- 新增 `test_nl_intent`（58）、`test_nl_entities`（15）、`test_nl_clarify`
  （14）、`test_command_center`（22）；GUI 回归 171 passed · 2 skipped。

## v25.2.38 - 2026-10-29

**记忆 v2 收尾：每周巩固任务 + 灰度对照报告（批次 43.5）**
（默认 shadow：不生成、不改写记忆内容，用户可见行为与 v25.2.37 一致）

**每周巩固（43.5）**
- `core/chat/memory_jobs.py`：`weekly_consolidate()` 只做减法 —— 删除已过期卡、
  同 id 只留最新一条、总量压到 800 条上限；旧卡没有 id 一律保留，
  不误删、不做摘要、不调模型。
- 有改动才留 `memory_cards.jsonl.bak` 并用 `.tmp + os.replace` 原子替换；
  无改动不碰文件；异常只记 `stats["error"]`，由 scheduler 记录并重试。
- `modules/installed/scheduler.py` 接入：`定时.记忆巩固间隔秒` 默认 7 天，
  启动 600 秒后首轮、聊天中让路；成功后日志输出「前→后（过期/重复/裁剪）」。

**灰度对照报告（43.5）**
- `tools/memory_report.py`：只读 `data/chat_shadow.jsonl`，统计 v2 注入字数
  与旧记忆段字数、用户说「还记得」时的预览命中率、影子期本应写入条数；
  支持 `--base / --json / --markdown`，可生成 `docs/105` 灰度报告。
- 影子行补充 `v2_chars / legacy_chars`，旧日志缺字段时回退 `preview` 长度。

**冻结期名额**
- 新增 `core/chat/memory_jobs.py`，core 模块 216 → 217：同提交执行
  `check_feature_freeze.py --rebase --force` 并记录理由（巩固逻辑需脱离
  Qt/Trunk 独立测试，且 `memory_v2.py` 已 576 行，继续内联会越过 600 行硬限）；
  Feature / gui / 按钮预算均未增加。

**测试**
- 新增 `tests/test_memory_jobs.py`（11）与 `tests/test_memory_report.py`（8），
  合计 19 passed。

## v25.2.37 - 2026-10-29

**聊天拟人 v1：状态层 + 规划器 + 校验器 + 分层人格卡 + few-shot 灰度（批次 42）**
（默认影子 / 灰度 0：用户可见行为与 v25.2.36 一致；冻结期不新增 Feature / 按钮）

**对话状态层（42.1，默认 shadow）**
- 新增 `core/chat/state.py`：逐轮记录意图、期望、长度偏好、情绪（EMA）、
  话题（双轮切换防抖）、关系、未回答数、承诺到期；
- 原子写 `data/chat_state.json`（`.tmp` + `os.replace`），损坏文件回默认，
  异常按 `diagnostics.swallowed` 静默，不影响回复；
- 开关「聊天.状态层」= `off | shadow | on`，默认 `shadow`。

**回应规划器（42.2，默认 shadow）**
- 新增 `core/chat/planner.py`：按状态与用户输入规划 8 种 act
  （ack/answer/answer_with_action/comfort/clarify/refuse/tease/remind），
  输出长度、语气、必须包含/避免内容、是否反问；
- 危险请求在入口直接规则拒绝，不交给模型规划；
- `rule/model` 生效时把「本轮回复要求」作为一条 system 消息插在最终用户消息前；
- 开关「聊天.规划器」= `off | shadow | rule | model`。

**生成后校验器（42.3，默认 shadow）**
- 新增 `core/chat/critic.py`：检查空回复/超长/复述用户话/重复句/禁语/列点/
  emoji 超预算/反问过多/疑似答非所问；
- 规则修复优先（截断、去复述、去重句、拆列点、减 emoji），
  「聊天.校验重写」打开时才允许一次模型重写，超长/空结果即拒绝；
- 开关「聊天.校验器」= `off | shadow | on`。

**分层人格卡（42.4，默认 shadow）**
- 新增 `core/chat/data/persona_tiers.json`（随包种子，用户可在
  `data/persona_tiers.json` 放同名文件覆盖）与 `core/chat/persona_card.py`：
  L1 核心 / L2 关系 / L3 情境 / L4 风格四层，总预算 520 字，按句读截断；
- 四种风格（松弛/毒舌/温和/专业）各自 emoji 预算；用户自定义 `ai_persona`
  仍最高优先级；
- 人格卡禁语表与校验器内置表合并，按词长降序替换；
- 开关「聊天.人格卡」= `off | shadow | on`，风格由「聊天.人格风格」覆盖。

**检索式 few-shot + 灰度（42.5）**
- 新增 `core/chat/data/chat_fewshot.json`（12 条随包种子，`data/` 可覆盖）
  与 `core/chat/fewshot.py`：
  按 act（权重 2）+ topic（权重 1）检索最多 2 条，冷启动回退内置样例；
- 「聊天.灰度比例」0–100，按会话 id 的 `zlib.crc32 % 100` 稳定分流；
  命中时规划器 `shadow→rule`、校验器/人格卡 `shadow→on`，并注入 few-shot；
  比例归 0 即完全回旧版；
- 影子日志新增 `plan / critic / persona / gray` 字段，供评测对照。

**真实聊天评测**
- `tools/run_eval.py --with-model --chat-limit N` 走完整回复链路生成聊天样例，
  输出平均字数与 8-gram 重复率（`chat_summary`），Markdown 报告同步展示；
- 评测时关闭联网与工具调用，结果可复现。

**内部**
- 冻结名额按 41.0 方案 A 同提交 rebase：`core 210 → 215`、
  测试 `174 → 179`（Feature 46 / gui 100 / 按钮 60 不变）；
- 批次 42 定向测试 **111 passed**；回复链路回归 **38 passed**；
  `run_eval --domain all --dry-run` **140 道通过**。

**验收**
- 默认全部影子 / 灰度 0：提示词与回复文本与 v25.2.36 一致；
- 全量测试 **2441 passed · 3 skipped**（289 秒）；
- `scripts\ci_local.py --quick` **13/13 通过 · 69.9 秒**；
- `check_version`、`check_file_sizes`、`check_silent`、`check_feature_freeze` 全绿。

## v25.2.36 - 2026-10-29

**评测底座 + 回归基线 + 聊天影子状态（批次 41；用户可见行为零变化）**
（冻结期不新增 Feature / 按钮：Feature 46、按钮 60 保持不变）

**评测底座**
- `tools/run_eval.py` 支持 `--domain safe|chat|nl|code|all`、`--dry-run`、
  `--strict`、`--report`：安全、聊天、自然语言路由、代码任务四类用例可独立跑，
  失败能定位到 case id；
- 新增 60 条聊天用例、40 条自然语言路由用例、20 条代码任务用例（原 20 条
  安全用例保留），共 **140 条**；`--with-model` 未开时聊天用例标记跳过；
- 新增 `tools/eval_metrics.py`：句数/字数/emoji/问号/禁语命中/8-gram 重复率/
  期望约束校验，纯函数、无网络；
- 新增 5 个代码修复 fixture（分数不增加、按钮不响应、空列表除零、循环导入、
  中文路径编码），评测时复制到临时目录，不污染本仓；
- 基线报告 `docs/104_评测基线_2026-10-29.md`：safe 20/20、nl 40/40
  （期望意图匹配 32/40=80%）、code 20/20（初始健康度），chat 待接模型。

**聊天影子状态（只记录，不参与回复）**
- 每轮对话追加一行 `data/chat_shadow.jsonl`：意图、话题、是否简单、
  上下文/生成/整轮耗时、回答长度、是否用户取消；超过 2MB 自动轮转为 `.1`；
- 开关「聊天.影子状态」默认开启；关闭后零行为差异，写入失败按
  `diagnostics.swallowed` 静默，绝不影响回复。

**内部**
- 41.0 治理决策：后续批次新增 `core/chat/*` 等模块时，在**同一 PR 内**
  执行 `check_feature_freeze.py --rebase --force` 并记录理由，不提前预留名额；
- 新增测试 `test_eval_metrics.py`、`test_eval_domains.py`、
  `test_shadow_state.py`，定向 21 passed。

**验收**
- `py -3 tools/run_eval.py --domain all` 出报告；`--dry-run` 结构校验通过；
- `scripts\ci_local.py --quick` **13/13 通过 · 71.1 秒**；
- `check_feature_freeze`（Feature 46 / core 210 / gui 100 / 按钮 60 / 测试 174）、
  `check_file_sizes`、`ruff` 全绿。

## v25.2.35 - 2026-10-29

**终端可选真 PTY（ConPTY）：装了 pywinpty 就有 Tab 补全 / 颜色 / 交互式程序**
（冻结期不新增 Feature / 按钮：Feature 46、按钮 60 保持不变）

**终端真 PTY（可选依赖）**
- 装了 `pywinpty`（`requirements-optional.txt`）时终端自动走 ConPTY：
  `python` REPL、`more`、`ping` 等交互式程序可用，Tab 补全和颜色生效，
  中文输入不再受 Windows OEM 代码页限制（英文系统 437 也能输入中文）；
- 没装则自动回退到批次 37 的「常驻 cmd.exe + 管道」实现，行为与之前一致；
- 两种后端对上层是同一套调用（`_shell_kind` 只用于区分回显策略）；
  关闭工作台仍会回收 shell / PTY，不留孤儿进程。

**终端呈现修正**
- ConPTY 输出是"屏幕画面"，含 CSI（光标/颜色）与 OSC（改窗口标题）序列，
  显示前统一清洗；控制台自己会回显输入，PTY 模式不再重复打印 `$ cmd`；
- 提示符用环境变量 `PROMPT=@x6@` 设置（省掉一次按键回显），首屏输出要等
  哨兵出现才开始显示；ConPTY 首屏比管道慢，兜底等待放宽到 3 秒。

**内部**
- 终端逻辑（ANSI 清洗 / 编码 / shell 生命周期 / PTY 适配）从
  `gui/ide_editor_shell.py` 拆到 `gui/ide_terminal.py`，`BottomPanel` 改为继承
  `TerminalMixin`：外层文件从 608 行回到 295 行（600 行硬上限），行为不变；
- `xiao6.spec` 在构建环境装了 `winpty` 时收集 `winpty.dll` / `conpty.dll` /
  `OpenConsole.exe`，没装则跳过且不报错；`tools/runtime_import_policy.json`
  把 `winpty` 登记为可选依赖；
- 管道输出兼容 `QByteArray` 等字节容器（直接 `str()` 会得到带引号的 repr，
  中文还会丢），shell 启动瞬间到达的输出不再被丢弃；
- 慢机器/首次冷启动用例的超时从 10 秒放宽到 20 秒（CI 实测 cmd.exe 首屏
  被 Defender 扫到 >10 秒），本机仍在 1 秒内返回。

**验收**
- `test_workbench.py` 98 passed（新增 PTY 假后端 5 条用例）；
- 定向回归 `test_workbench + test_gui_smoke + 守卫用例` 204 passed / 2 skipped；
- `check_buttons` 60/60、`check_file_sizes`、`check_feature_freeze`（gui 100，
  拆分文件已按冻结规则重锁）、`check_silent` 0、`check_threads`、
  `check_runtime_imports`、`ruff` 全绿。

## v25.2.34 - 2026-10-29

**工作台 IDE 化收尾：Git 暂存/提交、搜索替换、静态检查、补全、终端持久会话**
（冻结期不新增 Feature / 按钮：Feature 46、按钮 60 保持不变）

**源代码管理（SCM）**
- 侧栏新增提交框与「全部暂存 / 提交」链接、右键菜单（查看差异 / 暂存 /
  取消暂存 / 放弃改动…），改动按 `?? / M / A / D / MM` 着色；
- 底部新增「差异」页（第 4 页）：新增行绿、删除行红、`@@` 灰，文件名进页标题；
- 提交前两道闸（信息非空、暂存区非空），失败把 git 的 stderr 原样显示；
  提交成功在输出页记 `[git] <sha>`。所有 git 调用带 `-c core.quotePath=false`，
  文件参数一律 `-- <rel>`，中文路径不再出错。

**搜索增强**
- `Aa`（区分大小写）/ `.*`（正则）/ `替换` 三个开关，`rg` 与 `os.walk`
  兜底共用同一个匹配器；正则写错直接提示，不再当成"没有结果"；
- 「全部替换」先备份到 `data/.x6_replace_backup/<时间戳>/` 再原子写入，
  跳过 `.git`、二进制与 >1MB 文件，执行前二次确认。

**编辑器静态检查**
- 打开/保存时后台跑 `ruff check --output-format=json`，问题页显示
  「第 L 行:C  规则码  描述」，双击跳转；没装 ruff、超时或解析失败自动回退
  `ast.parse`，编辑过程仍只跑 ast（400ms 防抖），不卡输入。

**编辑器补全**
- 不再依赖 jedi：候选 = Python 关键字 + 内置名 + 本文件符号
  （JS/TS 用正则抽 `function/class/const/let/var`）；
- 键入 2 个字符后 300ms 弹出，`Ctrl+Space` 手动触发；注释/字符串内不弹，
  只对 `.py/.pyw/.js/.jsx/.ts/.tsx/.mjs/.cjs` 启用。

**终端持久会话**
- 不再每条命令新起 `cmd /c`：工作台保留一个常驻 shell，`cd / cls / pwd`
  仍本地处理并同步 shell 工作目录，`python` 等交互式程序能留在同一进程里；
- 输出流式追加、ANSI 转义清洗、只在贴底时跟随滚动；`exit`、空回车、
  进程被 kill 后自动重启；关闭工作台回收 shell，不留孤儿进程；
- 中文输入按 Windows OEM 代码页编码（中文系统 936），输出 UTF-8 优先、
  失败退 GBK/OEM，中文回显不再乱码；英文系统（OEM 437）暂不支持输入中文，
  留给可选的真 PTY 方案（批次 38）。

**插件市场**
- `hot_reload` 选类修复：跳过 `_` 开头的私有类并优先 `BaseModule` 子类
  （原实现取模块里第一个类，会把 Whisper 的 C 层后端当 trunk 加载并崩进程）；
  插件仓库与 `manifest.json` 已重新签名。

**验收**
- 全量 `pytest tests/` 2308 passed / 3 skipped；各批改动行覆盖率均 ≥70%
  （批次 37 实测 82.97%）；
- `check_buttons` 60/60、`check_file_sizes` / `check_shapes` / `check_feature_freeze` /
  `check_silent` / `check_threads` / `ruff` 全绿；
- `PyInstaller xiao6.spec` 打包产物实跑验证通过（详见 `docs/20` 批次 39）。

## v25.2.33 - 2026-10-26

**窗口单实例 + 退出清理 + 文档/教程同步**
（冻结期不新增功能；按钮预算保持 60 不变）

**所有按钮只开一个窗口**
- 新增 `_singleton_window`（非模态复用）与 `_run_modal_once`（模态重入守卫），
  主窗口所有 `*_dialog` / `open_*` 入口统一走这两条路；
- 任务中心改成单窗口：聊天卡片、活动中心、侧栏、命令面板再点「查看任务」
  都复用同一个窗口并切换到对应任务（`TaskCenterDialog.show_task`），
  不再连点叠出多个；活动中心、命令面板、意见反馈同样只保留一个；
- 系统检测、电脑控制从 `show()` 改成可复用窗口；保存的已关闭窗口会被清理，
  下次点击正常新建；
- 关闭主窗口时先关闭所有子窗口，让任务中心 / 活动中心注销运行时订阅并停掉
  定时器，修掉“后台线程往已释放窗口发信号”的退出崩溃风险。

**自检报告口径**
- 自检里的「⏱ 启动耗时: 2253.8秒（进程起到现在）」报的其实是**进程已运行时长**，
  用户会误以为启动一次要半个多小时；改名为「⏱ 已运行」；
- 真正的启动耗时改由 `core.startup.log_summary()` 启动完成时写入 `trunk._boot_ms`，
  自检新增「🚀 启动耗时」一行（原来读的 `trunk._boot_time` 根本不存在，从未打印过）。

**文档 / 教程**
- 程序内教程（`gui/tutorial_dialog.py`）新增「窗口只开一个」「次要动作是链接」
  说明，版本说明补到 v25.2.33；
- 根目录用户文档、`docs/00/10/20/README/92` 与打包源同步更新。

**验收**
- 全量 `pytest` 通过；新增/扩展的窗口单例测试覆盖高频入口连点、关闭后重开。

## v25.2.32 - 2026-10-26

**冻结版收尾：主链路补洞 + 按钮降到 60 + 公开评测装置**
（本版不新增功能，只修链路、砍按钮、补可复现评测）

**语音链路（修 4 个真问题）**
- `SpeechController.listen_once()` 统一返回 `{文字, 错误}`：插件返回的
  `text/error` 与调用方读的 `文字/错误` 键名不一致，识别成功也永远读空；
- `VoiceChatDialog` 之前调用不存在的 `voice_module.tts()`，异常被吞导致全程
  无声；改为 `_VoiceSynth(QThread)` + `core.realtime.tts.TTS` 生成音频，
  `QMediaPlayer` 播放，「打断」真的能停；
- `TTSWorker.done` 以前从不 emit，`SpeechController.play` 收不到路径；
- 录音没有上限、识别失败会无限静默空转；现在连续 3 次失败自动结束并提示原因，
  `pyaudio` 缺失给出可执行的安装提示。

**更新 / 回滚链路**
- 检查更新放到后台线程 `UpdateCheckThread`，不再卡界面；
- 历史记录写入 `files / verified / backup`，界面如实显示「可回滚 / 备份已清理 /
  无备份记录」；新增「回滚到选中记录之前」；
- `rollback()` 不再 `rmtree` 整个 `core/`、`modules/`（会抹掉更新后新装的插件），
  改为逐文件覆盖；备份目录不存在时返回 False，不再假装成功；
- 历史列表的导出 / 保存失败直接说明原因，不再只弹“完成”。

**权限安全链路**
- `lockdown` / `update_constraints` / `revoke` 落盘失败时返回 `ok=False`
  并说明「重启后会失效」，撤销失败会把内存恢复成磁盘状态（不会界面删了、
  重启又复活）；
- 安全中心保存后回读 `get_net_guard(trunk)._mode()` 验证真的生效。

**电脑控制 / 历史 / 团队 / 工具**
- `DepInstallDialog` 点「现在装」会 AttributeError（引用了不存在的 `btn_copy`），
  已改为 `lnk_copy`；
- 历史记录：读取失败不再静默返回空页，直接显示原因；正文 `html.escape`；
  「上一页」判断改为 `start > 0`；显示页码 x/y；
- 团队管理：导入非法 JSON、导出不可写都有明确提示，保存后同步 `group_chat.roles`；
- 电脑控制：整窗不再有常驻按钮，回车即启动应用。

**按钮预算 151 → 60（棘轮只降不升）**
- 9 个高频业务弹窗（电脑控制 / 系统 / 代码 Agent / 电脑 Agent / Agent 旅程 /
  安全中心 / 角色 / MCP / 历史）从 53 个创建点降到 11 个；
- 其余 20+ 个窗口的次要动作统一改成富文本链接（`make_action_links`），
  关闭统一写「Esc 关闭」；任务中心七个并排按钮改成动作链接；
  侧栏「任务中心 / 命令面板」与首屏引导卡也改成链接；
- 新增运行时密度测试：高频弹窗真建出来以后，按钮数超上限即失败
  （防止“循环里每行建一个按钮”这类回归）。

**SWE-bench Verified 评测装置（不发布分数）**
- 数据集落盘 `data/swebench/swebench_verified.jsonl`（500 题，走 hf-mirror +
  `HF_HUB_DISABLE_XET=1`）；
- 试跑 10 题清单修正为数据集中真实存在的 id，并加测试守住；
- `mirror_url()` + clone 直连失败自动重试 `ghfast.top`；
- 正式 50 题清单固定种子 `20261123`（`data/swebench_final_plan.json`）；
- 实跑 3 题（pytest / sympy / sphinx）均因本地 4B 模型产不出 patch 记为 error，
  合计 0 / 3；云端 Key 401、无 Docker、无 `swebench` 包三项阻塞如实写进
  `docs/94_SWE_bench_Verified_正式跑记录.md`，**不发布 resolve 率**。

**测试与守卫**
- 新增用例全部进既有测试文件（`test_voice_extra`、`test_agent_harness`、
  `test_auto_update`、`test_centers_extra`、`test_x6_code_cli`、`test_gui_smoke`）；
- 全量 `pytest tests/ -q` 通过；静默异常 0、线程守卫、文件长度、结构契约、
  版本号、插件仓库一致、静态检查（Ruff + Mypy）全通过；
- 按钮与冻结基线 rebase 到 60。

## v25.2.31 - 2026-10-25

**工程加固（覆盖率棘轮 / 拆分临界大文件 / 发布脚本 / 可观测基线）**
- 覆盖率门槛上调（只升不降）：全局 58→60、core 55→57、gui 38→40、
  modules/installed 45→47；新增 `core/code_agent.py`（65%）与
  `core/patch_engine.py`（80%）为 `critical_modules`；
  CI `coverage report --fail-under` 同步升到 60。
- 六个临界大文件拆到 ≤500 行（只搬代码、不改行为、旧导入路径保留）：
  `modules/installed/plugin_market.py` → `modules/support/plugin_market_online.py`；
  `gui/settings_dialog.py` → `settings_model_page.py`；
  `modules/installed/tool_caller.py` → `modules/support/tool_catalog.py`；
  `gui/mcp_dialog.py` → `mcp_catalog.py`；
  `gui/workbench_dialog.py` → `workbench_ai_dock.py`；
  `gui/mixins/dialog_mixin.py` → `background_tasks_mixin.py`。
  辅助实现放 `modules/support/`（不是可安装插件，不进插件清单），
  保证 `modules/installed/` 里仍然只有可发布模块。
- 新增 `tools/github_api_push.py`：`--branch/--message-file/--pr-title/
  --wait-ci/--merge/--dry-run`，只走 `api.github.com`，按原始行尾上传、
  内容未变复用 blob、支持删除文件；token 从环境变量或 Windows 凭据管理器
  读取，任何日志都不打印 token。
- 可观测性：`tools/perf_baseline.py` 新增冷启动与首 token（本机解析管线）
  采样；CI 以 10% 容忍度只报警不阻塞，并上传
  `data/perf_current.json`；`tools/run_eval.py` 固定 20 道本地样本，
  结果写入 `docs/92_Agent回归基线.md` 并在 CI 作为 Agent 回归门禁。
- 文档纠偏：`docs/50_产品体验与Agent能力提升方案.md` 的「尚未完成」清单
  按代码实况更新（自动测试、lint、失败回修、多文件 patch、diff 审批、
  回滚均已完成），避免后续重复立项。
- 新增测试：`tests/test_github_api_push.py`、`tests/test_module_split_exports.py`、
  `tests/test_background_tasks_mixin.py`（覆盖搬出的 7 个后台方法）；
  更新 `tests/test_download_verification.py` 与
  `tests/test_plugin_market_extra.py` 以匹配拆分后的模块位置。
- 插件仓库：重新签名并发布 `plugin_repo`（48 个模块），
  `check_repo_sync` 恢复全绿。

## v25.2.30 - 2026-10-25

**活动中心：后台作业统一进同一份注册表**
- `gui/workers.py`：`TaskWorker`、`LearnWorker`、`BgWorker`、`TTSWorker`
  与 `StreamWorker` 共用 `_reg_start/_reg_finish`，启动、完成、失败、取消
  都会登记；同一毫秒启动的同类 worker 用随机后缀区分，不再互相覆盖；
  `TTSWorker` 失败时记录异常原因，不再只标一个空失败；
  每项活动带上 `log_path` 元数据，供活动中心定位日志；
- `gui/update_dialog.py`：检查更新与下载安装也登记为活动
  （`update_check` / `update_install`），失败原因写进注册表；
- `gui/activity_center_dialog.py`：列表按「运行中 / 失败 / 最近完成」分组，
  失败行直接显示「失败原因」，详情页提供「查看日志」文档内链接，
  点击后在右侧查看日志尾部并可返回详情；日志视图每秒刷新时不会被拽回；
- 回收策略明确化：注册表只保留最近 200 条已结束活动（运行中永不淘汰），
  磁盘 `data/agent_runs` 由启动时的 `maybe_cleanup` 按 40 个目录 / 7 天、
  事件文件 5000 行回收，避免无限增长。

**顺带修复**
- `license_core._read_secret_file` 不再对 32 字节随机密钥整体 `strip()`：
  密钥首/尾字节若恰好是 0x0a / 0x20 等空白字节会被截断，
  重启后 HMAC 签名校验全部失效；现在只剥掉文本编辑器追加的 `\r\n`。

**测试**
- `tests/test_agent_harness.py` 新增 5 条：四类 worker 启动/完成均入注册表、
  四类 worker 失败均写入失败原因、保留策略只淘汰旧终态、活动中心分组
  与「查看日志」渲染、检查更新失败也登记活动；
- `tests/test_license_core.py` 新增密钥含空白字节的往返回归。

## v25.2.29 - 2026-10-25

**聊天：历史分页 + 会话草稿**
- `ChatStore` 新增 `load_page()`（`(ts, id)` 复合游标，按时间正序返回一页）；
  新增 `drafts` 表及 `set_draft/get_draft/clear_draft`，
  草稿随会话重命名/删除/清空级联处理；
- 聊天视图首屏只渲染最近 50 条，顶部提供「↑ 加载更早的消息」文档内链接，
  点击后按游标续取一页并插入顶部，滚动位置按内容高度差补偿，不会跳回底部；
- 历史消息显示原始时间戳，而不是加载时的当前时间；
- 新增 `_reload_chat_history()` 统一入口：启动、切换会话、编辑/重新生成、
  创建分支、登录切号全部走同一路径；
- 会话草稿按 `(用户名, 会话)` 保存未发送输入：输入变化 400ms 节流落盘，
  切换会话/新建会话/关窗时立即落盘，切回与重启后自动恢复；
  发送成功（普通聊天、任务模式、Agent 旅程接管）后清空草稿；
- 新增 `gui/mixins/history_draft_mixin.py` 承载分页与草稿逻辑，
  聊天混入保持轻量；分页入口是文档内链接，未新增 QPushButton（预算 184 不变）。

**测试**
- 新增 `tests/test_chat_paging_drafts.py` 12 条：分页游标边界与末页、
  会话隔离、草稿往返/隔离/重启恢复/随会话删除、ChatView 首屏与
  prepend 顺序及链接事件、混入分页与草稿切换流程；
- `tests/test_chat_mixin_extra.py` 新增发送成功后清空草稿的回归。

## v25.2.28 - 2026-10-25

**代码 Agent：复杂任务先出计划，确认后才动手**
- 新增 `core/code_plan.py`：复杂目标先生成结构化计划
  （目标摘要 / 分步操作 / 每步目的 / 涉及文件 / 风险等级 / 验证命令），
  用户在弹窗确认后才进入 patch 生成与审批；拒绝则零改动退出，
  返回 `rejected_plan=True`，不产生任何文件写入；
- 计划门控三重启发式：目标长度、复杂关键词（重构/实现/新增/迁移/架构/
  模块/测试/修复/优化/接口/并发等）、候选文件数，简单目标不打扰用户；
- 模型输出不可解析时降级为启发式计划，不阻断任务；
- 计划审批与 patch 审批分离（`plan_cb` / `approval_cb`），
  直接调用 `CodeAgent` 的旧代码行为不变；
- `AgentOrchestrator` 新增 `_approve_plan()`，审批类型 `plan` 全链路透传；
- 工作台与 Agent 旅程窗口支持计划展示与确认/拒绝弹窗，未新增按钮。

**代码 Agent：单次模型生成期间 Esc 立即生效**
- `CodeAgent` 内置 `CancelToken`，`cancel()` 同时置位事件、取消令牌并
  终止活动子进程；
- 新增 `_llm_chat()`：有 `stream_chat` 的模型走可取消流式链路，
  取消后立即关闭响应并抛出 `AgentCancelled`，不再等整轮返回；
- 单角色循环、探索 Agent、修改 Agent 全部改走 `_llm_chat()`；
  探索阶段原有失败降级保留，但用户取消不会被降级吞掉。

**测试**
- `tests/test_code_agent_loop.py` 新增 4 条：拒绝计划零落盘、
  确认计划后正常落盘、生成期间取消不进审批、简单目标跳过计划；
- 定向回归 65 passed；全量测试与结构守卫见发布记录。

## v25.2.27 - 2026-10-25

**聊天：云端真流式 + 本地首字超时**
- `LLMCloudMixin._try_cloud_stream(..., cancel_token=)` 不再在配置了
  `cloud_provider` 时退回非流式 `_try_cloud`：改为按 provider 发
  `stream=True` 请求，统一用 `parse_stream_chunk` 解析 SSE
  （openai / azure / anthropic / gemini），界面逐字刷新；
- Gemini 流式改走 `:streamGenerateContent?alt=sse`，不再一次性返回；
- 云端流式接入 `CancelToken`：Esc 时 `close()` 流响应，每块前检查取消，
  取消后返回已收到内容且不写错误提示；
- 本地流式读超时从固定 120 秒改为 `(5, 首字超时)`，默认 25 秒；
  首字迟迟不出时提示"本地首字超时，切云端"并直接切云端流式，
  不再让用户干等两分钟；可用 config.json 的 `本地首字超时` /
  `local_first_token_timeout` 调整（5~300 秒），`云端首字超时` /
  `cloud_first_token_timeout` 调整云端读超时（默认 60 秒）；
- 本地刚超时后不再走一次非流式本地重试（避免又白等一轮）。

**测试**
- 新增 `tests/test_chat_first_token_timeout.py` 13 条：首字超时切云端、
  cancel_token 透传、超时后不重试本地、云端模式优先真流式、
  流式不支持时回退一次性调用、配置读取与夹取；
- `tests/test_llm_cloud_provider.py` 扩到 9 条：provider 真流式 SSE 解析、
  取消保留半段并关闭响应、异常回退、Gemini 流式 URL。

## v25.2.26 - 2026-10-25

**聊天：Esc 真正停止后台生成**
- 新增 `core/cancel_token.py` 的 `CancelToken`：取消时既置位标志供流循环检查，
  也直接 `close()` 已登记的流响应，把阻塞在 `iter_lines()` 的读线程叫醒；
- `StreamWorker.stop()` 不再只把 `_is_stopped` 置 True（全项目无人读取的死标志），
  改为真正取消令牌；取消后不再向界面推 token、不再发 `done` 信号，
  活动中心把本轮记为 `cancelled`；
- `LLMClient.stream_chat(..., cancel_token=)`：每个分块前检查取消，取消后
  立即关闭响应并返回已收到内容，不再走云端兜底或非流式重试；
  本地流式因此会及时释放 Ollama 串行锁，下一条消息不用再排队；
- `trunk.reply()` / `ReplyPipeline.run()` / `legacy_reply.run()` / `LLMDispatcher.dispatch()`
  全链路透传 `cancel_token`；取消后跳过记忆写入、群聊合并、代码沙盒验证和
  后台闭环，不再"界面已停、后台还跑十几秒"；
- 取消引起的异常不会把 pipeline 判为故障（不进入冷却降级）。

**测试**
- 新增 `tests/test_chat_cancel.py` 8 条：令牌置位/资源关闭/晚绑定、
  StreamWorker 真正中断、流式取消只保留已收内容、取消后不重试非流式、
  取消前后完整读取对照。

## v25.2.25 - 2026-10-25

**编码 Agent 回修韧性**
- `CodeAgent.run()`：patch 生成/校验失败（JSON 不合法、`hunk.old` 匹配不到）
  不再让整个任务直接失败，而是记录错误后进入下一轮回修；连续两轮同一错误
  仍由 `no_progress` 正常终止；
- 回修提示注入上一轮已应用的 diff（`propose_patch(..., previous_diff=...)`），
  模型在原有改动上修，不再重复同一份补丁；
- 新增空 patch 保护：`new` 与 `old` 相同、实际未落盘任何改动时按“无进展”
  回修，不再出现“没改代码但测试通过即完成”；
- 失败反馈改为结构化摘要：先列失败用例名（`文件::用例:L行`），再附输出尾部，
  避免截断丢掉关键定位信息；
- 断点续跑状态新增 `last_diff`，恢复任务后仍能携带上一轮改动。

**聊天舒适度**
- 流式回复改为实时 Markdown 渲染：首帧立即显示，之后 0.12 秒节流重绘，
  结束时不再从纯文本突然跳成排版后的样子；
- `MarkdownRenderer` 自动补齐未闭合代码围栏，流式途中的半截代码块也能正常显示；
- Esc 停止后，已生成内容按 Markdown 渲染并写入会话历史，切换会话不再丢失；
- 停止提示改为「已停止生成（已保留当前内容）」。

**测试**
- 新增/更新 6 条单测：错误回修、空 patch、上一轮 diff 注入、流式节流、
  流式替换、未闭合围栏；
- 全量测试 1901 passed / 2 skipped，`lint_check.py` 全绿。

## v25.2.24 - 2026-10-25

**死代码清理（0 引用）**
- 删除 `core/computer_recorder.py`（与已注册的 `action_recorder` 重复）、
  `core/docker_sandbox.py`（未接线，进程级沙箱已够用）、
  `core/feature_flags.py`（无消费方）；
- 同步 docs/00、docs/10、docs/30、docs/50、docs/82、docs/92 与相关测试。

**合并降低认知成本**
- 授权 6 件套（core/file/keys/payload/codec/verify）→ `core/license_core.py`（561 行）；
- 自动更新 4 件套（download/patch/policy/problem）→ `core/auto_update.py`（537 行）；
  同步 `modules/installed/auto_updater.py`、`plugin_repo/auto_updater.py`、
  `core/plugin_api.py` 白名单与相关测试；对外导入路径各保留 1 个。

**测试补齐**
- 新增同名测试：`test_patch_engine`、`test_task_runtime`、`test_trunk_background`、
  `test_ollama_installer`、`test_personality_style_hints`，并新增
  `test_code_context`；全部离线、无网络依赖。
- 合并后的两个文件补同名测试：`test_license_core`（34 条，覆盖 HMAC/RSA 生成、
  编码、.lic 加解密、过期/机器/邮箱/版本锁定等分支）、`test_auto_update`
  （30 条，覆盖策略开关、问题收集、沙盒失败原因、部署回滚、更新包签名与
  sha256 校验、替换失败回滚）。两文件行覆盖率 93% / 94%，CI 改动行覆盖率
  由 59% 提升到 90% 以上。

**Bug 修复**
- `verify_license(today="2026-01-01")` 传字符串日期时 `date` 未导入，
  抛 `cannot access local variable 'date'`，被兜底成“激活码无法解析”；
  改为在到期分支内先导入 `date`。

**编码 Agent**
- `CodeContextMixin.repo_map()`：按目录列出 .py 文件的仓库地图，实例内缓存；
  关键词命中不足 6 个文件时自动注入上下文，目标含糊时不再盲猜路径。

**聊天舒适度**
- Esc 停止回复：保留已收到的部分内容，后台结果不再覆盖界面；
- 回复中禁止并发发送，避免两条回复交错写入；
- 流式输出仅在用户贴底时自动跟随，向上翻历史时不抢滚动条；
- 新增居中灰字系统提示（append_system）与纯文本中断气泡（append_plain）。

**文档口径**
- docs/82 完整度口径升级到 v2：新增“入口可达”“跨模块测试覆盖”，
  并单独标注薄适配层（panel_registry / safe_http / diagnostics 等）。

### 代码 Agent 能力补齐 + 工作台布局优化（2026-10-24）

**P0 轮次与终止条件**
- 新增 `core/code_agent_policy.py`：轮次上限默认 12（范围 1~15），优先级
  显式参数 > `X6_CODE_AGENT_MAX_ROUNDS` > `trunk.config` > 默认值；工作台新增
  "轮次上限"数字框，可随任务传入。
- 终止条件显式化：测试与 lint 全绿 / 连续两轮错误指纹相同（无新错误）/
  轮次用尽。返回 `stop_reason` 与 `rounds_used`，时间线直接展示原因。

**P0 真符号索引**
- 新增 `core/symbol_parser.py`：Python 用 AST（类/方法/嵌套函数/异步），
  JS/TS 优先 `tree_sitter_languages`，未安装时退回正则并标注
  `engine=regex, confidence=0.6`；
- `WorkspaceIndex.find_symbols` 改为"精确 > 限定名后缀 > 前缀 > 子串"排序，
  支持 `kind` / `file` 过滤；索引版本升到 2，`stats()` 暴露解析引擎分布。

**P1 多文件预演与回滚**
- `patch_engine.dry_run_patch` 在内存里按顺序模拟整批 patch（含 create 后
  update、rename），并做 Python AST / JSON 语法校验；
- `apply_patch` 默认先整体 dry-run，任何一处失败都不写盘；写盘后异常仍按
  backup manifest 整批回滚。

**P1 编辑器闭环**
- 新增 `gui/inline_diff.py`：编辑器内联 diff 预览，点击/双击行跳转到源文件，
  底部"应用/撤销"用 QLabel 链接实现（不新增 QPushButton，按钮预算保持 184）；
- Agent 落盘后自动刷新已打开 tab；撤销走 `AgentOrchestrator.rollback()`。

**P2 任务队列与断点续跑**
- 新增 `core/code_task_queue.py`：队列落盘 `data/code_jobs/queue.json`，
  状态机 `queued -> running -> completed|failed|paused|cancelled`；
  进程崩溃后 `running` 自动标为 `interrupted`；
- 工作台 AI 面板新增任务队列列表，双击未完成任务从记录的轮次/错误/指纹续跑。

**P2 PR 闭环**
- 新增 `core/github_pr.py`：只用 api.github.com（blob→tree→commit→ref→PR→
  check-runs→merge），Token 来自显式参数/GITHUB_TOKEN/git credential，
  不落日志；推送前统一过权限中心审计；
- 编辑器标签页右键菜单可"推送到 GitHub 并创建 PR"；`PRFlow.ci_feedback()`
  把 CI 状态整理成可回灌给 Agent 的 `previous_error`。

**P3 双角色 Agent**
- 新增 `core/code_roles.py`：探索 Agent（只读工具 + report）→ 修改 Agent
  （带 report 生成 patch）；默认开启，可用 `code_agent.two_role=false` 或
  `X6_CODE_AGENT_TWO_ROLE=0` 退回单角色。

**工作台布局**
- 编辑器工具条按"文件 / 运行 / AI / 关闭"分组（分隔符 + 右侧关闭），
  仍是单个 QPushButton 创建点；
- AI 面板按钮从竖排改为横排，顶部显示项目名与快捷键提示，新增轮次数字框
  和任务队列列表，时间线展示终止原因。

### UI 向 Trae 对齐：顶部标签页 / 状态栏 / 设置左分类（2026-10-23，活动栏已撤）

- 左侧 52px 图标轨道曾短暂加入，因与侧栏的「对话/任务/资料/设置」重复，已整栏移除；保留顶部标签页和状态栏元信息。
- 主区域改为顶部标签页：对话页常驻且不可关闭；MCP、技能改为标签页打开，同一 key 复用同一实例，关闭标签页后下次点击自动重建。
- 状态栏补充模型名与今日 token 用量：`UsageTracker.summary(days=1)`，30 秒护栏避免重复扫 `data/usage`，60 秒定时刷新。
- 设置窗口改为左侧分类列表 + 右侧内容：保留 `QTabWidget` 作页面容器并隐藏自带标签条，搜索跳转、`tabText`/`currentIndex` 等原有测试接口不变。
- 开发依赖 `requirements-dev.txt` 补 `pytest-qt` / `pytest-timeout`：干净环境只按 txt 装依赖时，GUI 测试会报 `fixture 'qapp' not found`，并在退出阶段触发 QApplication 拆除顺序导致的访问冲突（0xC0000005）。

### 第二阶段 v3.1 完成与修复（2026-10-23）

- 技能注入改为独立 system 消息，修复群聊 300 字截断导致用户原话丢失。
- Skills 对话框入口接通；按钮从 7 个精简为「导入/导出/更多操作/关闭」，确认、拒绝、删除、市场安装收进菜单。
- 新增 `core/skills_market.py`、`core/skills_catalog.json`、`skills_repo/*.x6skill`；下载包做 sha256 校验，解压做路径/数量/体积校验。
- Web 控制台修复 query token 404；`/v1/tasks` 接真实 TaskRuntime；补 `websockets` 依赖并修正新版本 asyncio 启动方式。
- MCP 目录刷新改回主线程 signal；目录项结构/命令前缀校验。
- web_agent 增加 DOM 可交互元素摘要，动作失败返回 `ok=False`；browser 补 `back()`。
- coder_pro 用户编辑后的计划会拼入 CodeAgent goal。
- 多模态请求格式覆盖 OpenAI / Anthropic / Gemini / Ollama。
- 侧栏高级快捷按钮精简：任务中心、命令面板保留，其余收进右上角「更多」。
- 设置窗口「系统」和「开发者」拆成独立页面，并去掉高级设置里「检查更新 / 命令面板 / 模块星图 / 日志」的跨页重复入口；设置窗口及 Web 控制台入口重复点击复用同一窗口，Web 控制台地址支持选中、复制和直接打开浏览器。
- 去掉「开始任务 / 定时任务 / 权限中心 / 电脑 Agent」等与现有页面重复的按钮入口；电脑 Agent 改为进入工作台 AI 面板，由 AgentOrchestrator 自动路由。
- 修复日志中的真实报警：旧版 forgetting.json（list 格式）迁移，避免 remember/due_review 崩溃；pywin32 缺失时 `_win()` 统一返回三元组，避免 list_windows 解包崩溃；向量库跳过坏维度时 data/emb_mat 保持对齐；DuckDuckGo 超时按网络降级处理，不再写 ERROR 日志。

### 修复：工作台按钮文字显示不全（2026-10-22）

**现象**：工作台工具条上的按钮只显示一条横线，看不到中文。

**根因**：`gui/style.py` 全局 `QPushButton` 的 `padding: 10px`
（上下各 10px），而工具条按钮 `setFixedHeight(24~27)`：

```text
24px - 20px(上下padding) - 2px(边框) = 2px 留给文字
```

13px 的中文只剩 2px，被裁成一条横线。

**修复**

| 位置 | 变更 |
|---|---|
| `gui/style.py` QPushButton | `padding: 10px` → `4px 12px`，新增 `min-height: 24px` |
| `gui/style.py` QCheckBox | 新增 `min-height: 22px` + `padding: 2px 4px` |
| `gui/workbench_dialog.py` | 固定高度 24→28、26→30（给不同 DPI 留余量） |

**新增回归测试**

```text
test_global_button_padding_leaves_room_for_text
test_workbench_buttons_have_enough_height
```

断言全局样式里不得再出现 `padding: 10px`，且按钮高度 >= 文字高度 + 8。

### 虚拟机连物理机大模型 + 局域网放行 + 向量库容错（2026-10-22）

**1. 虚拟机 / 物理机分离部署支持**

场景：程序装在虚拟机（192.168.10.128），Ollama 在物理机（192.168.1.2:11434）。

原来网络守卫只认回环地址（127.0.0.1 / localhost / ::1），
局域网私有地址一律拒绝，导致"本地模型永远连不上，一直切云端"。

新增两种放行方式：

| 配置 | 粒度 |
|---|---|
| `security.allow_lan_hosts` | 逐台主机，可带端口（精确） |
| `security.allow_lan_cidrs` | 整个网段（省事） |

两者取并集。本次已配置：

```json
"allow_lan_cidrs": ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"]
```

覆盖虚拟机网段（192.168.10.x）与物理机网段（192.168.1.x）。

**2. 修复 local_model purpose 误判**

`llm_cloud._post()` 原来用 `url.startswith(base_url)` 判断是否本地。
`127.0.0.1` 与 `localhost` 写法不一致时会把本地请求判成云端请求，
被网络守卫拒绝。新增 `local_model_purpose()`，按**主机名**匹配
配置里的 `ollama_url`。

**3. 设置页检测走网络守卫**

「检测本地模型」原来直接发请求、绕过策略，导致"检测显示未连接但聊天能用"。
现在统一走守卫，被拦截时提示原因。

**4. 新增 core/lan_trust.py**

```python
entry_of(url) / current_hosts() / trust_host() / revoke_host() / describe()
```

`trust_host()` 在写盘失败时返回 False（不假装成功）。
设置页「检测本地模型」右键可一键信任当前主机。

**5. 修复向量库加载崩溃**

`np.frombuffer` 只要求字节数是 4 的倍数，一条被截断的记录会得到短向量，
混入数组后 `np.array()` 报 `inhomogeneous shape`，整个库读不出来。

修复：加载时校验维度一致性，异常的记录**跳过而非崩溃**，并记日志。

**安全边界未放宽**

```text
公网 IP（8.8.8.8 / 1.1.1.1）        → 仍拒绝
purpose=network 的普通出站请求       → 仍按原策略
只有 local_model / local_mcp /
local_health 三种用途走局域网放行
```

**验证**：1561 passed / 2 skipped；物理机 Ollama 实测连通（4 个模型）。

### 巡检修复：界面与后台 5 个真实 BUG（2026-10-22）

对全部按钮、页面、后台线程做了系统巡检，发现并修复 5 个真实缺陷。

**1. 连点按钮会开出多个窗口（严重体验问题）**

`mcp_dialog()` / `bot_dialog()` / `plugin_dialog()` 等 30 个开窗方法
每次都 `new` 一个新窗口。实测连点 MCP 三次 → 开出 3 个窗口，要一个个关。

修复：新增 `_singleton_dialog()` / `_singleton_fn_dialog()`，
按 key 缓存窗口；关闭后自动重建。另外 `mcp_dialog()` 之前
**只 `.show()` 不 `return`**，调用方拿不到对象，也已修复。

**2. 本地模型请求被网络守卫误拒（功能失效）**

日志实证：

```text
[INFO] 本地模型失败，切云端: 私有/回环/保留地址
```

根因：`llm_cloud._post()` 用 `url.startswith(self.base_url)` 判断是否本地。
当 `base_url=127.0.0.1` 而请求发往 `localhost` 时对不上 →
被当成 `cloud_model` → 网络守卫拒绝回环地址 → **本地模型永远不可用**。

修复：新增 `_is_local_target()`，按**目标主机名**判断
（127.0.0.1 / localhost / ::1 视为同一台机器），与写法无关。

**3. 关闭窗口后进程退不干净**

`threading.Timer` 默认 `daemon=False`，`trunk_background` 的 LLM 预热
用了它 → 关闭窗口后线程数停在 7 不下降，进程无法退出。

修复：显式 `timer.daemon = True`。

**4. 主窗口没有 closeEvent**

3 个 QTimer（活动徽章 1s / 主动关怀 10min / 状态刷新 3min）
在窗口关闭后仍在跑。

修复：新增 `closeEvent`，停止全部定时器并调用 `trunk.shutdown()`。

**5. 沙盒验证字段契约不一致**（本轮之前已修，一并记录）

`code_runner` 成功时不返回 `成功` 字段，导致所有代码块都被判"运行失败"。

**新增测试**

```text
tests/test_dialog_singleton.py      5 项  窗口复用
tests/test_backend_lifecycle.py     5 项  定时器/线程收尾
tests/test_ui_and_backend_bugs.py   6 项  本次 5 个 bug 的回归
```

验证：**1546 passed / 2 skipped**。

### 工作台融合 + uv 支持 + 文档同步（2026-10-22）

**一、三窗口融合为 🧰 工作台**

原来 `代码编辑器` / `Agent 旅程` / `AI 代码 Agent` 是三个独立窗口
（216 + 370 + 361 = 947 行），各自实现线程、diff 审批、时间线；
用户改完 AI 生成的代码想手动调，必须关窗重开，文件上下文全丢。

新增 `gui/workbench_dialog.py`：

```text
+--------------+----------------------------------+
| 文件树        | 编辑器（多文件标签）               |
|              +----------------------------------+
|              | 🤖 AI 面板（AgentDock）           |
+--------------+----------------------------------+
| 运行输出                                          |
+--------------------------------------------------+
```

- **无功能页签**：不存在"编辑器页/旅程页/Agent页"的切换
- 编辑器标签只表示"多个文件"，与旧行为一致
- AI 面板与编辑器共享同一份"当前打开文件"上下文
- 旧入口全部保留并转发到 `open_workbench()`

**二、按钮精简（遵守按钮预算）**

| 删除 | 替代 |
|---|---|
| ⛶ 全屏 | F11 |
| ▼ 收起 AI | Ctrl+J / 拖动分隔条 |
| 刷新（信任页） | 打开自动刷新 + 操作后自动刷新 |

保留的按钮都是执行中必须即时点击的动作：开始 / 暂停 / 取消 / 弹出。

**三、MCP 依赖 uv**

三个 MCP 服务器（网页抓取 / Git / SQLite）依赖 `uvx`，此前未安装导致
"握手失败: 子进程未运行"。已用 pip 安装 uv 0.13.5 到 `.venv\Scripts`，
程序会自动把该目录加入 MCP 子进程 PATH。

实测连通：文件系统 14 / 网页抓取 1 / Git 12 / SQLite 6，共 **33 个工具**。

**四、文档同步**

根目录 9 份（使用说明 / FAQ / 检测手册 / 安装教程 / 模型教程 /
激活教程 / 部署步骤 / README / ARCHITECTURE）+ docs/ 5 份
（00 / 10 / 30 / 40 / 70 / README 索引）全部补充本次变更。

打包源 `E:\xiao6-package` 已同步（4585 文件 / 202.5 MB），
11 份用户文档逐字节校验一致；`小6小传.txt` 已补入打包清单。

验证：1530 passed / 2 skipped；按钮预算 168；结构/静默/行数全通过。

### 修复：启动弹窗改为"只确认一次"（2026-10-22）

**现象**：每次启动程序都要重新确认协议、重新登录、重新点 MCP 允许。

**根因**

1. `core/auth.py` 的 `current_user` **只存在内存里**，从不写盘 ——
   重启后 `whoami()` 返回"未登录"，必然弹登录框。
2. 协议同意状态写在 `data/agreement.json`，但启动链没有统一的
   "已确认就跳过"判断，两处各自为政。
3. MCP 信任按命令哈希逐个生效，没有"一次授权全部"的入口。

**修复**

- 新增 `core/startup_consent.py`：启动期确认的唯一记录
  （协议 / 引导 / MCP 信任 / 插件能力），原子写 + 明确错误返回。
- `core/auth.py` 新增 `remember_session()` / `restore_session()` /
  `last_user()`：登录成功后把**账号名**写入 `data/users/session.json`，
  下次启动自动恢复。
  ⚠️ 只存账号名，**不存密码/激活码**；恢复时必须重新走
  `login()` 的完整校验（激活状态、验签、过期、团队禁用），
  任何一步失败都回到未登录。
- `gui/account.py` 新增 `try_restore_login()`（修了把 tuple 当 dict 的 bug）。
- `gui/main_window.py` 启动链：协议已同意则跳过；登录前先尝试恢复；
  引导完成后记录。
- MCP 新增「🔐 信任管理」页，可一键全部信任（见上一条变更）。

**明确保留每次询问的操作**（写死在 `ALWAYS_ASK`，不允许被记住）：

```text
覆盖文件 / 删除文件 / 覆盖目标文件 / 关机 / 重启 /
执行命令 / 自动更新部署 / 按控件名点击
```

这些直接毁数据，必须每次确认。

**当前状态**：本机账号 `xiao6` 已记住登录，协议已标记同意，
4 个 MCP 服务器已全部信任 —— 下次启动不再弹这些框。

验证：1517 passed / 2 skipped。

### 修复：MCP 服务器启动反复弹窗（2026-10-22）

**现象**：每次启动程序都弹出"确认操作 · 启动 MCP 服务器"，即使点过「永久允许」。

**根因（三处叠加）**

1. 「永久允许」是**逐个命令**生效的（按命令哈希存储），
   而程序有 4 个 stdio 服务器 —— 授权一个不会顺带授权其他；
   用户只授权过 3 个，SQLite 那条每次都要重新问。
2. 没有"批量信任"入口，只能一个一个点。
3. `_confirm_startup()` 里 `except Exception: return False` 裸吞异常，
   即使信任写入失败也**静默失败**，用户以为授权了、下次照样弹窗。

**修复**

- 新增 `core/mcp_trust.py`：信任库的唯一实现
  （`command_hash` / `load_trusted` / `save_trusted` / `is_trusted`），
  原子写 + 明确错误返回。
- `mcp_client` 新增 `trust_report()` / `trust_all_servers()` /
  `revoke_trust()`；信任写入失败会写入 `conn_errors`，不再静默。
- 新增 `gui/mcp_trust_view.py`「🔐 信任管理」面板：
  列出每个服务器的命令、状态、哈希，支持
  **全部永久信任（不再弹窗）** 与撤销全部。
  该面板**不加载 mcp_client**，改为后台线程，避免卡死界面。
- 确认弹窗的「永久允许」按钮加了说明：命令改动会使哈希变化并重新询问
  （这是防止命令被替换的安全设计）。
- 为什么不能"只问一次就永远不再问"：哈希基于命令内容，
  命令被改动必须重新确认，否则恶意程序可以替换命令绕过审核。

**当前状态**：本机 4 个 MCP 服务器（文件系统 / 网页抓取 / Git / SQLite）
已全部写入信任列表，下次启动不再弹窗。

验证：1498 passed / 2 skipped。

### 修复：状态栏本地/云端指示灯（2026-10-22）

**问题 1：切到"本地"时云端灯也是绿的**

两处代码无条件把云端灯设成绿色：

| 位置 | 原代码 |
|---|---|
| gui/mixins/dialog_mixin.py `switch_model()` | 本地分支里 `_status_cloud` 也被设成 `#0f0` |
| gui/settings_dialog.py `_safe_set_model_ui()` | `cloud_light.setStyleSheet("color:#0f0;")` 无条件执行 |

**问题 2：重启后又变回默认，像"设置没保存"**

配置本身是正常保存的（`data/config.json` 里 `model_mode` 值正确），
但**启动时没有任何代码根据 `model_mode` 回填指示灯** ——
只有 `switch_model()` 内部会改颜色，所以重启后停在 `build_ui()` 的初始值。

**修复**

- 新增 `gui/status_lights.py` 作为指示灯唯一真理源：
  `paint()` 按模式刷新本地/云端灯 + 模型按钮 + 顶栏标签，
  保证**任何模式下最多只有一个绿灯**。
- `switch_model()` 与 `_safe_set_model_ui()` 统一改为调用它。
- `main_window._init_from_trunk()` 新增启动回填
  （`paint_from_config`），重启后按已保存的配置恢复指示状态。
- 新增 `tests/test_status_lights.py`（12 项，含"任意模式不得双绿"回归）。

验证：1483 passed / 2 skipped。

### 修复：代码"沙盒验证运行失败"误报（2026-10-21）

现象：AI 回复里带 python 代码块时，末尾总显示"（沙盒验证运行失败：）"，
即使代码完全正确（例如只定义 `def add(a, b): return a + b`）。

根因（**返回契约不一致**）：

| 位置 | 行为 |
|---|---|
| modules/installed/code_runner.py | 成功时只返回 stdout / stderr / returncode，**没有 "成功" 字段** |
| core/pipeline/post_processor.py | 用 `res.get("成功")` 判断 → 永远为 None → 判成失败 |

修复：

1. `code_runner.run_code()` 统一返回契约，成功与失败两条路径都带
   `成功`(bool) / `输出` / `错误` / `stdout` / `stderr` / `returncode`。
2. `post_processor.verify_code()` 增加兼容：没有 `成功` 字段时回退看
   `returncode == 0`。
3. 区分"仅定义未调用"与"运行失败"：无输出时显示
   `沙盒验证通过（仅定义未调用，未产生输出）`，不再误报失败。
4. 新增 `tests/test_code_sandbox_contract.py`（11 项回归测试）。

验证：1471 passed / 2 skipped；42 个插件重新签名，仓库校验通过。

### 插件标准 v2.1：分级、审计、熔断、密钥校验（2026-10-21）

对齐外部《模块级程序标准 v1.0》并落实评审 P0/P1/P2：

新增模块：

- core/plugin_tier.py：L1/L2/L3 分级与 risk_level 自动推导
- core/plugin_audit.py：N15 审计日志（8 字段 + 脱敏 + 90 天保留期）
- core/plugin_limits.py：N13 熔断（5 次/60s）+ 资源上限 + 网络限流

新增工具：

- tools/check_plugin_tier.py    分级一致性
- tools/check_plugin_deps.py    依赖语法 + 环检测 + AST 边界
- tools/check_plugin_security.py 配置/路径/密钥/审计/L3 专项
- tools/verify_signature.py     RSA 签名 + 公钥位数 + 吊销列表

broker 增强：

- 熔断前置检查、调用成功/失败计数、写入配额、网络限流
- ctx.config.get_secret() 凭据代理（需 read_secrets + secret_names 声明）
- 每次能力调用写结构化审计

manifest v2.1：

- 新增必填 license / author / min_host_version / plugin_tier / risk_level
- version 统一为三段式语义化（1.0 -> 1.0.0 等）
- 回环地址允许显式端口（127.0.0.1:5000）

契约测试：

- tests/test_plugin_contract.py：42 模块批量契约（29 项）
- tests/test_plugin_standard_v21.py：v2.1 组件单测（19 项）
- templates/plugin_contract_test.py：单插件模板

CI 新增 5 项门禁。当前实测：1443 passed / 2 skipped；覆盖率 61.17%；
质量门禁 error 0；分级 L1=36 L2=4 L3=2；签名 42/42（RSA 2048）。

### 插件标准 v1.1：对齐模块级程序标准（2026-10-21）

新增可执行组件：

- core/plugin_errors.py：18 个结构化错误码 + retryable + context，附 normalize_error 渐进迁移
- core/module_lifecycle.py：new -> started -> stopped 状态机，start/stop/close/shutdown/health 幂等
- core/tool_contract.py：工具 contract 字段校验
- tools/check_plugin_quality.py：42 模块质量门禁，error 必须为 0

基类升级：

- modules/base.py：BaseModule 继承 LifecycleMixin，新增 NOT_RESPONSIBLE 与 describe()
- core/agent_generic.py：改为继承 BaseModule，使 3 个 agent 模块合规

门禁首跑修复：3 个 agent 缺 run；3 处 except pass 无理由；localhost 白名单；生成能力漏 filesystem 段。

文档：新增根目录 插件标准.txt、docs/MODULE_STANDARD.md；PLUGIN_STANDARD.md 补 v1.1。

验证：1395 passed / 2 skipped；覆盖率 60.99%；质量门禁 error=0。

### 插件标准 v1.0 落地（2026-10-21）

**问题**：标准其实早就存在（`core/plugin_api.py` + `core/plugin_capabilities.py`），
但 42 个官方模块**全部没有声明 capabilities**，每个都落进 legacy/默认拒绝，
清单里的能力声明形同虚设。

**修复**：

- `tools/rebuild_modules_repo.py` 新增 `capabilities_of()`：按模块真实依赖生成
  标准能力声明（最小权限 + 高风险显式化）。
- 生成结果**5 段齐全**（network / filesystem / process / ui_control / config）；
  修复了此前合并时漏 `filesystem` 段的问题。
- 改为**以生成结果为准**，不再沿用旧清单里不完整的声明。
- `core/plugin_capabilities.py`：域名白名单显式允许回环地址
  `localhost` / `127.0.0.1` / `::1`（连本地模型/MCP/浏览器调试端口必需），
  带端口的任意主机仍然拒绝。
- 42 个模块重新签名并发布到 `plugin_repo/`。

**合规结果**：

```text
模块总数 42 / 声明 capabilities 42 / 5 段齐全 42
已签名 42 / api_version 1.0 42 / 清单+源码校验通过 42 / legacy 0
```

**新增文档与契约测试**：

- `docs/PLUGIN_STANDARD.md`：插件标准 v1.0 全文（S1~S8）
- `tests/test_plugin_standard.py`：17 条契约测试（必填字段、能力完整性、
  签名、依赖边界、回环地址、高风险显式声明）

### 修复：启动完成后主界面被清空（真正的白屏原因，2026-10-21）

上一轮修字体是必要的，但**不是这次白屏的原因**。日志里
`字体就绪(151)` 说明字体早已正常，问题出在启动收尾：

```python
# gui/app_pyqt.py::_make_boot_callbacks.on_finished（旧代码）
ph.deleteLater()
window.setCentralWidget(None)      # ← 把 build_ui() 刚装好的整张界面拆掉
```

`build_ui()` 已通过 `setCentralWidget(central)` 装好主界面，
`on_finished` 紧接着又清空它，于是窗口只剩标题栏和状态栏 ——
与"底部文字正常、中间全白"的截图完全一致。

修复：占位页只从父级摘下（`setParent(None)` + `deleteLater()`），
**不再动 centralWidget**。

回归测试（防回弹）：
- `test_boot_finished_never_clears_central_widget`：AST 检查 `on_finished`
  内不得出现 `setCentralWidget`。
- `test_boot_finished_keeps_central_widget`：跑完回调后 `centralWidget()` 仍存在。
- 修正旧测试 `assert w.cleared is True` 为 `is False` ——
  那条断言当初把 bug 当成了正确行为。

验证：1355 passed / 2 skipped；截图确认侧栏、聊天区、输入框、按钮全部渲染。

### 第二阶段产品能力 + 文档/教程同步（2026-10-20）

- 新增 8 类模型服务商适配：OpenAI、Anthropic、Gemini、OpenRouter、
  Azure OpenAI、LM Studio、llama.cpp、vLLM，以及自定义 OpenAI 兼容。
- 新增 `core/model_router.py`：tool calling / JSON / vision / context 路由，
  本地失败或能力不足自动云端兜底。
- 新增增量 ACL-aware RAG：页码/offset 引用、混合检索、轻量 rerank。
- 新增 GUI Agent 质量层：UIA+OCR/视觉双通道、动作验证、重试修复、
  DPI/多显示器/IME 输入策略。
- 新增插件版本/信任/兼容检查、检查更新、更新前备份、回滚账本。
- 新增团队 RBAC、登录绑定、用户隔离、集中配置和脱敏审计导出。
- 新增模型用量/成本面板与价格估算。
- 新增 GUI：cloud_provider_dialog、rag_dialog、team_dialog、usage_dialog、
  panel_registry。
- PyInstaller 不再重复打包 gui/core 源码树，产物约 370 文件 / 148.6MB。
- 本地全量测试：1292 passed / 2 skipped；覆盖率约 60.36%。
- 同步 README、ARCHITECTURE、docs/00/10/20/50/70/80、FAQ、使用说明、
  模型教程、检测手册、部署步骤、开发者须知和程序内新手教程。

### P1/P2 工程收口（2026-10-20）

- 新增 `core/command_policy.py`；应用启动、关机/重启、代码测试命令全部去掉
  `shell=True`，改为白名单 + argv + 权限中心 + 审计。
- `core/sandbox.py` 改为显式 cmd 包装，不再使用 Python `shell=True`；
  Bandit HIGH 清零（shell=True 与弱哈希安全用途提示均已处理）。
- 新增 `.venv` / `.runtime-venv` / `.build-venv` 创建与检查脚本，并实际验证
  三套环境；新增 `requirements-runtime.lock` / `requirements-runtime-full.lock`。
- 可选依赖 Pillow 升级到 `>=12,<13`，运行环境不再混入 Jupyter/pytest 等开发包。
- 新增电脑文件/窗口、chat mixin、任务中心、安全中心、语音、便携打包、
  install.bat、PyInstaller 产物检查等测试。
- 分四批收敛剩余全部 `except Exception: pass`：174 -> 0，`check_silent` 基线为 0。
- 最终全量测试：1185 passed / 2 skipped；全项目覆盖率 58.25%，
  CI 增加 `coverage report --fail-under=58` 门槛。
- chat_mixin 覆盖率从 27.9% 提升到 52%（该文件单独覆盖率）。
- 新增 PyInstaller missing-module 分类许可列表与检查器，270 条已知噪声
  全部归类，出现未知缺包会失败。
- 完整可选依赖环境已安装并验证：19 个可选包全部可导入，Playwright Chromium
  启动通过，faster-whisper 后端可识别，Office 解析/OpenCV/Pillow 功能检查通过；
  67 个完整运行依赖 0 已知漏洞。
- MCP stdio 启动去掉动态 shell=True，改为 command_policy + 显式 cmd.exe + shell=False。
- 新增 `scripts/run_windows_build_check.ps1`，本地已完整跑通与 GitHub
  Windows workflow 等价的构建、产物检查、warning 分类和启动冒烟。
- 使用干净 `.build-venv` 重新跑 PyInstaller，新增 Qt 插件与敏感文件检查、
  Windows 打包 CI workflow。
- `install.bat` 改为精确选择 Python 3.12/3.11/3.10，并增加版本硬校验与
  运行兼容性检查。

### 兼容性矩阵、v0→v1→v2 数据迁移与插件 API 边界（2026-10-20）

- 新增 `.github/workflows/compat-matrix.yml`：Windows 2022/latest  Python 3.10/3.11/3.12
  共 6 个兼容任务，覆盖依赖安装、清单生成、语法编译、数据迁移 dry-run、
  插件 API 检查和核心兼容测试。
- 新增 `core/data_migrations.py` 的逐级迁移框架：缺失版本按 v0 处理，
  `v0 -> v1 -> v2` 不跳步；JSONL 坏行原文写 `.bad_lines`，SQLite 用事务和
  `x6_meta`；迁移前自动备份到 `data/_migrations/`，失败不覆盖原文件。
- `core/data_schema.py` 自检新增 `migratable` 提示；启动时仍由 Trunk 自动迁移。
- 新增 `core/plugin_api.py`：插件公共 API v1.0、`PUBLIC_CORE_MODULES`、
  禁止 `core.trunk` / `core.data_schema` / `core.secret_store` 等私有依赖；
  插件市场安装、下载和本地 `.py` 安装均在执行/落盘前静态检查。
- `modules_repo/manifest.json` 的 42 条官方模块新增 `api_version: "1.0"` 与
  `first_party: true`，并重新 rebuild + RSA 签名；`check_repo_sync.py` 42/42 通过。
- `tools/check_plugin_api.py` 同时校验 manifest 和源码边界；`test.yml` / 兼容矩阵已接入。
- 更新 `使用说明-小白版.txt`、首次设置向导、帮助菜单新手教程、`README.md`、
  `ARCHITECTURE.md`、`CONTRIBUTING.md`、`docs/README.md`，并新增
  `docs/70_兼容性与数据迁移.md`。

### 11 个存量超标文件拆分完成（2026-10-19）

- `core/computer_agent.py` 1097 -> 359，拆出 perception/planner/executor/verifier。
- `modules/installed/computer_controller.py` 925 -> 213，拆出 app/input/system/parser tools。
- `modules/installed/personality.py` 923 -> 51，拆出 state/time/social/style hints。
- `core/code_agent.py` 844 -> 320，拆出 context/explorer/runner/git。
- `gui/onboarding_wizard.py` 841 -> 353，拆出 local/install/final/provider 页面。
- `gui/mixins/ui_mode_mixin.py` 720 -> 19，拆出 navigation/guidance/task/launcher/actions mixin。
- `core/llm_client.py` 657 -> 213，拆出 shared/health/usage/cloud/local。
- `gui/code_editor_dialog.py` 617 -> 216，拆出 widget/ai/runner。
- `gui/settings_dialog.py` 607 -> 574，拆出公共设置组件。
- `modules/installed/auto_updater.py` 603 -> 120，拆出 problem/patch/download/policy。
- `core/license_core.py` 600 -> 41，拆出 keys/codec/payload/file/verify。
- 所有生产文件均 <= 600 行；文件长度 baseline 仅保留 `core/trunk.py` 门面预算。
- 旧公共导入路径全部保持兼容。


### 文件长度守卫改为默认 600 行（2026-10-19）

- 新增文件默认上限从 1300 降为 600 行。
- 存量超标文件在 `tools/file_size_baseline.json` 中冻结当前行数，只许下降。
- `core/trunk.py` 独立锁定为 220 行。
- 新增 `tests/test_file_size_policy.py` 防止预算回涨。


### Trunk 门面拆分与行数锁定（2026-10-19）

- `core/trunk.py` 从 1268 行拆到 151 行，只保留组合根、`__init__` 和公共门面。
- 新增 `trunk_config.py`、`trunk_memory.py`、`trunk_registry.py`、`trunk_background.py`、`trunk_reply.py`。
- 新增 `tests/test_trunk_facade.py`：锁定 220 行预算，禁止 Trunk 类重新新增业务方法。
- `tools/check_file_sizes.py` 增加 trunk 相关文件的独立行数预算。


### 18 项代码质量硬化（2026-10-19）

- 风险等级改为动作类型强制校正，模型不能把高危动作降为 low。
- patch 引擎增加受保护目录与 realpath 路径校验。
- 测试/lint 接入沙箱命令执行器：敏感环境清理、资源限制、超时/取消/进程树清理。
- 无界面 Agent 默认 fail-closed，只读动作例外。
- Git 分支和提交改用参数数组，消除 shell 注入。
- Agent 弹窗关闭增加取消、等待和后台安全关闭。
- 截图文件名加纳秒，OCR 缓存按文件签名并 LRU 限制。
- 新增 Agent 运行产物保留策略和 RunRegistry 淘汰。
- Browser 的 Playwright 调用固定到专属线程。
- WorkspaceIndex 增加增量刷新。
- 观察支持按需截图/UIA，grounding 按需 OCR/视觉。
- 拆分 ComputerFileToolsMixin、ComputerWindowToolsMixin 和若干工具模块，新增文件长度守卫。
- 新增统一 swallowed 异常诊断，静默失败存量从 372 降至 1。
- 新增懒加载编译/导入检查、真实 Agent E2E、Ruff/Mypy 静态检查与 CI。


### Agent 可控闭环（2026-10-19 收口）

- 新增 `core/agent_router.py`、`core/agent_orchestrator.py`：一个入口自动路由代码/电脑/对话。
- 新增 `core/agent_permissions.py`：代码与电脑 Agent 统一权限、once/session/always 确认与审计。
- 新增 `gui/agent_timeline.py`、`gui/agent_journey_dialog.py`：实时步骤、截图、暂停、继续、取消、人工接管、一键撤销。
- 修复 `core/code_agent.py` 默认测试命令缺少 `sys` 导入的问题；增加 pytest/npm/cargo/go 自动探测。
- 修复 `control_visible` 用非空 dict 误判成功的问题；实现 `text_changed`、`element_value`、`url_contains`、`file_contains` 验证。
- 电脑 Agent 增加 Observe -> Plan -> Act -> Verify -> Replan 动态循环、element_id/rect/confidence grounding、截图目标框选。
- patch 引擎支持 update/create/delete/rename/write，并支持顺序操作模拟与完整回滚。
- 代码 Agent 支持 read_file/grep/list_files/find_symbols/run_command 探索工具和可取消/可暂停/可超时命令。
- 浏览器模块增加 DOM 感知接口，电脑 Agent 支持 browser_* 动作。
- 修复多显示器/高 DPI 下的虚拟桌面坐标、全屏截图、前台窗口和控件值读取。
- 新增 `tests/test_agent_closure.py`；全量 pytest：1026 passed / 2 skipped。

## v25.2.23 - 2026-10-19

### Agent Harness 基础能力（2026-10-19）

- 新增 `core/agent_harness.py`：RunRegistry、任务活动同步、统一错误信封。
- 新增 `gui/activity_center_dialog.py`：运行中活动中心；状态栏显示运行中 N。
- 新增 `gui/theme_manager.py`：主题、字号、密度持久化。
- 新增 `gui/window_state.py`：窗口位置、大小、最大化状态记忆。
- 设置窗口增加主题和界面密度。
- 新增 `core/workspace_index.py`：文件、Python 符号、import、测试关联索引。
- 新增 `core/patch_engine.py`：多文件 patch 校验、diff、应用、备份和回滚。
- 新增 `core/action_schema.py`：类型化电脑动作和验证条件。
- 新增 `core/computer_agent.py`：电脑操作 Observe -> Act -> Verify -> Retry 基础 harness。
- 新增 `gui/diff_dialog.py`：文件/hunk 选择、diff 预览和应用。
- 代码编辑器 AI 修复增加 diff 审批和右键撤销上次 AI 修改。
- `Trunk.get_workspace_index()` 提供项目索引入口。
- 新增 `tests/test_agent_harness.py`、`tests/test_code_agent.py`、`tests/test_computer_agent.py`、`tests/test_code_agent_loop.py`、`tests/test_chat_branches.py`。
- 新增 `core/code_agent.py` 和 `gui/code_agent_dialog.py`：多文件 patch、审批、测试、失败继续修复。
- 新增 `core/visual_grounding.py`：UIA 元素解析和目标 grounding。
- 新增 `core/computer_recorder.py`：电脑操作录制与回放。
- 新增 `gui/feedback_states.py`：统一 Loading / Empty / ErrorCard 组件。
- 设置增加搜索、主题和密度；窗口位置/大小/最大化状态持久化。
- 聊天右键增加编辑上一条、重新生成和创建对话分支。
- 代码编辑器 AI 修改增加 diff 审批、右键撤销和保存后索引更新。
- 设置搜索、主题与界面密度；窗口布局记忆。
- 聊天右键支持编辑上一条、重新生成和创建分支。
- 活动中心接入聊天、任务、学习、TTS、BgWorker 和后台后处理。
- 代码 Agent 增加失败后继续修复、测试命令和 lint 命令输入。
- 代码 Agent 增加 Git 工作区状态记录、dirty diff 备份和测试失败定位解析。
- MCP stdio 子进程连接/断开进入活动中心，并预导入传输层避免并发 import 崩溃。
- 设置项增加影响说明、主题/密度即时预览、命令面板快捷键配置。
- 电脑 Agent 融合 UIA + OCR + 多模态 grounding，并支持 LLM 跨应用任务计划和审批执行。

### 文档合并（2026-10-19）

- 开发文档按主题合并为 3 份主文档：
  - `docs/00_产品架构与UI主文档.md`
  - `docs/10_开发流程与工程手册.md`
  - `docs/20_优化路线与实施记录.md`
- `UI简化与导航方案`、`开发流程与目录结构梳理`、`四阶段可落地优化方案`、
  `四阶段实施记录`、`现有功能深化优化方案`、`深度优化记录`、
  `小6智能体最新架构与功能说明`、`小6工程化落地-执行手册`、
  `小6工程化风险解决方案` 改为跳转页，避免同一事实多份副本。
- `docs/README.md`、根目录 README 和 ARCHITECTURE 的文档索引已同步。
- 用户说明合并：`使用说明-小白版.txt` 成为唯一完整用户手册；
  旧短版 `使用说明.txt` 已删除，打包/便携版只带完整手册。

### UI 分层与崩溃补报修复（2026-10-19 同步）

- 新增简单/高级 UI 模式：普通用户默认简单模式，高级功能折叠保留。
- 新增 `gui/ui_mode.py`、`core/feature_registry.py`、`gui/guidance.py`。
- 头像菜单固定 5 项：切换模式、检查更新、设置、登录/切换账号、帮助。
- 高级模式新增更多菜单，按任务/资料/工具/安全/插件-MCP/开发/帮助分组，并自动去重。
- 左侧栏改为可滚动区域；模块区显示模块（N），无模块按钮时显示暂无模块按钮。
- 修复按钮图标和文字丢失导致头像、清空聊天、模块区出现空按钮的问题。
- 统一任务入口：输入框聊天/任务切换、聊天转为任务、任务结果卡片、失败重试和增加预算继续。
- 修复自动补报误报：启动时先快照旧 `.running`，再写当前 pid，并检查 pid 是否存活。
- `log_digest` 只读取 `faulthandler.log` 最近一次启动后的现场，避免 pytest 历史栈混入。
- 最新验证：993 passed，2 skipped；按钮预算 119/119；静默失败检查 341/372。

###  四阶段安全与 Agent 体验优化

**第 1 阶段：安全底座**
- 新增统一权限中心、网络出站网关、进程级代码沙箱、结构化审计日志和紧急停止。
- 工具执行前经过权限中心；无确认界面时危险操作 fail-closed。
- LLM、搜索、插件市场、更新器、通知、MCP、Ollama、天气等出站请求接入网络策略。
- 手机端支持 HTTPS 自签名证书、Secure Cookie；远程工具默认禁用。

**第 2 阶段：Agent 体验**
- 新增可持久化任务状态机，支持暂停、取消、恢复、失败重试。
- 新增任务中心：任务列表、步骤时间线、状态和错误查看。
- 文件编辑确认框展示 unified diff。

**第 3 阶段：知识能力**
- 新增 PDF/Word/Excel/PPT/Markdown/HTML 文档解析与分块。
- 新增 BM25 + 向量混合检索、记忆编辑/遗忘、工作区目录隔离。
- 知识库窗口支持导入文档。

**第 4 阶段：生态与工程**
- 新增模型注册表、用量统计、插件治理、固定评测集。
- MCP 工具权限描述与 stdio 子进程敏感环境变量清理。
- 新增 `requirements.lock`、SBOM、便携版打包脚本。

**测试**
- 全量测试：971 passed，2 skipped（共 973 个用例）。
- 新增 `tests/test_optimization_phases.py`、`tests/test_security_hardening.py` 等回归测试。

**移除**
- 移除「手机远程」功能：删除 `mobile_remote` 模块、`gui/mobile_dialog.py`、启动入口、配置项、测试与相关文档。
- 保留其它本地服务安全加固：MCP 鉴权、bot_server token、权限中心和审计日志。

**深度优化**
- 任务运行时：断点续跑跳过已完成步骤、取消状态防覆盖、线程自动清理。
- 权限确认：支持仅本次 / 本次运行 / 永久允许，安全中心支持撤销权限和导出审计。
- 云端流式补上脱敏和用量统计；网络网关增加 DNS rebinding 检查和事件日志轮转。
- 检索改为批量写入和 BM25 缓存，文档解析增加 50MB 上限。
- 任务运行时支持 DAG 依赖、任务预算、幂等键和 step_id trace。
- 权限规则支持路径/域名/扩展名约束，永久允许自动收窄范围。
- 新增工具参数校验和标准结果结构；沙箱增加内存/CPU 监控；网络重定向逐跳校验。
- 新增上下文预算和短期响应缓存。
- 新增 SQLite FTS5 知识索引；记忆支持 TTL、过期清理和遗忘 tombstone。
- 任务中心改为事件驱动刷新。
- 权限规则增加命中统计和范围编辑；安全中心可修改约束。
- 知识库支持删除后清理索引、全量重建索引、来源/页码引用和来源检索。
- 模型路由增加失败熔断、P50/P95 延迟统计和模型健康查询。
- 复杂请求自动进入任务运行时；任务运行时成为主链路。
- 安全中心增加安全摘要、权限范围编辑和可理解的操作说明。
- 知识库增加 OCR、RRF 混合检索、工作区隔离、文档管理、重建索引和页码引用。
- 模型中心增加模型目录、硬件概览、推荐模型和回退链展示。
- MCP 工具权限声明、插件信任/权限展示和插件回滚。

---

## v25.2.22 - 2026-10-14

### ✅ 安全 / 稳定性 / 工程化收尾（2026-10-19）

**配置加密（Windows DPAPI）**
- 新增 `core/secret_store.py`：`data/config.json` 里的敏感字段
  （cloud_key / webhook / secret / token ）落盘为 `dpapi:v1:...`，
  **绑定当前 Windows 用户**（拷到别的机器解不开）；内存里仍是明文。
- 接入 5 个读写点：`core/config.py`、`core/trunk.py`、`core/llm_client.py`、
  `core/auto_report.py`、`core/crash_watchdog.py`。
- `config.default.json` **保持明文**  它要发给别人，加密了对方解不开。

**修：首次设置向导在 UI 线程同步请求 Ollama（实测 4.11 秒）**
- `model_setup.check()` 新增 `probe` 参数；`needs_onboarding` /
  `show_onboarding` / `_fill_final` 全部跳过网络探测（0.00 秒）。
- 用户在向导里点「保存并检测」时仍会真探测。
- 启动路径（`main_window._do_login_flow`  `needs_onboarding`）也不再白等 3 秒。

**修：协议升到 v3.1 后测试弹框卡死**
- 根因：`JarvisWindow.__init__` 里协议框 `exec_()` 会阻塞；测试的
  autouse 桩是**函数级**，而 `test_ui_responsiveness` 的 `win` 是
  **模块级**  模块级先构造主窗口，桩还没生效  pytest 卡在 collected。
- 修法：桩改 **session 级**（`pytest.MonkeyPatch`）。

**修：三个偶发失败**
- `test_vector_store`：只统计 `/api/embeddings` 端点（后台线程会打 `/api/chat`）。
- `test_mcp_stdio`：握手超时 25s → 60s。
- `ollama_installer.download()`：取消前置判断  立刻取消不再先建连接，
  也不会把"取消"误报成"错误"。

**文档**
- `ARCHITECTURE.md`：用例 890 → 932、分发 48MB → 201.4MB。
- `使用说明-小白版`：补上"崩溃摘要会自动上报"这个例外。
- `docs/开发流程与目录结构梳理.md`：反馈通道 / 凭据存储的描述更新为现状。
- `.github/workflows/test.yml`：注明为什么不跑 `check_repo_sync`
  （CI 上 modules_repo 未签名，验签必然失败）。


### 🔵 反馈通道从「QQ 邮箱授权码」改为「飞书群机器人 Webhook」

**为什么改**：邮箱授权码不是"密码"，而是**邮箱控制权**（SMTP 能发，
通常 IMAP/POP3 还能收）。把它打进程序发给别人 = 把邮箱交出去 ——
Nuitka / 加固壳都挡不住，因为程序运行时必须把明文交给
`smtplib.login()`，断点或内存 dump 就能拿到。
群机器人 webhook 只是个"公开地址"，泄露了删掉机器人重建即可。

**改了哪些**
- 新增 `core/notifier.py`：飞书 / 企业微信 / 钉钉 三通道，
  `Notifier(config).send(text)` 统一出口，用 `notify_channel` 切换；
  飞书、钉钉的加签算法都已实现（按官方算法）。`_post_json` 只放行
  http/https（沿用原 `bot_server._safe_url` 的防线）。
- `gui/feedback_dialog.py`：SMTP → `Notifier`；网络请求进 `QThread`
  （不卡 UI，`check_threads`/`ui_responsiveness` 都盯着这个）；
  500 字上限；60 秒本地限流（发送失败自动放行，允许立刻重试）。
- `gui/mixins/dialog_mixin.py`：`_panel_commands()` 加「意见反馈」——
  它之前是**孤儿**（`show_feedback()` 写了但全项目没有任何地方调用），
  现在设置窗口和 Ctrl+K 命令面板都能打开。
- `core/bot_server.py`：`send_wecom()` / `send_dingtalk()` 收敛到
  `Notifier`，去掉一份重复的 urllib 拼接实现（公开 API 不变，
  `gui/bot_dialog.py` 不受影响）。
- 配置：删掉 `feedback_email_*` / `feedback_smtp_*` 5 个键，
  新增 `notify_channel` / `feishu_webhook` / `feishu_secret` /
  `dingtalk_webhook` / `dingtalk_secret`。
- `tests/shape_snapshot.json` 同步更新（config.json 键集变了，总数仍 43）。
- 新增 `tests/test_notifier.py` 14 条用例（含飞书加签按官方算法复算）。

**验证**
- 7 个守卫全过；`check_silent` 仍 354、`check_buttons` 仍 115（都没涨）
- 全量测试 890 -> **900+ passed**
- 真实 webhook 端到端：返回 `{"code":0,"msg":"success"}`，通道 feishu
- 全盘扫描明文邮箱授权码：**0 份**（配置与备份里都已清除）

⚠️ **注意**：webhook 地址会随程序分发（在 `config.default.json`
和 `core/config.py` 里）。这是故意的 —— 朋友拿到程序才发得出反馈。
它是"公开地址"，泄露最坏是被往群里发消息，删掉机器人重建即可。
代码侧已实现飞书加签并填好 `feishu_secret`；
**到飞书机器人后台勾选「签名校验」后才生效**  勾选前签名会被忽略，
带签/不带签都能发（实测确认过）。勾选后如果消息发不出去，
先检查三处 `feishu_secret` 是否一致。

### 🔴 修：`libs/` 里 5 个必需依赖缺了 3 个（打包目录跑不起来）
用户问"打包目录里打包后能正常使用吗" —— 去实测，发现一个**会让整包废掉**的问题：

    requirements.txt 要 5 个：PyQt5 / requests / numpy / cryptography / psutil
    libs/ 里只有 2 个：numpy / requests
    **缺 PyQt5（142 MB）、cryptography、psutil**

后果很直接：`run.py` 开头就有这么一段
    _missing = _has_missing_deps()      # 检查 PyQt5 / cryptography
    if _missing:
        print("缺少依赖: " + ", ".join(_missing))
        sys.exit(1)
**在干净机器上跑源码版会直接退出**，而且用户看到的就是一句
"缺少依赖: PyQt5, cryptography"，不知道该怎么办。

- **修法**：把 3 个包装进两处的 `libs/`
      E:\xiaoliu\libs          4168 文件 / 199.5 MB
      E:\xiao6-package\libs    4168 文件 / 199.5 MB（严格比对：0 缺 0 多 0 不同）
  逐项：PyQt5 2524 文件 142.3 MB / numpy 946 / 40.0 MB /
        cryptography 122 / 10.0 MB / psutil 18 / 0.4 MB / requests 27
- **⚠️ 两处都要补**：`sync_package.py` 的 `plan()` 会把"目标里多出来的"
  算成待删除 —— 只补打包目录的话，**下次同步就被删掉了**。
- **验证方式**（这才是真验证）：建一个**真空 venv**（5 个包一个都没有），
  只用打包目录自己的 `libs/` 去跑它 ——
      numpy OK / requests OK / PyQt5 OK / cryptography OK / psutil OK
      Trunk OK，工具数 63
      gui.main_window OK
      → ✅ 干净机器上可以跑
  之前那次"能跑"是**假的**：测试用的解释器里本来就装着这些包，
  测不出"干净机器"。

- **⚠️ 代价（要说清）**：打包目录 **47.8 MB → 247 MB**。
  这 200 MB 是**跑起来必须的**（PyQt5 一个就 142 MB），省不掉。
  真正的"可省"部分仍然是 optional_libs（1 GB）和 browsers（706 MB）。

### 顺手修：`Ctrl+K` 快捷键失败时不再静默
`gui/main_window.py` 里那段是 `except Exception: pass` ——
CI 上 `test_main_window_assembles` 报"Ctrl+K 快捷键没装上"，
而本地一直是绿的，**因为异常被吞了，本地/CI 的差别一个字都看不到**。
改成写一条日志（功能仍可用，但没有快捷键）。
⚠️ 这条**没定位到根因**（CI 环境专属，本地复现不出来）—— 如实记着。

### CI 就绪度（实测数据）
把仓库克隆到干净目录跑，**41 failed / 817 passed** → 现在：
    · `.github/workflows/test.yml`（windows-latest + offscreen +
      pip 国内源 + **先跑 rebuild_modules_repo** + pytest + 6 个守卫）
    · `tools/rebuild_modules_repo.py` 修了一个 CI 阻塞：
      `modules_repo/` 不存在时 `os.listdir` 直接抛 FileNotFoundError ——
      而 CI 的第一步就是跑它，一上来就红
    · `tests/conftest.py` 加了一组**集中式跳过规则**
      （requires_manifest / requires_data / requires_optional_libs /
        requires_local_tool / requires_logs + 一张表 + 一个 hook）
      干净检出：**41 failed → 6 failed**（860 passed / 24 skipped）
    ⚠️ 为什么用"一张表 + hook"而不是在每个函数里插一句：先试了后者，
      写脚本往 7 个文件里插调用，**脚本的 docstring 跳过逻辑有 bug，
      把几个函数的 docstring 开头行删掉了**（直接语法错）。
      测试文件是"人写的文档 + 代码"，不该用正则去动。
测试 890 个用例，全通过。

## v25.2.21 - 2026-10-14
### 落地 P4：`ARCHITECTURE.md` 写成 3 页速览（31 行 → 162 行）
初版方案说"文档不足，换个人半天找不到北" —— 核实后发现**文档是充足的**
（967 行架构说明 + 224 行小白版 + 796 行 CHANGELOG）。
**真正的问题不是"没有文档"，是"太长，新人读不完"** ——
967 行对刚接手的人来说等于没有。

所以这一版**不是从零写，是把 967 行压成 10 分钟能读完的骨架**：
  · 一句话架构（微核 + 星型拓扑图）
  · **启动顺序**（从双击 bat 到窗口出现，含那两处"必须在此之前"的坑）
  · **数据流**（用户输入 → 检索 → 拼提示词 → 模型 → 后处理 → 后台队列）
  · 工具是怎么挑出来的（两级过滤，改工具描述时会用到）
  · 一次 `trunk.call` 的完整路径（含安全分级）
  · 文件分工表 + **改插件后必须做的三步重签**
  · **新人从哪儿读起：这 10 个文件看完就懂 80%**
  · 几条"不能违反的规矩"（每条都注明了**谁在盯着**）
  · 出问题时先看哪儿（现象 → 文件对照表）
  · 工程化现状（用例数 / 守卫数 / 覆盖率 / 分发体积）
开头第一句就写明：**这份是骨架，细节去查 967 行那份** ——
免得新人以为这就是全部。

测试 890 个用例，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.20 - 2026-10-14
### 落地 P1-f：`modules/installed/personality.py` **15.5% → 60%**（104 个用例）
它是**全项目最大的文件**（559 条语句），做的是"让小6 像个人"：
心境、口头禅、称呼、主动搭话、天气/节日/深夜这些情境提示。

它的结构是**四十多个小 `*_hint`**，每个往提示词里塞一句话。
这种代码最容易出的问题是：**某一个 hint 抛异常 → 整段人格提示拼不出来
→ 它突然变得很生硬**（用户感觉是"它今天怪怪的"，
根本想不到是某个 hint 崩了）。所以本文件分两块：
  · **批量**：40 个 hint 逐个调（含空串 / None / 超长 / emoji / 控制字符）
  · **重点**：`full_hint`（拼装入口）、`update_emotion`（心境状态机）、
    `_load`（坏文件兜底）

**🔴 抓到 4 个真 bug（同一类：`None` 输入直接崩）**
    `full_hint(None)`          TypeError: object of type 'NoneType' has no len()
    `update_emotion(None)`     同上
    `short_reply_hint(None)`   同上
    `repeat_hint(None)`        TypeError: 'NoneType' object is not subscriptable
    `learn_people(None)`       同上

  **为什么 None 是真会来的**：`full_hint(user_text)` 有 3 个调用点
      core/llm_client.py:242
      core/pipeline/legacy_reply.py:159
      core/pipeline/prompt_assembler.py:39
  输入来自 `_extract_user_text(msgs)` —— 消息里没有 user 角色、
  或者内容是空的时候它**返回 None**。

  **后果不是"崩一下"**：调用处外面包着 try/except，所以是
  **人格提示静默失效** —— 那一轮小6 突然没性格，
  而日志里什么都看不到，极难归因。
  已在 5 个入口统一把 None 当空串（`if not isinstance(x, str)`）。

**坏文件兜底逐项验**：`personality.json` 是
  · 不存在 → 用默认值
  · JSON 坏了 → 退回默认
  · 空文件 / 内容是数组 / 字符串 / 数字 / null → 都退回 dict
这个文件是用户长期积累的（心境、称呼、纪念日），被强杀/断电时真会写坏。
坏了至少程序要能起来 —— 用户的感觉该是"它性格重置了"，
而不是"程序打不开了"。

**⚠️ 两条测试自己的错：**
  · 断言 `personality_growth(txt)` 能收参数 —— 跑出来
    `TypeError: takes 1 positional argument but 2 were given`。
    是我照"其他方法都收 user_text"的规律**猜的，没看签名**。
  · 查"流水线有没有引用 personality"时查的是 `context_builder.py`，
    那里根本没有 —— 真正调 `full_hint` 的是另外三处。
    改成查**真实存在的那三个调用点**，而且反过来要求
    "每个调用点都真的调到了 full_hint"（改了名字它们会静默失效）。

**记录了 `ask_confirm` 取向之外的另一个既有选择：**
  `full_hint` 里那个 `except: pass`（用户自定义人格读取失败时静默跳过）
  是合理的 —— 读不到自定义性格只是少一条提示，不该让整段拼不出来。

### 覆盖率进展（P1 全部完成）
    core/self_check.py                 0.0%  →  74%
    core/vector_store.py              32.8%  →  76%
    core/realtime/engine.py            0.0%  →  76%
    core/module_server.py              0.0%  →  85%
    modules/installed/auto_updater.py 13.7%  →  83%
    modules/installed/personality.py  15.5%  →  60%
测试 786 → **890 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0
（改了 personality.py，已重签 43 条）。

## v25.2.19 - 2026-10-14
### 落地 P1-e：`modules/installed/auto_updater.py` **13.7% → 83%**（64 个用例）
这是**全项目最危险的一段代码**：
  · 它覆盖程序自己的文件（core/gui/modules 下的 .py）
  · 它是**唯一从网上拉代码并写进磁盘**的地方
  · 写坏了用户就打不开程序 —— **而且不知道是怎么坏的**
所以重点不是"功能对不对"，而是**"坏事发生时它拦不拦得住"**。

**六道闸逐个验（任意一道能绕过去，用户就可能拿到改坏的程序）：**
  ① 验签 —— **必须在下载之前**终止（先下后验的话，恶意内容已经落盘了）
  ② 空文件列表 —— 拒
  ③ 路径穿越 `../../x.py` —— 拒，**且不去下载**
  ④ sha256 不符 —— 拒，**且一个字节都不写**
  ⑤ 下载失败 —— 拒
  ⑥ 用户取消 —— **一个文件都不许动**（含不留下备份目录）

**成功路径也要验：**
  · 文件被正确替换
  · **旧文件必须留备份** —— 那是回滚的唯一依据
  · **替换中途失败要回滚**（比"更新失败"更糟的是"改了一半"：
    程序可能直接起不来，而用户无从判断）
  · 记更新历史（对话框读它）
  · 进度回调被调用（界面上那根进度条靠它）

**🔴 抓到 2 个真 bug：**
  · **`build_suggestion` 解析失败时返回 `".py"` 而不是空串**
    原写法 `(mod.group(1) if mod else "").strip(".py") + ".py"`
    —— 解析不出时得到 `".py"`。而调用方的守卫是 `if not target_file:`
    **`".py"` 是真值，守卫形同虚设**：闭环会拿着一个垃圾目标名
    继续往下走（打补丁写进 `.py`、再去部署），最后报一句很难懂的错。
    实测日志里能看到 `③ 编程小匠补丁: .py (7字)`。
  · **沙盒验证失败时消息里没有原因**
    原来返回 `out[-100:]`（stdout 的尾巴）—— 而 Python 的报错走
    **stderr**，于是用户看到"沙盒验证失败: "后面**什么都没有**。
    实测：补丁是两行注解语句，import 时求值报 NameError，
    报错全在 stderr、stdout 是空的。
    **"只告诉你失败了、不告诉你为什么"的提示等于没提示** ——
    用户既不能自己修，也没法把错误贴给别人看。已改成优先给 stderr。

**新增结构守卫：**
  · `deploy_patch` 热重载失败必须回滚（磁盘上是坏的 = 下次启动起不来）
  · `backup_current` 只留最近 5 个（备份是整个 core+modules，
    不限个数的话用几次就把磁盘吃满 —— 和 backups/ 涨到 1.4 GB 同类）
  · 沙盒临时文件名必须带 pid + 线程号
    （与 `hot_reload.sandbox_test` 同一个坑：共用固定名时两个验证流程
    并发会互相覆盖，**验证结果张冠李戴**）
  · 「自主.升级」规则关掉时：分析照做，但**不改文件**

**⚠️ 记录了 `ask_confirm` 的一个取向（没改，放明处）：**
  `trunk.confirm()` 抛异常时返回 **True（放行）**。风险是 GUI 出问题时，
  本该弹窗确认的危险操作会静默放行。好在后面有备份+回滚兜着，
  而且 `_allow_self_upgrade` 那道规则闸还在。这是既有选择，不是漏写。

**⚠️ 三条测试自己的错（如实记下）：**
  · 把 `/absolute.py`、`//server/x.py` 列进"必须挡住"是错的 ——
    代码是 `lstrip("/")` 后当**相对路径**处理，落在项目内，**那才是对的**
    （拒绝的话，清单里所有以 / 开头的正常路径都会被拒）。
    关键性质是"**落在 base 内**"，不是"返回 None"。
  · 假 LLM 两次调用返回了同一个文本 —— 而闭环里 `llm.chat` 会被调
    **两次且用途完全不同**（第 1 次出建议、第 2 次要完整代码）。
    于是补丁内容是"目标模块: m.py"那两行，注解在 import 时求值报
    NameError，沙盒**正确地**判了失败，我却一度以为是沙盒坏了。
    加了个 `StagedLLM`（第一次给建议、第二次给代码）。
  · 断言自升级开关"默认该是关的" —— 跑出来是红的，**看过代码才确认
    是我想当然了**：代码注释写着"默认开（等于改动前的无条件执行）"，
    是加这个开关时有意选的"保持原有行为"。改成记录这个取舍。

### 覆盖率进展（累计）
    core/self_check.py              0.0%  →  74%
    core/vector_store.py           32.8%  →  76%
    core/realtime/engine.py         0.0%  →  76%
    core/module_server.py           0.0%  →  85%
    modules/installed/auto_updater.py 13.7% → 83%
测试 722 → **786 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0
（改了模块文件，已 rebuild_modules_repo + sign_modules 重签 43 条）。

## v25.2.18 - 2026-10-14
### 落地 P1-d：`core/module_server.py` **0% → 85%**（24 个用例）
它对外开一个 HTTP 端口（8899），**GUI 启动时自动内嵌启动** ——
也就是说：**用户机器上一直有个本地服务在跑，而它从没被验证过。**

它错了不是"某个功能不好用"，而是"端口被占 / 请求打不开 / 路径能穿出去"。
所以这批用**真起服务、真发请求**（临时端口，不占 8899）。

- **重点验了路径穿越**：`/modules/../secret.py` 这类请求能不能读到
  仓库外的文件。
  这个服务对 127.0.0.1 开放 —— 本机任何程序（包括浏览器里的网页，
  通过 CSRF / DNS rebinding）都能请求它。真能穿出去就是**任意文件读取**。
  现在的实现是"先查清单、清单里没有就 404"，所以穿越名天然查不到。
  测试钉住这个性质 —— 哪天有人改成"直接拼路径"，它会立刻红。
  同时静态检查确认只绑 `127.0.0.1`（不是 `0.0.0.0`）。
- 六个端点逐个验：`/`、`/api/modules`、`/api/modules/<name>`、
  `/modules/<name>.py`、`/api/health`、未知路径（404）
- 清单的三种异常输入：**不存在** / **JSON 坏了** / **带 BOM**。
  ⚠️ BOM 那条最实际：这个 manifest 是**要提交到 git、可能被记事本或
  PowerShell 编辑**的文件，那两个工具都爱加 BOM。原来用 utf-8 读会直接抛，
  表现是"模块列表空了"，很难查。
- 端口被占要返回**能看懂的话**而不是抛异常（它是启动时自动起的，
  抛了会把整个启动流程挂掉）
### ⚠️ 三条测试自己的错（不是服务器的问题，如实记下）
  · **URL 里的中文没 percent-encode** —— `urlopen` 要求请求行是 ASCII，
    直接传中文会在**客户端**就抛 `UnicodeEncodeError`，
    看着像服务器崩了。加了 `urllib.parse.quote`。
  · `search_modules()` 返回的是 `{"找到": n, "结果": [...]}` 而不是 list；
    `get_module_stats()` 的键是 `模块总数` / `总大小KB` 不是 `模块数` /
    `总大小` —— 两个都是我先猜错了，照实际返回改了。
  · **"端口被占"那条用错了方法**：本来想"起两个同端口服务"，
    但 **Windows 上 `SO_REUSEADDR` 允许重复绑同一个端口**，
    第二个也能起来 —— 那条路测不出来。（这是 Windows 和 Unix 的
    真实差异，不是 bug。）改成让 `HTTPServer` 构造时抛 `OSError`。
  · 另外假模块文件写得太小（30 字节），`总大小KB` 按 `// 1024` 算
    永远是 0，测了等于没测 —— 改成写够 1 KB 以上。
### 覆盖率进展（累计）
    core/self_check.py       0.0%  →  74%
    core/vector_store.py    32.8%  →  76%
    core/realtime/engine.py  0.0%  →  76%
    core/module_server.py    0.0%  →  85%
测试 698 → **722 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.17 - 2026-10-14
### 落地 P1-c：`core/realtime/engine.py` **0% → 76%**（32 个用例）
实时对话的总调度：采集 → VAD → ASR → LLM → TTS → 播放，五个线程靠事件
总线串起来。它强依赖外部世界（麦克风、pyaudio、语音模型），所以原来没测 ——
但这恰恰最该测：**缺依赖时的话对不对、状态机会不会卡住、停止会不会留垃圾**，
这些都不需要真麦克风。

- **🔴 抓到一个很隐蔽的真 bug：ASR 一抛异常，线程直接死**
      def _asr_llm_loop(self):
          while self._running:
              try: buf = self._asr_q.get(timeout=0.3)
              except queue.Empty: continue
              self._handle_round(buf)          # ← 这里没包 try
  而 `_handle_round` 里的 `try:` 是**从 LLM 那一段才开始的** ——
  `asr.transcribe_frames()` 在 try **外面**。
  后果：ASR 抛一次异常 → 穿出 `_handle_round` → 穿出循环 →
  **线程直接死掉**。用户看到的是"实时对话突然不应答了"，
  **没有任何报错**，界面还显示 LISTENING，只能关掉重开。
- **顺着查出另外三个循环有同类隐患**（AST 逐个查的）：
      _capture_loop   只有 stream.read 在 try 里，
                      VAD / numpy / emit / 状态切换全裸着
      _tts_loop       队列取之后到 synthesize 之前那几行裸着
      _idle_loop      **一行 try 都没有**
  都修成"**循环体整体包住**"。原则：**工作线程绝不该被未处理异常杀死** ——
  它跑在后台，死了没人知道，而且它是常开的（实时对话的本意）。
- `_handle_round` 里 ASR 那一段**单独兜住 + 回监听态**：光靠外层循环
  能"线程不死"，但状态会卡在 THINKING（界面显示"正在思考"，
  其实是识别炸了）。
- 新增结构守卫：**AST 检查每个 `*_loop` 的 while 体必须整体在 try 里**。
  这条比任何单个用例都值钱 —— 它管的是"将来有人又加了裸代码"。
- 另外验证了：缺 pyaudio 的提示**带国内源**（v25.2.11 定的规矩，
  这次把它纳入测试）；麦克风打不开要**明确报出来**且不把 running
  设成 True；`idle_stop_sec=0` 时不该起这个常驻线程；
  播完要清轮次表（不清会随对话一直涨，表现为"用久了变卡"）；
  并发改状态 / 并发清轮次不崩。

### ⚠️ 顺手修了 `test_test_hygiene.py` 的一处误报
它判断"有没有建真 Trunk"用的是 `"Trunk()" in src` —— 而我在
`test_realtime_engine.py` 里定义了 `class FakeTrunk`，用的时候写
`FakeTrunk()`，**里面含有子串 `Trunk()`**，于是被误报成
"建了真 Trunk 却没走 make_trunk"。
改成负向断言的正则 `(?<![A-Za-z_])Trunk\s*\(\s*\)`，并逐个核对过 9 种
写法（`FakeTrunk()` / `make_trunk()` / `Trunk(base)` 都不算，
`self.trunk = Trunk()` 算）。

### 覆盖率进展（累计）
    core/self_check.py       0.0%  →  74%
    core/vector_store.py    32.8%  →  76%
    core/realtime/engine.py  0.0%  →  76%
    **总计 41.7% → 45%**
测试 666 → **698 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.16 - 2026-10-14
### 落地 P0+：崩溃转储配置（`tools/setup_crash_dumps.py`）
faulthandler 只能 dump **Python 层**栈，**看不到 numpy/Qt/torch 的原生
子帧**。如果那次 access violation 是崩在 `c10.dll` 里某个偏移，
光有 Python 栈定位不了 —— 得拿**进程级 dump**。

- 两条路都支持：
  · **WER LocalDumps** —— 系统自带，改注册表，配一次长期有效
    （要管理员：写的是 HKLM）
  · **procdump** —— Sysinternals 官方工具，不用管理员
    （实测下载成功 v12.01，1.3 MB，存 `data/tools/procdump.exe`）
- `崩溃转储配置.bat` 一键入口（看现状 / 下载 / 配置 / 打印监视命令）
- ⚠️ **几处容易配错的地方，都在代码里写了理由**：
  · 默认**不用** `-e 1`（首次异常就抓）—— 那会被 Python 内部的正常异常
    刷爆（它大量用异常做流程控制），几秒钟 D 盘就满。真正的崩溃一定是
    **未处理**异常，`-e` 就够
  · 必须 `-ma`（完整 dump）—— 迷你 dump 只有栈，而 C 层内存错误的
    现场在堆里，配迷你等于白配
  · dump 目录固定在项目下 `data/dumps/`，不散落到系统目录
  · **隐私提醒**：dump 是进程内存快照，**里面有聊天记录、记忆内容和
    API Key** —— 两种模式的提示里都写了这句
- ⚠️ 一个测试抓出来的 bug：`procdump_watch()` 写成了
  `return True, (" ".join(cmd), "说明…")` —— 多一层括号，
  调用方 `cmd, note = rest` 只拿到 1 个，直接
  `ValueError: not enough values to unpack`。

### 落地 P1-a：`core/self_check.py` **0% → 74%**（21 个用例）
用户点「深度自检」时期待的是"告诉我哪儿坏了"，所以它的准确性比别处要紧。
做法：造一个假 trunk 指向**临时小项目**，让 26 项检查**真跑**，
再逐个注入问题验证它真的报出来。

  · **抓到 2 个真 bug（同一类）**：`deep_check` 和 `health_score` 里
    写的是 `o["ok"]` / `o["error"]`，而 `_check_ollama()` 返回的 dict
    **形状不一定全** —— 遇到 `{"ok": False}`（没有 error 键）直接 KeyError，
    **把整个自检打挂**。
    **"自检本身崩掉"比"自检报出问题"糟得多** —— 用户点它就是为了
    知道哪儿坏了，结果它自己先死了。已全部改成 `.get()`。
  · 负向测试（**这才是重点**）：注入语法错 / 模块互相 import /
    日志里的 `sk-` 密钥 / 配置缺失 / 数据文件缺失 / 硬编码路径，
    逐个验证自检真的报出来
  · 反向测试：模块 `import core` 是**合规的**，不能误报
    （踩过的坑：老正则只要文件名出现在 import 行里就报违规）
  · 接线测试：`trunk._deep_check` / `_warmup_ollama` 必须还在
    （GUI 直接调前者，4 个测试打桩后者）

### 落地 P1-b：`core/vector_store.py` **32.8% → 75%**（26 个用例）
它是**记忆检索的核心** —— 错了表现为"小6 记不住事"，
很难归因（用户会以为是自己没说清）。关键设计是**降级**：
嵌入服务连不上时要自动退到关键词检索，并且 300 秒内不再重试。

  · **🔴 抓到一个影响很大的真 bug**：`__init__` 里**从来没初始化
    `_embed_retry_at`**，但 `_embed()` 的**成功路径**要用它
    （`if self._embed_retry_at != 0:` 用于"恢复了就提示一下"）。
    后果：
        第一次嵌入必然抛 AttributeError
        → 被自己的 except 当成"嵌入失败"
        → 设下 300 秒冷却
        → **每次启动后 5 分钟内语义检索完全不可用，静默走关键词降级**
    冷却判断那处用的是 `getattr(..., 0)` 兜住了，成功路径没有 ——
    所以这个 bug **只在"嵌入真的能用"时才暴露**，极难碰到。
  · **抓到 2 个健壮性问题**（都是"长期积累的文件"该有的防护）：
    · `data/vectors.db` **损坏时程序起不来**。而且修的时候发现：
      `_conn()` 里的 `PRAGMA journal_mode=WAL` 在坏文件上**自己就抛**，
      所以"先连接、抛了再补救"走不通（补救时还是要连接）——
      必须**开库前先验**。已加 `_ensure_db_ok()`：坏库改名
      `.corrupt` 留证再重建（不直接删，万一能人工抢救）
    · `data` 里混进 `{"text": None}` 时检索**整个崩掉**。
      原因是 `item.get("text", "")` —— `get` 的默认值只在**键不存在**
      时生效，键存在但值是 None 时照样返回 None，于是 `"x" in None`
      抛 TypeError。一份长期积累的库里出现几行脏数据很正常，
      不能因此让"回忆"整个不可用。已改成 `or ""`。
  · 重点验证：**冷却期内一次网络请求都不发**（这是冷却存在的
    全部意义 —— 否则每次检索都要白等一个 5 秒超时）
  · 验证"重启后记忆还在"（这是"记忆"这个词的底线）
测试 578 → **642 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

### ⚠️ 一次"用户文档从磁盘上消失"的事件（未定位到原因）
准备提交时发现 git status 里有 `D 小6工程化风险解决方案.txt` ——
**用户给的那份方案文档从磁盘上没了**（已从 git `checkout` 回来，
17164 字节完好）。

排查了所有带删除/移动的代码：
```
core/backup.py:264        只删 backups/ 下的旧备份目录
tools/sync_package.py     只删**目标目录**（E:\xiao6-package）里的东西
tools/measure_coverage.py 只删自己生成的临时 json
tools/check_*.py          没有删除操作
```
**没找到能删到项目根目录的路径 —— 至今没定位到原因。**

所以加了 `tests/test_user_docs_intact.py`（24 个用例），意义是：
**下次再发生会立刻红，而不是等用户发现自己的文档没了。**
  · 15 个用户文档逐个检查存在且非空
  · 6 个运行必需文件同样检查
  · **文档不能被 `.gitignore` 排除** —— 这次能恢复正是因为它在 git 里，
    被排除了就找不回来了
  · 静态检查：`tools/` 里不许有"对项目根目录动手"的删除（防回弹）
  · `backup._cleanup()` 只准删 `backups/` 里的东西
    （它是全项目唯一一个真的 `shutil.rmtree`）

⚠️ 没定位到原因不等于没风险 —— 如实记录在这。

### 测试（新增 4 个文件，85 个用例）
测试 578 → **666 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.15 - 2026-10-14
### 完善工程化方案：把"猜的"换成"实测的"，并落地 P0
用户给了一份《小6工程化风险解决方案》，让"完善可行落地"。
核实之后发现**方向全对，但 3 处前提/数字和实际不符** ——
照抄会白干几天。这一版全部改成实测值，并把最该做的 P0 做掉。

**核实结果**（每条都跑了命令）：
    初版说                      实测                        判定
    ───────────────────────────────────────────────────────────────
    覆盖率 0.24，补 11 个        **真实覆盖率 41.7%**        口径用错了
    用例涨到 0.4                 （0.24 是"测试行数:生产
                                  行数"，不是覆盖率；
                                  到 40% 反而已经过了）
    crypto/backup/vector        **48.9% / 61.3% / 32.8%**   前提不准
    "没测"                      —— 三个都已有测试
    "加崩溃捕获"                sys.excepthook 早有、       已做一半
                                crashes.log 早有，
                                缺的是 **faulthandler**（0 处）
    "文档不足，写 3 页"         已有 967 行架构说明 +       前提不成立
                                224 行小白版 + 796 行
                                CHANGELOG
    CI "20 分钟"                **仓库没有 remote**，       严重低估
                                且 libs/ modules_repo/
                                data/ 都不在 git 里
                                （git 只跟踪 341 个文件）

### P0 已落地：崩溃现场捕获（`core/crash_guard.py`）
  2026-10-13 那次 access violation **没现场、没定位**，根因是：
      `sys.excepthook` 只能接住 **Python 层**异常；
      access violation 是 **C 层**内存错误 —— 进程当场死，
      解释器根本没机会跑到 excepthook。
      （证据：那次崩溃时 `crashes.log` 里**什么都没有**）
  `faulthandler` 把 dump 做在信号/异常层，能在死之前写下所有线程的栈。
  - 新增 `core/crash_guard.py`：`enable()` / `dump_now()` / `status()` /
    `recent_crashes()`
  - `run.py` **模块顶层**第一个装（不是 main 里）—— 也覆盖"导入阶段就崩"
  - `tests/conftest.py` 也装 —— **那次崩溃就出在全量测试里**
  - `dump_now()` 给卡死用：卡死往往比崩溃更难查（没有崩溃点，只有"不动"）
  - 日志 `data/logs/faulthandler.log`：启动标记（时间/pid/python/工作目录）
    + 全线程栈 + 线程数（v25.2.10 定位到"线程数暴涨"是诱因）
  - ⚠️ **写清了局限**：faulthandler **看不到原生子帧**（numpy/Qt/torch 的
    C 层调用）。要定位 DLL 级崩溃还得配 procdump 或 WER 本地 dump ——
    具体命令写在 `crash_guard.WER_HINT` 里。**只靠 faulthandler 会以为
    信息够了。**
  - 取舍：`enable()` 失败**返回空串、不抛异常** —— 它是保护措施不是功能，
    装不上就退化成"和以前一样没有现场"，但不能因为它打不开程序。

### 新增 `tools/measure_coverage.py`：先测量，再定计划
  那份方案最大的问题是**没测量就下结论**（所以才会把行数比当覆盖率）。
  做成工具，一键出真实数据：
      py -3 tools\measure_coverage.py            全量（约 2 分钟）
      py -3 tools\measure_coverage.py --quick    只验证工具能跑
  报告按"**语句多 × 覆盖低**"排序给最该补的清单 —— 不是单纯覆盖低
  （补一个 20 语句的小文件到 100% 没有意义）。

### 实测基线（本次全量 578 用例跑出来的）
    总覆盖率 **41.7%**（18,920 语句，未覆盖 11,036）
      gui                 5,174 语句   53.2%   ← 最高（和直觉相反）
      core                7,215 语句   43.5%
      modules/installed   6,531 语句   30.5%   ← 最低

  **真正的短板是 0% 或极低的大文件**：
      0.0%  core/self_check.py            383 语句 ← 用户会点的"深度自检"
      0.0%  core/realtime/engine.py       184 语句
      0.0%  core/module_server.py         155 语句
      0.0%  modules/installed/voice.py    135 语句
     13.7%  modules/installed/auto_updater.py  366 语句 ← 更新是危险操作
     15.5%  modules/installed/personality.py   549 语句 ← 最大的文件
     32.8%  core/vector_store.py         247 语句

  修正后的补测试目标（按"语句多 × 覆盖低"）：
      self_check 383→70% / personality 549→50% / auto_updater 366→60%
      vector_store 247→70% / realtime/engine 184→60% / module_server 155→60%
  ⚠️ **不建议**为数字补 GUI 点击细节 —— gui 已经 53.2%，是全项目最高的，
     那类手动验证更划算。
  ⚠️ **验收标准不是"到多少个百分点"**，而是"每个会改用户数据的函数，
     都有测试证明它改对了、改坏能回滚"。覆盖率是结果，不是目标。

### CI 那条改成 6 步（初版估 20 分钟，实际约半天）
  ① 建远程仓库并首次推送（`E:\xiaoliu` **没有 remote**）
  ② `pip install -r requirements.txt -i 清华源`
  ③ 补 `data/_schema.json` 和 `data/agreement.json`
     （干净机器实测 426 passed / **11 failed**，失败全是缺这些文件）
  ④ 处理 `modules_repo` 不在 git 里的问题（`check_repo_sync` 会失败）
  ⑤ 必须 **windows-latest** runner（不是 ubuntu —— 用了 Win32 API）
  ⑥ 设 `QT_QPA_PLATFORM=offscreen`

### 方案文档已重写（`小6工程化风险解决方案.txt` v2）
  在原文上加"修订说明"一节，把 3 处错误逐条列出来（不藏着），
  并把验收标准、落地清单、P0 实施记录都补进去。
  **保留初版两个正确判断**：faulthandler 的方向、纯本地日志不上云的隐私立场。
### 测试（新增 `tests/test_crash_guard.py`，14 个用例）
  · enable 建日志、写启动标记、可重复调用、默认路径
  · **坏路径不抛异常**（保护措施不该拦住程序启动）
  · dump_now 真的写出栈 + 记录原因 + 记线程数
  · **接线检查**：crash_guard 必须在 `run.py` 里**早于任何 Qt 导入**；
    `tests/conftest.py` 也必须装
  · `WER_HINT` 里必须有 procdump / LocalDumps / "原生" 字样
    （局限必须写在代码里，否则下次有人拿到栈会以为信息够了）
  ⚠️ 一个测试自己发现的问题：`reset_for_test()` 会清掉**会话级**的开启状态，
     导致后续用例假失败、**而且真崩了就没现场了**。已用 autouse fixture 恢复。
测试 564 → **578 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.14 - 2026-10-14
### 修：打包目录里混着 modules_repo\.git（461 文件 + 私有仓库地址）
做体检时数了一下打包源的文件数，发现**对不上**：

    Get-ChildItem（不含隐藏）   1711
    Get-ChildItem -Force        2172     ← 差 461
    dir /s /b /a-d              2172

差的那些是 **`modules_repo\.git`**。

- **它怎么进去的**：早先用 `robocopy /MIR` 手动同步，
  **只排除了 `__pycache__`、没排除 `.git`**（robocopy 默认连隐藏文件一起拷）。
- **里面有什么**（查过了）：
      ✅ 没有凭据（无 .git-credentials、config 里没有 token）
      ⚠️ **私有仓库地址**：https://gitee.com/cloud-drift/liuyun.git
      ⚠️ git 历史（`objects/` 里可能有已删文件的内容）
      1.79 MB / 461 文件
  这些都不该跟着安装包发出去。
- **为什么正式同步工具也没清掉它**（三个原因叠加，一个比一个隐蔽）：
    ① `copytree(dirs_exist_ok=True)` —— **只增不删**
    ② "要删除"清单靠 `plan()` 比出来，而 `plan()` 的 `walk()`
       **会跳过 `.git`** → 它永远不出现在清单里 → 永远清不掉
    ③ 更糟：`if not (add or upd or dele): return 0` **提前返回**，
       清理那一步**永远跑不到**（加了清理之后才发现）
- **还有一个最隐蔽的**：`shutil.rmtree(p, ignore_errors=True)` **静默失败**。
  git 的 `objects/` 里是**只读文件**，Windows 上 rmtree 删不掉它们，
  而 `ignore_errors=True` **把失败吞了** —— 于是同步**连续两次**报告
  "清掉了 modules_repo/.git"，实际 433 个对象文件一个没少。
  **是测试 `test_real_package_has_no_nested_git` 把它揪出来的。**
- **修法**（四处）：
    · 清理步骤 `purge_forbidden()`：复制后**无条件扫一遍**目标目录，
      不依赖差异比对
    · 把"目标里已有的不该有的东西"**算进差异判断** ——
      这样"已经一致"时也会走到清理
    · 用 `onerror` 回调**先清只读属性再删**；删完**检查是否真的没了**，
      没删掉就如实返回失败（不假装成功）
    · 返回值改成 `(清掉的, 没删掉的)`，删除失败**明确报出来**
- 结果：打包源 **2172 → 1711 文件**，`.git` 已清除。
### 测试（`tests/test_package_sync.py` 20 → 27 个用例）
  新增 4 条专门盯这次的坑：
    · `.git` 必须在 SKIP 里
    · `ignore_patterns(SKIP)` 对**嵌套** `.git` 有效（实测 560 → 49 文件）
    · **只读文件也必须删得掉**（就是最难发现的那个）
    · **删不掉要如实报出来**，不能假装成功
    · **清理必须在提前 return 之前**（源码位置检查 —— 第二版的 bug）
    · 真实打包目录里不许有**任何层级**的 `.git`
测试 557 → **564 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.13 - 2026-10-14
### 修：自动备份把 700 MB 浏览器内核当用户数据备份（backups/ 涨到 1.4 GB）
用户让清理 `backups/` 的 1.4 GB。去看里面是什么，发现**根因是个真 bug**：

    每个备份 **708.3 MB**，其中 **705.6 MB 是 Chromium 内核**
    （data/browsers 的 .pak×446 / .hyb×104 / .dll×14）
    而 data/ 根目录下 70 个文件（真正的用户状态）合计才 **1.8 MB**

    **备份本该只有 2.7 MB —— 膨胀了 262 倍。**

- **根因**：`core/backup.py` 的 `EXCLUDE_DIRS` 里有 `browser_sessions`
  （小），**没有 `browsers`**（705.6 MB）。
  它上面那行注释写着"实测 data 目录 37.9MB，其中只有 2.2MB 是真正需要
  备份的状态" —— **那句话写的时候 `data/browsers` 还不存在**，
  是浏览器功能加进来之后才把它漏进备份范围的。
- **修法**：`EXCLUDE_DIRS` 加上 `browsers`。
  判断标准写进注释了：**能重新下载/重新生成的东西不进备份。**
- **清理**（顺序很重要：**先做正确的小备份 → 验证 → 再删大的**，
  反过来万一备份失败用户就没有安全网了）：
      清理前  backups/  1421.0 MB（2 份 × 708.3 MB）
      先备一份正确的    2.7 MB，逐个核对 chats.db / memory.json /
                        config.json / graph.json / vectors.db /
                        personality.json / episodic_memory.json 都在
      再删旧的          实际释放 **1414.3 MB**
      清理后  backups/     6.7 MB
  **项目总占用 3285.8 MB → 1874.3 MB。**
### 新增：打包源同步工具（`tools/sync_package.py` + `同步打包目录.bat`）
  打包流程是「开发目录 → 复制一份干净的 → 对那份打包」。
  这一步**每次改完代码都要重做** —— 忘了就会把旧代码打进安装包，
  而且**装出来照样能跑**，只是行为是旧的，很难发现。
  比"忘同步"更严重的是**把不该带的带进去**（data/config.json 里是你的
  API Key，进了安装包就是隐私事故）。
  所以做成工具：
      py -3 tools\sync_package.py            同步（先显示要改什么）
      py -3 tools\sync_package.py --dry-run  只看差异
      双击 同步打包目录.bat                    一步到位（带确认）
  每次同步都会跑安全检查：不许有 data/ backups/ optional_libs/
  tests/ tools/ .git/，`config.default.json` 里不许有填好的 Key。
### 测试（新增 2 个文件，33 个用例）
  · `tests/test_backup_scope.py`（13）：大而可再生的目录必须在排除名单；
    **反过来也要防"排除过头"**（users/rules/skills/knowledge 这些
    用户状态不许被排除）；真实项目上算一遍备份体积必须 <50 MB。
  · `tests/test_package_sync.py`（20）：同步清单里不许有 data/ tools/
    等；`config.default.json` 不许有真 Key；`check_safety()` 和 `plan()`
    要真的能查出问题（不是走过场）；真实打包目录必须干净。
  · 负向测试 3 项全抓到：拿掉 browsers 的排除 / 把 users 也排掉 /
    让 `_skip_dir` 不认 `EXCLUDE_DIRS`。
测试 524 → **557 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.12 - 2026-10-13
### 缺依赖时弹框问"要不要现在装"（不用再自己开命令行了）
上一版把提示统一带上了国内源，但用户还是得**自己开命令行、复制粘贴**。
实测很多人到这一步就放弃了 —— 那个功能就白做了。
这一版补上最后一块：**就地装**。

- **`core/error_text.missing_package(text)`** —— 从错误文本里认出缺的是哪个包
  支持四种来源：`No module named 'x'` / `describe()` 产出的人话 /
  提示里的 `pip install` 命令 / 常见包名兜底。
  **认不出就返回空 —— 不猜**（猜错会让用户装一个不相干的包，比不提示更糟）。
  import 名 → pip 名的转换（`cv2`→`opencv-python`、`PIL`→`Pillow`…）。
- **`gui/dep_dialog.py`** —— 弹框：
      需要「识别图片文字」用到的一个组件：opencv-python（约 112 MB）
      走国内源（清华），装进程序的 optional_libs 目录 —— 不会污染系统 Python
      [现在装]  [以后再说]
      装不了？复制命令自己跑          ← 文字链接，不占按钮预算
      ☐ 以后不再问我这个组件
  · 装包在 **QThread** 里跑（pip 装大包要几十秒到几分钟，不能卡住界面）
  · 装完把 `optional_libs` 加进 `sys.path`，**当前进程立刻能用**
  · **报出包的大小** —— torch 491 MB、opencv 112 MB、jedi 0.5 MB。
    不告诉用户就让他点"现在装"，是不负责任的。
- **挂在聊天回复那个时机**（`chat_mixin._maybe_offer_install`）
  回复里出现"缺依赖"就弹。三条防骚扰约束：
    · 同一个包**只问一次**
    · 勾了"不再问我这个组件"就永久跳过（存进 config 的 `dep_never_ask`）
    · 任何异常都吞掉 —— 这只是便利提示，不该影响聊天
- **为什么不做成全自动静默下载**：pip 是从网上拉代码并在你机器上执行，
  该让用户知情；torch 一个包 491 MB，静默下 500 MB 说不过去。
  所以是"**用户点一下** + **告诉他多大** + **可以拒绝**"。
### 测试（新增 tests/test_dep_install.py，28 个用例）
  · 包名识别：9 个该认出来的 + 7 个**不该认出来的**（含"缺少参数""需要先打开"）
  · **明写的 pip 命令本身就是最强信号**：第一版把"信号词闸门"放在最前面，
    结果 `"未检测到语音识别后端。py -3 -m pip install ... faster-whisper"`
    被挡掉了 —— 明明明写了命令，却因为句子里没有闸门认得的词而返回空。
    改成**先匹配明确模式，闸门只留给最后的兜底**。
  · 大小提示：重包要报量级；**小包不能显示成"约 0 MB"**
    （第一版用 %d 格式化，uiautomation 的 0.2 变成了 "0 MB"）
  · 弹框：三个出口齐、复制到剪贴板带国内源、勾选=永久不再问、
    **装包在 QThread 里**（静态检查）、建框本身必须瞬间返回
### 按钮预算 112 → 115（新增的框：2 按钮 + 1 复选）
  理由已写明：这个框**只在"用户刚点的功能因为缺组件而失败"时出现** ——
  用户已经用自然语言表达过诉求了，是程序做失败了。
  这个时刻"说一句"没用（说的就是那个功能本身）。
  「复制命令」已从按钮改成**文字链接**（次要逃生口不占按钮预算）。
### ⚠️ 记录一次没复现的崩溃
  加完新测试后第一次跑全量时出现过一次 access violation
  （退出码 3221225477）。之后连跑 4 次全过（524 passed，0 崩溃），
  单独跑新文件 5 次也全过。**没有复现，也没有定位** —— 如实记录在此。
  如果后面又出现，按 v25.2.10 那条线索查（那次真凶是线程数暴涨）。
测试 496 → **524 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.11 - 2026-10-13
### 缺依赖的提示统一带上国内镜像（原来 17 处里 16 处没带）
用户问"缺依赖会提示吗、会附带国内下载地址吗" —— 去实测，发现做得**很差**：

    含 "pip install" 的用户提示共 17 处
    其中**带国内镜像的：1 处**
    **不带镜像的：16 处**

用户按那些提示跑，会走 PyPI 官方源 —— 国内经常慢到以为卡死
（实测官网直链下 Ollama 只有 0.05 MB/s，PyPI 大包同理）。
用户分不清"慢"和"卡住"，最后就是不装了、功能不用了。
**"最后一公里"就差这一步。**

- **统一入口 `core/error_text.py`**
  · `PIP_MIRROR` 常量（清华源，pip 官方文档推荐的国内镜像之一）
  · `install_cmd(pkg, target="optional_libs")` —— 生成一条**能直接粘**的命令
  · `install_hint(pkg)` —— 上面那条 + **图形界面替代路径**
    （不想碰命令行的人走「设置 → 扩展 → 功能扩展组件」）
  默认 `--target optional_libs`，装进项目目录不污染系统 Python
  （和 install_optional.bat 同一约定：卸载程序时不给系统留一堆包）。
- **改了 9 处硬编码提示**，都改成走统一入口：
  · `modules/multimodal.py`（whisper / opencv ×3）
  · `modules/computer_controller.py`（uiautomation）
  · `modules/voice.py`（faster-whisper）
  · `modules/error_lib.py`（E005 依赖缺失的错误码知识库）
  · `core/realtime/engine.py`（pyaudio）
  · `core/license_core.py`（cryptography）
  · `core/optional_deps.py`（登记表里的"装法"字段）
  · `tools/optional_deps.py`（命令行输出）
- 现在用户看到的提示长这样：
      「识别图片文字」缺一个可选组件（opencv-python），当前没装
      下一步：
          装上它（走国内源，快）：
              py -3 -m pip install --target optional_libs opencv-python \
                  -i https://pypi.tuna.tsinghua.edu.cn/simple
          不想用命令行的话：设置 → 扩展 → 功能扩展组件，找到它点「安装」
### 测试（新增 tests/test_dep_hints.py，13 个用例）
  · `install_cmd` / `install_hint` 必须带镜像、默认装到 optional_libs
  · 常用 6 个可选包逐个验翻译结果带镜像
  · **全项目扫描**：不许再有"面向用户但不带国内源的 pip 提示"（防回弹）
  ⚠️ 扫描器第一版有**两类误报**，都修了：
    ① `core/error_text.py` 的**函数文档里**举了
       `todo = "装上它试试：pip install pyautogui"` 作例子，被当成真提示
       → 改为逐行跟踪三引号状态跳过 docstring
    ② 多行字符串里镜像在**下一行**（辅助函数写法），只看单行会误报
       → 改为拼接后 3 行一起判
  ⚠️ 还抓出我自己批处理脚本的一个 bug：改 `optional_deps.py` 时
     引用了一个**没定义的 `_hint`**（脚本加的辅助叫 `_ih`）。
     跑全量测试才发现（6 个 NameError）。
### 插件仓库已同步重签
  改了 4 个模块文件 -> rebuild_modules_repo（43 个）-> sign_modules（43 条）
  -> check_repo_sync 通过
测试 483 -> **496 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.10 - 2026-10-13
### 定位并修掉测试套件的间歇性进程崩溃 —— 真凶是线程数暴涨
上一版留下一个已知问题：全量跑 pytest 时**约 1/3~3/5 概率整个进程硬崩**
（Windows fatal exception: access violation，退出码 0xC0000005 / 3221225477），
崩点固定在"第一次构造向导"那一步，单独跑那个文件却 100% 正常。

- **真凶：fixture 用了 `scope="function"`，20 个用例就建 20 个向导**
  每个向导配一个 `make_trunk()` 造的 Trunk —— 而
  **`make_trunk` 并不屏蔽 `Trunk.__init__` 里无条件启动的
  `_bg_loop` / `_idle_worker` 两个后台线程**（它们不在 `_BACKGROUND` 名单里）。
  于是 20 个用例 = 20 个 Trunk = **40 个后台线程**。
  改成 `scope="module"`（1 个 Trunk / 2 个线程）后：全量 **4/4 全过，零崩溃**。
- **排查过程（都做过对照实验，不是猜的）**
  · 排除 `test_ollama_pull.py`（排除它照样崩；那文件单独跑 3/3 全过）
  · 排除模块级全局持有向导（改 function 作用域后仍崩 3/5）
  · 排除新加的 `QTimer(self)`（去掉后仍崩 3/3）
  · **二分定位到是"累积"效应**：前缀 18 个测试文件时正常，
    加到第 19 个（`test_mcp_stdio.py`）就崩 —— 说明不是某个文件有毒，
    而是总资源量过了临界点。线程数暴涨正是"累积"的来源。
  · ⚠️ 中途一度把布局测试**并进 `test_gui_smoke.py`**，结果连单跑都崩 ——
    那恰好反证了"是数量问题"（合并后同一个文件里就有 20 个向导）。
- **归位**：布局测试仍并进 `test_gui_smoke.py`（都是 GUI 控件测试，
  同一类东西放一起更合理），只是先把 fixture 改成模块级。
### 顺带修
- `test_gui_smoke.py` 补 `QComboBox` / `QPushButton` / `QLineEdit` 导入
  （合并进来的用例要用）。
- 更正上一版一处说法：当时记的"可能是析构顺序问题"**方向不对**，
  实际是线程数量。CHANGELOG 里留着这段，免得下次又往析构方向查。
- ⚠️ **更正本版一开始的一处记账错误**：刚合并完时记的是"503 个用例"，
  那是**把实验残留的副本文件 `test_aaaa_onboarding_layout.py`
  （改名实验留下、忘了删，+20 个用例）也算进去了**。
  删掉残留后是 **483 个** —— 合并只是把布局测试**换了个文件放**，
  用例总数不变。真实数字以 `pytest tests/ -q --collect-only` 为准。
测试 **483 个用例**（布局测试从独立文件并入 GUI 冒烟，总数不变）。
全量 4 连跑零崩溃；8 个守卫 + 插件仓库一致性全 0。

## v25.2.9 - 2026-10-13
### 修：向导窗口装不下内容（滚动条 + 文字截断）
用户截图报的：对话框里出现**横向 + 纵向滚动条**，说明文字和输入框被截断，
"看着就是坏的"。

- **根因：窗口最小尺寸是我手写的一个猜测值**
  `setMinimumSize(660, 520)`。实测「配置模型」页内容需要 **620 x 628**，
  向导外壳（标题栏 + 页标题 + 底部按钮栏）另占 **22 x 99** ——
  所以窗口至少要 **642 x 727**，而 **520 的高度差了 207 px**。
  负向测试打出来的数字更直白：**最小高 520 小于内容需要 811**。
- **改成按内容现算**：`fit_to_content()` 取各页 `sizeHint()` 的最大值
  加外壳开销。并且：
  · **状态文字变长后重算** —— "没装 Ollama"那四步说明会让页面明显变高，
    不重算就把新加的行直接裁掉（而这几行正是全部指引）
  · **只增不减** —— 用户自己拉大过窗口的话，一次文字更新不该把它缩回去
  · 强制 `layout().activate()` 后再量 —— 刚 `setText` 完就量的话
    `sizeHint` 还是**旧文字**的尺寸，算出来仍然不够
    （实测：宽 580 时那段四步说明需要 280px，只给了 80px）
- **验收覆盖 7 种状态**：连上且有模型 / 没装 Ollama / 有 Ollama 没模型 /
  切服务商 / 安装包下完 / 模型下载中 …… 缩到最小尺寸，全部无滚动条、
  无窄输入框、无截断文字。实测最小尺寸从 660x520 变成 **644x730**。
### 测试
- `tests/test_onboarding_layout.py` 12 → 20 个用例：窗口最小尺寸必须
  按内容算（不是手写值）、每种状态下都不许有滚动条/窄框/截断文字、
  文字变长要跟着变高、窗口不许被缩回去。
- 负向测试 3 项全抓到（禁用 `fit_to_content` / 改回手写 660x520 /
  去掉状态更新后的重算）。
  ⚠️ **前两次尝试是无效的**：用 PowerShell here-string 做字符串替换，
  而它是 `\r\n`、源文件是 `\n` —— 替换根本没生效却仍打印"已还原"，
  看起来像"测试没抓到"，其实代码没被改过。
  改用 Python 改文件后三项全部正常抓到。
### ⚠️ 一处检测方法用错（记下来免得再犯）
  第一版判断"文字有没有被切"用的是 `QLabel.sizeHint().height()`，
  结果**误报**了 `lbl_provider_tip`（要100 有40），白排查一轮。
  自动换行的 QLabel 必须用 **`heightForWidth(实际宽度)`** ——
  `sizeHint()` 给的是"首选宽度下的高度"。
  后来加了对照组（故意把窗口压到 300x260）确认新方法**确实能**发现被切。
测试 475 → **483 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.8 - 2026-10-13
### 模型也改成一键下载（带进度）—— 第 4 步不用再开命令行了
对标同类程序的最后一条差距。原来那一步要求用户：
按 `Win+R` → 输 `cmd` → 粘 `ollama run qwen2.5:3b` → 看着黑窗口 →
**自己判断什么时候算下完**。同样劝退，而且下错/下不完用户也不知道。

- **⬇️ 下载模型（用 Ollama 的 /api/pull 流式接口）**
  点一下就拉，带进度条、速度、可取消。状态实时翻译成中文：
  「正在读取清单…」→「正在下载…」→「正在校验文件…」→「正在写入…」→「下载完成」。
  下完**自动刷一次模型列表**，不用再点「重新检测」。
  取消**不会白下** —— Ollama 自己管理 blob 缓存，下次拉同一个模型接着用
  （所以中断时故意**不删**已下好的层）。
- **复用同一套进度条和取消按钮**（两种下载互斥，不会同时进行），
  所以只多了一个按钮，没有多出一块进度区。
- 引导文案第 4 步从"开命令行跑命令"改成"点「⬇️ 下载模型」"。
- 使用说明-小白版.txt 同步。

### ⚠️ 本机没有 Ollama 可测，所以用**模拟服务**验
这台机器实测**没装 Ollama**（`Downloads` 里倒躺着一个 1497.5 MB 的安装包）。
所以 `/api/pull` 这条路的验证方式是：起一个本地 HTTP 服务，
按**官方文档的 NDJSON 格式**吐数据，验解析与进度逻辑。
这样反而能精确构造真实环境很难复现的情况（校验阶段没有 total、
中途返回 error、坏行混进来、流结束但没有 success）。

顺带**独立核对了安装包大小**：我实测的 `APPROX_MB = 1509 MB`，
用户手动下那个文件是 **1497.5 MB**（9-24 的版本），**偏差 0.8%** ——
说明实测值是准的。

### 测试（新增 tests/test_ollama_pull.py，8 个用例）—— **一次抓出 3 个真 bug**
1. 🔴 **`"downloading"` 状态没有中文翻译** —— 其余几条都翻了，就这条漏了，
   进度条上会直接把英文 `downloading` 甩给用户。
2. 🔴 **坏行会崩掉整次下载** —— 我只挡了"JSON 解析失败"，
   但**解析成功不等于拿到字典**：合法 JSON 也可能是字符串/数字/数组
   （测试里那个 `"这不是 JSON"` 字符串，`json.dumps` 之后就是合法的
   JSON 字符串），下一句 `d.get()` 直接 AttributeError。
3. 🔴 **「正在校验文件…」和「正在写入…」永远不显示** ——
   原来的节流是"有 total 就报，没 total 要等 0.4 秒"，
   而这两帧既没有 total、又瞬间就过去了，每次都被窗口吃掉。
   用户看到的是**进度条卡在 99% 然后突然完成**。
   改成**状态一变就报**，只对同一状态内部节流。

其余用例：请求体必须是 `{"name":…,"stream":true}`、`{"error":…}` 要如实报、
取消能真中断、Ollama 没跑时给可读错误不抛、
**流正常结束但没收到 success 时不能说"完成"**（要提示去重新检测 ——
真环境里网络中断就是这样，直接算成功用户会以为下好了）。

按钮 111 → 112（向导 6 → 7）。这个"说一句"替代不了的原因和另外两个一样：
它面对的是**程序还没配好模型、根本答不了话**的场景。
测试 467 → **475 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.7 - 2026-10-13
### Ollama 一键下载安装（带进度）+ 云端服务商一键填入
继续对标 `E:\程序代码编辑器`，补上它最好用的两条。**下载源全部实测过。**

- **⬇️ Ollama 一键下载安装（不用再自己开浏览器找）**
  原来只给一句"去官网下载 Ollama，装完执行 ollama run xxx"，
  用户得自己开浏览器 → 搜官网 → 下 1.5GB → 装 → 开命令行。
  现在向导里一键完成：**自动挑下载源 → 带进度条 → 下完变「📦 立即安装」**。
  实测数据（本机 2026-10-13，探源只取 1KB、测速只取 8MB）：

  | 源 | 响应 | 吞吐 | 下完 1.5GB |
  |---|---|---|---|
  | **gh-proxy.com 加速** | **0.49~0.75 秒** | **6.46~18.21 MB/s** | **约 1.4~4 分钟** |
  | ghproxy.net 加速 | 2.29 秒 | — | — |
  | ghfast.top 加速 | 2.64 秒 | — | — |
  | GitHub Releases | 2.26 秒 | 0.08 MB/s | 约 5 小时 |
  | Ollama 官网 | 3.43 秒 | 0.05 MB/s | **约 8 小时** |

  **官网比加速源慢 130 倍以上** —— 所以默认走加速源，官网留着兜底
  （第三方加速随时可能挂，不能只留一条路）。
  所有源都用 `/releases/latest/download/` 这种**不带版本号**的地址，
  官方发版也不会 404（有测试钉住这条）。
  ⚠️ **安装包实测 1509 MB**（不是几百 MB —— 现在的 Ollama 把 GPU 运行库
  打进去了）。这个数必须如实写，写小了用户会以为下完了其实没有。
  ⚠️ **不静默安装**：只负责把安装程序拉起来，装到哪、要不要开机自启
  交给系统安装向导决定（替用户全自动做完是越权，而且很多人想改安装盘）。
  取消下载会清掉 `.part`，**不会留下半个 exe**（留半个最坏：用户双击它
  得到"安装程序已损坏"，完全不知道是自己上次取消造成的）。
- **云端服务商一键填入（不用自己抄 URL）**
  原来只有一句"以智谱 GLM 为例，地址填：https://…"，用户得把 URL
  抄进输入框 —— 抄错一个字符就是 404，很难查。
  现在多了「服务商」下拉框，选一家自动填好**地址 + 模型名**，
  并给出该家的 Key 申请入口。
  **5 家地址全部实测**（发不带 Key 的请求，返回 401 = 地址有效且需鉴权）：
  智谱 GLM / DeepSeek / 通义千问 / 月之暗面 Kimi / 硅基流动。
  ⚠️ **OpenAI 实测连接超时**（国内直连不通），所以**没收进预设** ——
  收进来只会让用户白填一次再失败。
  ⚠️ 修了一个自相矛盾：下拉框默认停在第一项（智谱 GLM），
  而下面的地址可能是用户已保存的别家 —— 界面会显示"选了智谱但地址不对"。
  现在 `_prefill()` 会按已保存地址**反查服务商并同步下拉框**，
  反查不到就落到「自定义」并把已填内容原样留着（不覆盖用户改过的值）。
  （踩坑：`setCurrentText` 选**同一个值**不触发信号，不能指望回调帮忙同步。）
- **引导文案同步更新**：第 1 步从"去官网找"变成"点上面的按钮"，
  五步写到能照着做（装完在哪、跑什么命令、多大、回来点哪）。
- **使用说明-小白版.txt 同步更新**：两条路线都改成按新界面写，
  并写明各家 Key 申请地址、以及"只想填域名会 404"这个坑。
### 测试
- 新增 `tests/test_ollama_install.py`（15 个用例）：源列表非空且指向
  `OllamaSetup.exe`、**地址里不能带版本号**、必须有国内加速源且排在前面、
  官网要留兜底、安装包大小要写实测值、挑不到源时返回 None 不抛、
  取消后不留半个文件、坏文件/没下完的安装包不许被拉起来、
  云端地址必须是 `chat/completions` 完整接口地址、预设里不许有连不上的服务商。
- 按钮 109 → 111（向导 4 → 6）。已经把原设计的 3 个（下载/安装/取消）
  **合并成 2 个**（下载与安装共用一个按钮，按状态换动作）。
  剩下两个"说一句"替代不了：一键下载面对的是**程序还没配好模型、
  根本答不了话**的场景；取消下载是因为 **1.5GB 的下载不给取消键就是陷阱**
  （唯一出路是杀掉程序，下次还得从头再来）。
测试 452 → **467 个用例**，全通过；8 个守卫 + 插件仓库一致性全 0。

## v25.2.6 - 2026-10-13
### 对标《程序代码编辑器》：修引导页布局 + 补小白使用说明
对照 `E:\程序代码编辑器`（同类程序）的安装导向与教程，找出并补上小6 的差距。

- **🐛 修用户截图报的布局问题（首次设置向导 → 配置模型页）**
  现象：本地 Ollama 那行的「地址」「模型」输入框被压成几十像素，
  文字截成 `http://localhost:...` / `qwen2.5-coder...` 两条残影，
  **既没法核对也没法改**。
  根因：那一行塞了 **4 个控件**（`地址：|输入框|模型：|输入框`），
  两个输入框都设了 `stretch=1`，容器一窄就双双被压到最小宽度。
  云端那边本来就是拆两行的，**本地这边漏了**。
  修法：本地那行也拆成两行（地址一行、模型一行），每个输入框加
  `setMinimumWidth(240)`；云端把 `模型 + Key` 也从一行拆成两行。
  实测各尺寸下所有输入框都 >= 240 px。
- **模型框改成「可编辑下拉框」—— 检测到就自动填进去**
  原来是个普通输入框，用户得照着文档手打模型名。
  **打错一个字符，表现就是"发消息没反应"**，很难自己查出来。
  现在：连上 Ollama 后把已有模型自动列进下拉框，优先保留用户已选的那个；
  仍然是可编辑的，自己训的模型名照样能填。
  实测本机自动填入 4 个：`qwen2.5-coder-1.5b-cn:latest` /
  `xiao6-qwen3.5-4b:latest` / `qwen3.5:4b` / `nomic-embed-text:latest`。
- **"没装 Ollama"从一句话改成能照着做的四步**
  原来只有一句"没装的话：下载 Ollama，装完执行 ollama run xxx"。
  对比同类程序：它们把下载做成了**程序内一键完成 + 进度条**。
  小6 这边暂时还是引导用户自己去官网 —— 那就至少写清楚：
  下载地址 / 托盘会有图标 / `Win+R` → `cmd` → 粘哪一行 /
  约 2GB 要等进度条 / **装完回到哪一步点「重新检测」**。
- **补一份面向用户的小白说明**（`使用说明-小白版.txt`，13 节）
  项目里原本**只有 700 行的《架构与功能说明》** —— 那是给改代码的人看的，
  用户没法从里面查到"怎么配模型""某个功能在哪个菜单""出问题怎么查"。
  新说明对齐同类程序的写法：按"点哪个按钮会发生什么"写，含
  常见问题 Q1-Q8、目录速查、以及"换电脑不用拷 1.7GB"这类实用提醒。
  入口：首次向导欢迎页 + 「设置 → 系统 → 📖 使用说明（小白版）」。
### 测试
- 新增 `tests/test_onboarding_layout.py`（12 个用例）：各尺寸下输入框宽度、
  地址与模型必须各占一行、模型框是可编辑下拉框、检测到的模型要自动填入、
  已选模型不能被刷新冲掉、连不上时步骤要可照做。
- 负向测试 3 项全抓到：塞回一行 / 去掉最小宽度 / 换回普通输入框。
  ⚠️ 其中"去掉最小宽度"一开始**抓不到** —— 拆成两行后它成了冗余防御，
  正常尺寸下测不出差别。补了一条只读 `minimumWidth()` 的用例让它可测
  （第一版那条折腾 resize/setFixedWidth，把控件状态搞乱、基线自己就挂了）。
- ⚠️ 新测试一度让 **pytest 整体硬崩**（`0xC0000005` access violation，
  跑到 63% 直接没输出）：向导 `_prefill()` 会起 `onboarding-probe`
  线程去 urllib 请求 Ollama，测试跑完时 daemon 线程还在跑，
  解释器拆除阶段撞上它。修法：fixture 里把异步探测强制走同步分支。
- 按钮预算 108 → 109（`system_dialog` 6 → 7）。这个入口"说一句"替代不了 ——
  它正是给**还不会用 / 模型还没配好、程序根本答不了话**的人看的。
测试 440 → **452 个用例**，全通过。

## v25.2.5 - 2026-10-13
### 补欠账 1-8：测试欠账、清理、文档核对、加密安全、静默审计、减轻分发
**功能零增减。分发从 3.2 GB 可压到约 66 MB。**

- **#1 补我自己的两笔测试欠账**
  `tool_presets`（工具模式预设）和 `module_map`（调用边扫描）都是我这轮新写的
  关键逻辑，当时只用临时脚本验过就完事 —— 而这一整轮我一直在批评"写好了没人验"。
  补 36 个用例。顺带改进扫描输出：`tool_caller` 的 9 条内置工具表出边
  以前标成 `?`，现在标"按表分发"。
  ⚠️ 负向测试挖出我测试里的盲区：`test_default_preset_is_all` 读的是**运行时值**
  （已持久化在 rules.json），所以**改源码默认值它发现不了** ——
  后果是"老用户不受影响，新用户一装就是错的模式"。补了 AST 直查源码默认值。
- **#2 清理 data/ 一次性目录与孤儿文件**
  ⚠️ 原计划定为"零风险"，实际**不是**：`_trash_20261010` 里装的是
  **真实数据备份**（chats.db / memory.json / graph.json 快照），不是垃圾。
  改成**先打包留档再删**：`backups/cleanup_20261014_101700.zip`（129 文件 / 377.6 KB）。
  另处理 10 个孤儿数据文件（有内容但代码里**没有任何写入方**，
  留着会让人以为对应功能还在工作）。回收 1.13 MB。
- **#3 核对 35 KB 的规则文档**
  结论：**它不是过时，是性质被搞错了** —— 自称"文档为唯一事实源"，
  实际是 v2.0 的设计稿。点名列出对不上的：注册模块 43→**67**；
  别名 `web_learner→proactive_learner` **早已删除**；
  C 组 8 条标注"建议待落地"，实际**都已有实现**。
  头部加状态声明 + 核对表 + 5 个真事实源；正文那行错的别名一并修正。
- **#4 给加密与敏感信息加测试 —— 一次挖出 6 个真问题**
  🔴 **安全问题**：`sensitive_detector.detect()` 返回
  `{"value": m.group()[:20] + "..."}` —— 把密钥**前 20 字符原样带出来**。
  这个结果一旦进日志/发给模型，"检测敏感信息"这个动作本身就成了泄露渠道。
  改成只返回类型/长度/位置偏移。
  🔴 **密码输错报的是"编码错误"**：`import_encrypted` 把「AES 解密失败」和
  「没装 cryptography」混在同一个 except 里，于是密码错也掉进 XOR 回退，
  解出乱码报 UnicodeDecodeError。现在分开判断，密码错明确说"密码不对"。
  另修：导出坏行静默、写不可写路径抛穿、短串脱敏形同虚设。
- **#5 按"用户路径"审静默 except**
  357 处按文件挑没意义，改成按路径圈定（聊天回复 51 / 启动 17 / 界面 12 /
  数据写入 10 = 90 处）。实审了数据写入那 10 处：
  `vector_store` 的 Chroma 同步失败改成"记一次日志 + 首次提示"
  （完全静默会让向量检索悄悄退化成关键词检索）；
  `config.py` 迁移后回写失败改成记 warn（原来用户看到"改了设置重启就没了"，
  日志里什么都没有）。**357 → 354 处**，基线已下调。
- **#6 可选依赖的"状态可查"（省 1 GB）**
  查下来小6 的"按需安装"**早就做好了**（requirements-optional.txt 按功能分组，
  注释里还记着 av<19、huggingface-hub<2、torch 与 PyQt5 的 DLL 冲突这些硬坑）。
  真正缺的是"按需**知道**"：`optional_libs/` 装着 1050.7 MB / 21960 文件，
  却没有任何地方记录装了什么、什么版本。
  新增 `core/optional_deps.py` + `tools/optional_deps.py`：
  功能→依赖映射、扫描（**不 import 重包**）、登记表 `data/optional_deps.json`
  （DSH `runtime.json` 的对应物）、分发建议。
- **#7 浏览器内核按需下载的提示（省 705 MB）**
  `data/browsers` 实测 705.6 MB，本就不该随程序分发。
  缺的是"没装时给什么提示"—— 以前用户看到 playwright 原始报错被截到 80 字：
  `Executable doesn't exist at ...chrome-w`。
  新增 `Browser.chromium_info()`：说清这是正常的、怎么装、
  以及 `PLAYWRIGHT_BROWSERS_PATH` 那个坑（装错地方就会找不到）。
  ⚠️ 顺带发现**命令会被 80 字截断**（"…install chr"），修法是把命令放最前面。
- **#8 下载校验：核对结果是"已经有了"**
  **小6 早就有，而且比 DSH 的 payloadDigest 更强**（DSH 是未签名哈希，
  小6 是 sha256 + RSA 验签；没登记默认拒绝）。
  缺的不是保护，是**没有任何测试钉住它** —— 一次重构就可能悄悄去掉，
  而且去掉后一切照常工作（只是不再验了）。
  补 12 个用例。
  ⚠️ 负向测试抓出我**两处太弱的断言**：
  ① 只断言字符串存在 → 而 plugin_market 有**两条安装路径**，
     改掉一条另一条还在 → 照样通过。**只钉一条路径等于另一条没保护。**
  ② 用"数 `verify_manifest` 出现次数" → 改成 `if False and ...` 短路后
     字符串还在、次数没变 → 照样通过。**数次数 ≠ 数"真的在把关"。**
### 修复
- 设置里 4 个按钮点不动（**我改出来的回归**）：重构 `_panel_commands` 时把键名
  改清楚了（系统→系统自检、插件→插件市场、日志→日志中心、MCP→MCP市场），
  但没同步设置窗口 —— 它是按名字查表的，查不到就 `setEnabled(False)`
  **静默置灰**（点不动、无报错、无日志）。
  根因是**显示名和查表键用了同一个字符串**。已解耦（`_open_btn(..., key=)`）
  并把"缺的是哪个键"写进 tooltip。新增 `tests/test_settings_entries.py`。
  ⚠️ 为什么这一轮加的测试全没抓到：`test_gui_smoke` 只验"能构造、有子控件"
  （置灰的按钮照样算数）；`test_ui_responsiveness` 直接调 `win.sys_dialog()`
  **绕过了设置里那个按钮**；`_open_btn` 又是优雅降级不抛异常。
### 测试
285 → **440 个用例**，全通过；8 个守卫退出码全 0。

## v25.2.4 - 2026-10-13
### 产品级加固（第二轮 1-5 项，功能冻结）
- **GUI 冒烟测试**（tests/test_gui_smoke.py，43 个用例，3.8 秒）
  界面是用户 100% 的接触面，却最容易在重构中悄悄坏掉：改个 import、
  重命名个控件，程序照样启动，只有点到那个窗口才崩。
  这一轮我自己就犯过两次（system_dialog 死 import、main_window 漏
  Qt/QShortcut）。覆盖：类式 16 + 部件 3 + 线程 8 + QObject 2 +
  高亮器/编辑器 2 + 函数式 show_xxx_dialog 11 + 主窗口装配 1。
  ⚠️ 我一开始报的"GUI 覆盖 3%"是**错的** —— 那是用"类名是否出现在测试
  源码"量的，但本项目大量界面是**函数式**（show_xxx_dialog），
  类名根本不出现。真实情况：类式 32 个 + 函数式 13 个。
- **日志轮转（两条路统一）+ 日志中心只读尾部**
  实测项目里两条写日志的路，同一件事两个实现：
  app.log（core/logger.py）有轮转 ✅、trunk.log（core/trunk.py）
  open(path,"a") 直接追加、**没有任何上限** ❌（已 914 KB 且一直长）。
  而 gui/log_dialog.py 用 `f.readlines()` **读整个文件**再切最后 300 行。
  → 抽出公共 core.logger.append_line / rotate_if_needed，trunk 改走它；
    日志中心改用 deque(maxlen=tail) 边读边丢，内存恒定。
  ⚠️ 写"连着转两次"的测试时**抓出我自己写的一个 bug**：keep=1 时
    后移各代的循环里 src 和 dst 是同一路径，先 remove 再 replace 必然
    失败 —— 后果是**每隔一次轮转就失败，并把上一代日志删掉**。
    连续写入看起来正常只是因为成功/失败交替。
- **静默失败棘轮**（tools/check_silent.py）
  全项目 500+ 处 `except Exception: pass`。存量**不能批量改**（大部分是
  合理的最尽力路径），但新增必须拦住 —— 静默失败正是这一轮修掉两个
  真问题的根源。基线 357 处 / 103 文件；"该忍"的可标
  `# 静默是故意的：<为什么>` 或 `# noqa: silent`。
  挂进 pre-commit（AST 扫描，0.5 秒）。
  **它当天就抓到了我自己新加的 2 处静默 except**，逼我写明理由。
- **数据文件版本登记**（core/data_schema.py）
  这一轮修的两个真问题根子都是"格式假设 + 没有版本校验"。
  45 个数据文件逐个版本化是过度设计，所以只做最值钱的两件事：
    ① **降级保护**：数据是更新版本写的 → 警告"先别改它，升级程序再动"，
       而不是按旧格式静默误读甚至覆盖回去
    ② 给将来的迁移留挂点
  登记 8 个有真实格式假设的文件，落盘 data/_schema.json（单独文件，
  不往 jsonl 里塞特殊行 —— 我们刚为"坏行保留"改过 auto_organize）。
  已接进已有的深度自检（不新增界面入口）。
### 修复
- 修掉一个我自己写的**脆弱测试**：test_last_error_expires 用 within=0
  判定过期，而判定是 `elapsed > 0`，记录和查询落在同一时钟刻度时
  `0 > 0` 为假 → 偶发失败（全量跑挂一次、单跑又过）。改成负窗口，
  连跑 20 次全过。
- check_silent 基线里 per_file 一开始存的是行号列表，比较时变成
  `int > list` 直接 TypeError。改成存数量。
### 踩坑记录（都写进代码注释了）
- **不要 patch QDialog.show**：为识别非模态界面把 show 换成记录器再
  赋值恢复，结果 `TypeError: show(self): first argument of unbound method
  must have type 'QWidget'` 污染了后面所有用例（test_ui_responsiveness
  直接挂 6 个）。原因：show 从 QWidget 继承，赋值会在 QDialog 上造副本。
  改用**返回值**识别非模态界面。
- 12 个函数式对话框里 8 个把命令**挂到超时**：它们结尾是 d.exec_()
  （模态等用户关窗口），测试里没人关。修法：桩掉 QDialog.exec_，
  并借它记录哪些窗口走到了 exec_。
- 第一次负向测试改的是 gui/system_dialog.py，但那个文件**不在覆盖列表**里
  （它是 (self) 签名的混入方法）→ 没报错是必然的，属于**假阴性**。
- 断言日志中心"不再 readlines"时，第一版用文本匹配，结果匹配到了
  **我自己写的解释性注释** → 改用 AST 找真实调用。

测试 325 -> 348 个用例，全通过；8 个守卫（含新棘轮）退出码全 0

## v25.2.3 - 2026-10-13
### 产品级加固（方向 2 + 3，功能冻结）
- **逐个判断"自己吞异常"的能力方法**（审计出 10 条，该报的报、该忍的忍）
  🔴 **最重的一条是真·数据丢失**：memory_organizer.auto_organize
     读记忆卡时 `except: pass` 跳过解析失败的行，写回却是
     `open(path, "w")` **全量覆盖** —— 那几行被**永久删除**。
     更隐蔽的是返回值：`"原始": len(cards)` 报的是**解析成功的条数**，
     不是文件行数。于是 {"原始": 5, "保留": 5} 看起来"一条没丢"，
     文件里却可能有 8 行 —— **数据丢了，报告还说没事。**
     修法：坏行**原样保留**、报出坏行数与明细、"原始"改为文件真实行数、
     写回改成临时文件 + os.replace。
  🔴 **第二条比"静默"更糟**：startup_optimizer.precompile
     `py_compile.compile(f, doraise=False)` **根本不抛异常**（把 SyntaxError
     打到 stderr 就返回 None），于是 `except` 永不触发、`count += 1`
     **把编不过的文件也算成成功**（实测：正常文件+语法错文件 -> {'预编译文件': 2}）。
     改成 doraise=True 才真的能捕获并报告。
  另 5 处（growth_report / check_conflicts / dream_system / mood_report /
  knowledge_qa 两处）：跳过坏行本身是对的，**不报跳过数是错的** ——
  用户看到"最近 7 天 0 条记录"分不清"真的没有"还是"全被跳过了"。
  2 处经审计判定**该忍**并写明理由（防止以后被误当 bug 改掉）：
  gpu_detector.detect（没有 N 卡是正常结果）、crash_export 写提示文件
  （尽力而为，信息已在返回值里）。
- **错误信息面向用户化**（新增 core/error_text.py）
  原来报错长这样：
     「识别图片文字」执行出错：TypeError: OCR.available() takes 1 positional
     argument but 2 were given
  对开发者有用，对用户没用 —— 既不知道发生了什么，也不知道该做什么。
  现在翻译成"**人话 + 下一步**"，原文不丢：
     「识别图片文字」这个功能和当前版本对不上（内部接口不一致）
     下一步：多半是模块版本旧了 —— 到插件市场看看有没有更新
     （技术细节：TypeError: OCR.available() takes 1 positional ...）
  覆盖 20 类常见错误：缺组件/连不上/超时/找不到文件/没权限/数据坏了/
  接口不一致/内存不足/证书/限流等。
  **拿不准的不许瞎猜** —— 没见过的错误保留原文，不编造建议。
  接进两处：trunk.call 的异常分支、能力分发的失败信息。
### 修复
- core/version.py 的 __build_date__ 之前被我误写成 2026-10-14
  （系统时间是 10-13）。原因是 PowerShell 测试里的 `git checkout --`
  把索引里的旧内容恢复回来、覆盖了日期修正 —— 已改回并核对三处一致。
### 测试
  253 -> **285** 个用例，全通过
  新增 tests/test_memory_safety.py（8，数据安全回归）、
  tests/test_silent_data.py（7，"跳过坏数据要报数"）、
  tests/test_error_text.py（14，错误翻译）
  三个文件都做了负向测试：去掉修复后对应用例立刻失败

## v25.2.2 - 2026-10-13
### 产品级加固（功能冻结：不加功能、不减功能，只提高可靠性与可验证性）
- **新增能力冒烟测试**（tests/test_capabilities.py，85 个用例）
  实测 44 条能力里原来**只有 2 条**被任何测试提到过（5%），
  后果已经吃到过两次：check_conflicts 的 `open(...)[-200:]` 必然 TypeError
  （功能从来没成功过）、「采纳建议」读占位符去搜（从来没工作过）——
  共同点都是"写好了没人跑过"。现在分三层验：
      结构（44 条全查）  模块能加载 / 方法存在 / 参数传得进去
      真调用（22 条）    离线只读的**真跑一次**，返回不能是错误
      安全分级（12 条）  会改数据的必须标 confirm、长任务必须标 bg
  并做了负向测试：故意改错方法名 / 去掉 confirm / 去掉 bg / 删 hints，
  四种破坏全部被抓到，还原后回到全绿。
- **@safe 的错误不再静默**（core/safe.py + tool_caller._explain_none）
  @safe 出错时返回 None（日志里有记录），但调用方**无法区分**
  "这方法本来就返回空"和"出错了"。实测吃过亏：ocr_available() 被多传一个
  参数，TypeError 变成 None，现象上就是"这功能没反应"。
  现在按函数名/限定名记下最近一次错误（限定名是为了防 stats/run 这类
  同名方法串台），分发器据此把静默的 None 变成明确的失败信息。
- **导出类不再"看起来成功"**
  · migration.export：写不进 zip 的文件原来 `except: pass` 静默跳过，
    最后照样返回 {"ok": True} —— **这比导出失败更危险**（用户以为备份完整，
    换电脑才发现少数据）。现在报告已打包数 + 跳过数与原因。
  · crash_export：脱敏原来靠硬编码 3 个键名，**将来加了新密钥就会静默
    漏出去**，而崩溃包恰恰是发给别人排查的。改成模式匹配（键名含
    key/secret/token/password/webhook/credential 就脱）+ 名单兜底，
    并报告 config 是否成功进包。
- **测试卫生检查**（tests/test_test_hygiene.py）
  防止"建 Trunk 不屏蔽后台"这个**已经咬过两次**的坑：
  Trunk() 构造 3 秒后会连 config.json 里的 MCP 服务器，
  每个实例拉起 4 个子进程且会累积，会污染断言全局计数的用例。
  光写文档拦不住（conftest 里记着，我还是踩了），所以做机器检查。
### 修掉我自己引入的三个问题
- `max_tokens_reply` 因键名含 "token" 被误脱敏 —— 崩溃包反而少了真实设置。
  改为"值是数字就不当密钥"（密钥不可能是纯数字）。
- 卫生检查器用正则时把**自己 docstring 里解释这个坑的话**当成了调用
  （自己抓自己），改用 AST 精确定位真实调用点。
- 同一检查器读文件没用 utf-8-sig，带 BOM 的文件 ast.parse 失败后被
  **静默 continue** —— 负向测试发现"一个真带裸 Trunk 的探针被跳过了"。
  现在解析不了会明确报错，不再静默跳过。
### 测试
  152 -> **253** 个用例，全通过；六个守卫退出码全 0
  迁移包测试改用临时小目录，耗时 43s -> 1.3s（覆盖不变）

## v25.2.1 - 2026-10-13
### 整理（产品升级向：不新增功能，只让已有的变诚实）
- **模块星图的调用边扫描修好**：原来只认 `trunk.call("字面量","字面量")`，
  导致一批**正在跑**的模块在图上看不到调用者（像孤儿）。现在承认五种形态：
  字面量 / 映射表驱动 / 直接 import / 别名 / 能力注册表驱动。
  实测边数 9 -> 50；agent_coder、agent_analyst、agent_planner、plugin_signer
  从此能看出谁在用它们
- **退役 5 个确认无调用路径的模块**（源码保留在 modules/retired/）：
  active_learning（唯一引用是个全项目无人使用的历史别名）
  graph_db（自述 P2-19 旧实现，已由 knowledge_graph 取代；而且它构造函数
  收的是路径不是 trunk，本来就永远加载失败）
  reasoning_engine（外部零引用，职责与 task_loop 重叠）
  skill_distill（外部零引用，与 skill_capture 是同一件事的两个真相）
  empathy（见下）
- **接通 2 个写好了却没人用的模块**（只声明已有方法，不写新逻辑）：
  knowledge_qa    -> kqa_ask / kqa_list / kqa_search / kqa_add / kqa_stats
  startup_optimizer -> startup_precompile
  LAZY_MAP 72 -> 67，能力注册表 38 -> 44，工具表 57 -> 63
- **清单瘦身**：modules_repo 从 47 条降到 43 条（退役的不再登记 ——
  留着会"装了也不会被加载"），重新 RSA 签名，漂移 0
### 发现
- **smart_router 的路由结果被丢掉了**：它有 8 条意图→模块映射，
  但 core/trunk.py 只消费 `意图 == "task"` 这一个分支，
  **全项目没有任何地方读 `r["模块"]`** —— 包括 empathy 在内的 7 条映射
  算完就丢。empathy 因此实际到不了（这是它被退役的真实原因）。
  接入它属于行为变更，不在本次"只整理"的范围，故只记录不实施。
- 静态可达性分析在这个项目上不可靠：为了得到可信数字，先后踩了
  5 个度量缺陷（把登记表当调用方 / LAZY_MAP 元组取错下标 /
  漏 self.call / 漏直接 import / 没处理 stt-voice 这类别名）。
  结论是**静态扫描只能当下界**，最终仍需人工逐个确认。
### 修复
- core/module_map.py 里"模块之间没有直接 import"那句注释已过时
  （plugin_market 就直接 `from core.plugin_signer import PluginSigner`），已更正

## v25.2.0 - 2026-10-13
### 新增
- **能力注册表**：core/module_caps.py 把"能力从哪来"统一成两个来源 ——
  插件模块里声明的 TOOLS（运行时**从源码读**，源码哈希才是被 RSA 签名覆盖的）
  和 core 侧集中声明（core/core_caps.py）。注册表 38 条能力
- **命令面板 Ctrl+K**：一个搜索框找所有能力和面板（能力 38 + 面板 19 = 57 条）。
  取代原来"实用工具"面板那 24 个按钮
- **工具模式预设**：日常 / 干活 / 编程 / 维护，按场景收窄给模型看的工具范围
  （全部 57 -> 编程 10），默认"全部"= 不过滤
- **长任务后台执行**：能力可标 bg: True，聊天触发时转后台线程，不再卡住回复
  （自动更新闭环、任务闭环、学习、辩论、模型投票、导出打包）
- 能力增加安全分级：readonly / confirm / danger / bg / hints
### 修复
- **零参数方法被硬塞空字符串**：`list_pending()` 被调成 `list_pending("")`
  -> TypeError，还被 @safe 吞成静默返回 None（最难查的那种）
- **工具分发器只传第一个参数**：多参数能力全部残废，现按签名决定 kwargs 还是首参
- **memory_organizer.check_conflicts 从来没成功过**：`open(...)[-200:]`
  对文件对象切片必然 TypeError
- **「采纳建议」按钮一直是坏的**：读的是占位符"🤔 正在生成建议..."（全项目
  只有一处 setPlainText，之后再没人填过），等于拿这句占位符去网上搜
- **语音输入在子线程里碰 Qt 控件**：注释写着"回到主线程更新UI"其实没回，
  会随机崩。改为 emit 信号、槽在 GUI 线程执行
- **能力声明曾不受签名保护**：RSA 签名覆盖的是模块文件 sha256，
  不覆盖清单条目字段 —— 故运行时改为从源码读 TOOLS
### 架构调整
- **按钮 114 -> 108**：撤掉"实用工具"面板 24 个循环创建的按钮（改命令面板）、
  系统面板 4 个"点一下就调一个能力"的按钮、日志中心 2 个重复入口
- 撤按钮前后先声明能力再撤，保证"撤按钮 != 删功能"
- **新增 5 个防回弹守卫**（挂进 check.bat，共 6 步）：
  check_shapes（结构漂移）/ check_version（版本号）/ check_buttons（按钮预算）
  / check_tools（提示词预算）/ check_threads（子线程不许碰控件）
- 清掉因撤按钮而变成死代码的 export_logs / export_data（与注册表重复实现）

## v25.1.6 - 2026-10-13
### 新增
- 浏览器自动化修活：基于 Playwright 的 DOM 级控制（打开/点击/输入/读页面文字/
  批量填表/登录保持/新标签/滚动/截图）。此前代码写了但跑不起来 ——
  chromium 二进制没下载，且全项目没有一处调用它
- 开发者文件工具三件套：fs_read（带行号、可只读一段）/ fs_search（搜内容）/
  fs_edit（精确替换，原文须唯一，改前自动备份）
- UI 元素树（uiautomation）：ui_windows / ui_find / ui_dump / ui_click / ui_type，
  GUI 操作从"盲点坐标"升级到"按控件名操作"
- 命令执行 shell：28 条白名单命令 + 默认关闭 + 每条弹窗确认 + 拒绝串联重定向；
  没有确认界面时直接拒绝执行
- 规则引擎接通 E 组「自主规则」4 条（联网.反爬应对 / 学习.自主选方向 /
  自主.升级 / 联网.默认放开），默认值等于原有行为
- 新增规则「电脑控制.允许命令」（默认 false）
- 设置窗口新增 🕸️ 模块星图入口；模块星图补齐分组与说明、改为 AST 扫描真实调用边
- 实用工具面板新增搜索框
### 修复
- 「复制 a.txt 到 b.txt」曾被解析成"改剪贴板"并回"已复制到剪贴板"（看起来像成功，
  实际没复制文件）；根因是剪贴板正则贪婪且排在文件复制之前，导致 copy_file 不可达
- 文件操作只认绝对路径（"新建文件 test.txt" 不认），现支持相对路径
- restart 未被标记为危险操作（危险表里写的是 reboot，匹配不到 restart）
- 「打开百度」会去找一个叫"百度"的程序，现按网址打开
- 自我反思在 LLM 挂掉时静默记一个"5 分"，与真实评分混在一起（实测 50 条里 48 条是
  假分，平均分被灌成 5.08）；现评不上如实留空，统计只算真评分
- 「检测本地模型」按钮卡界面 3 秒（urlopen 跑在主线程），已线程化
- 模型管理对话框在子线程里操作 Qt 控件（会随机崩溃），改为信号回主线程
- 后处理（记忆沉淀/技能捕获/后台整理）失败只写日志、界面无感，现状态栏+日志双写
- 懒加载探针（19 处 call(模块,"__no__")）被当成"调用失败"刷 WARN 日志，已静音
- 26 个按钮文字被裁（全局样式表 padding 吃掉固定高度按钮的空间）
- 登录门禁此前是阻塞 while，窗口要等登录完才显示
- 错误提示不再是一句"请联系开发者"，改为说清「哪个模块 + 下一步」
### 架构
- trunk.py 从 1827 行瘦身到 1086 行（_deep_check → core/self_check.py，
  _reply_legacy → core/pipeline/legacy_reply.py，事件总线删除）
- 清理 105 处死 import（未使用 import 从 219 降到 12）
- modules_repo 与 modules/installed 重新同步（此前 47 个文件里 41 个不一致），
  并全部重新 RSA 签名
- 版本号统一：core/version.py 成为唯一来源，core/__init__.py 不再各写一份；
  新增 tools/check_version.py 防止再次漂移
## v25.1.5 - 2026-10-08
### 修复
- 修复设置保存顺序错误，改模型/联网开关现在立刻生效
- 修复deep_search空指针崩溃，网络全失败时不再抛TypeError
- 修复最后一个硬编码D盘路径，全项目零硬编码盘符
- 批量清理所有py文件UTF-8 BOM
- 备份前自动合并SQLite WAL，备份数据库完整不丢数据
### 新增
- 启动时自动检查Python版本（3.10+）和核心依赖，缺依赖弹中文提示
- 新增install.bat一键装依赖脚本
- 新增requirements.txt/requirements-optional.txt依赖清单
- 自动TTS默认关闭，避免朋友使用时突然出声
- 独立历史记录窗口，支持分页/搜索/导出聊天记录
- 向量库启动自动一致性检查，数据不一致自动对齐
## v25.1.3 - 2026-10-08
### 修复
- 修复llm_client三级模型路由，small/vl模型正确读配置
- 修复memory_loop字段判断错误，记忆闭环正常触发
- trunk.call统一返回带ok字段，不再静默失败
- crypto去掉硬编码密钥，改为本地随机生成
- bot_server自动生成访问token
## v25.1.0 - 2026-10-07
### 新增
- 实时对话流水线、截图识字GLM-4V接入、磁盘缓存秒回重复问题
- 功能中心、历史记录窗口、代码编辑器模块

### 修复：启动完成后主界面被清空（真正的白屏原因，2026-10-21）

上一轮修字体是必要的，但**不是你看到的那个白屏**。日志里
`字体就绪(151)` 说明字体早就正常了，问题出在启动收尾这一步：

```python
# gui/app_pyqt.py::_make_boot_callbacks.on_finished（旧代码）
ph.deleteLater()
window.setCentralWidget(None)      # ← 把 build_ui() 刚装好的整张界面拆掉
```

`build_ui()` 在 `BootController` 里已经 `setCentralWidget(central)` 装好了主界面，
紧接着 `on_finished` 又把它清空，于是窗口只剩标题栏和状态栏 ——
和你截图里"中间全白、底部文字正常"完全一致。

修复：占位页只从父级摘下（`setParent(None)` + `deleteLater()`），
**不再动 centralWidget**。新增两条回归测试（AST 静态检查 + 行为级检查）
钉死这个行为。

### 依赖安全升级（2026-10-21）

- pip-audit 新披露 9 条漏洞：`certifi 2026.10.18`（1 条）与 `Pillow 12.3.0`（8 条）。
- `certifi` 升到 `2026.10.19`；`Pillow` 升到 `13.0.0`（`requirements-optional.txt`
  由 `>=12,<13` 改为 `>=13,<14`）。
- 两个 lock 文件同步更新；`pip-audit` 对 runtime 与 full 两套依赖均为
  **0 known vulnerabilities**。
- 复查图像链路：Pillow 13 下 OCR/多模态相关测试 11 项通过，
  可选依赖运行时检查（含 Playwright 冒烟）通过。

### 修复：界面全白、启动一堆弹窗、代码编辑器行号崩溃（2026-10-21）

**界面全白（P0）**

- 根因不是布局，是 **Qt 一个字体都没有**：`QFontDatabase().families() == []`。
  这种状态下 Qt 不报错，只是把每个字画成空白块，看起来像白屏。
- 新增 `core/font_bootstrap.py`：启动时检测字体族数量，为 0 就从 Windows
  系统字体目录注册（微软雅黑/黑体/宋体/Segoe UI/Arial），并设置默认字体。
- `gui/app_pyqt.py` 在建任何控件之前调用 `ensure_fonts(app)`。
- 深度自检新增一行字体结论；没有 QApplication 时安全跳过（此前直接访问
  QFontDatabase 会让进程 0xC0000409 硬退出）。

**启动弹窗太多（P0）**

- 以前协议框在 `__init__` 里同步弹、登录框 `singleShot(0)` 弹、首次向导
  `singleShot(400)` 弹，三者重叠；登录框内部还会**再查一次协议**。
- 改为串行引导链：`_do_login_flow` → `_confirm_agreement` →
  `_after_agreement_login` → `_maybe_onboarding`，一次只出现一个模态框。
- `gui/login_dialog.py` 不再重复弹协议。

**首次配置向导永远不出现（P1）**

- `show_onboarding` 被删了，但 main_window / dialog_mixin 仍在 import，
  每次启动都写一条 "cannot import name 'show_onboarding'"，新用户看不到配模型向导。
- 已恢复 `show_onboarding()`，返回是否走完并向 `mark_done` 记录。

**代码编辑器行号崩溃（P1）**

- `gui/code_editor_widget.py` 调用了不存在的
  `self.viewport().contentOffset()`，paintEvent 每次抛 AttributeError 刷屏。
- 改为 `self.contentOffset()`，并在绘制期间兜住异常，不再冒泡到 Qt 事件循环。

**验证**

- 全量测试：1331 passed / 2 skipped；覆盖率约 60.48%。
- 截图对比：修复前整屏只有色块；修复后侧栏、聊天、输入框、状态栏文字全部正常。
- 新增 `tests/test_font_and_dialogs.py`（11 项）。

### 启动提速（2026-10-20）

- 新增 `core/startup.py`：启动阶段打点，日志里输出 `[启动耗时]` 一行。
- 新增 `gui/boot_controller.py`：窗口先显示骨架，Trunk 在事件循环之后创建。
- `JarvisWindow(boot_signal=False)` 支持延迟启动；`X6_BLOCKING_BOOT=1` 可退回旧行为。
- 看门狗改为在 `run.py` 里早于 Qt 拉起，独立进程。
- 模块星图导出、LLM 看门狗和模型预热改为启动后后台执行。
- 实测：界面可见 2501ms -> 约 160~200ms；全功能就绪约 1.0~1.2s。
- 本地全量测试：1298 passed / 2 skipped；覆盖率约 60.2%。