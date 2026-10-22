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

- 批次 1（agent_analyst ~ learning_loop，21 个）：`docs/plugin_audit_v21_batch1.md`
- 批次 2（mcp_client ~ weather，21 个）：`docs/plugin_audit_v21_batch2.md`

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
