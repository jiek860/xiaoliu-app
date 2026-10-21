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
