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
| 7.3 SPEC 技术规格 | 部分 | `docs/PLUGIN_STANDARD.md` |
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
质量门禁 warn           125（逐步收敛，不阻塞发布）
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
> 相关文档：`docs/PLUGIN_SDK.md`（开发指南）、`docs/MODULE_STANDARD.md`（模块级标准对照）
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
