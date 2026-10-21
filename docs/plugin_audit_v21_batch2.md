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
