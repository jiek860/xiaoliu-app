# 小6插件标准（Plugin Standard v1.0）

适用版本：v25.2.23 起
状态：**已落地并强制执行**（不是建议稿）
事实源：`core/plugin_api.py`、`core/plugin_capabilities.py`、
`core/plugin_broker.py`、`modules_repo/manifest.json`
契约测试：`tests/test_plugin_standard.py`

---

## 一、标准包含什么

| 编号 | 标准 | 强制点 |
|---|---|---|
| S1 | 清单必填字段 | 插件市场安装/下载前 |
| S2 | 插件 API 版本 `api_version=1.0` | `manifest_api_version()` |
| S3 | 能力声明 `capabilities`（5 段齐全） | `validate_capabilities()` |
| S4 | 依赖边界（只能用公共 core 模块） | AST 静态检查，不执行插件代码 |
| S5 | 签名与哈希（RSA + sha256） | 安装/下载前验签 |
| S6 | 文件名校验与路径越界防护 | `safe_plugin_filename` / `safe_join` |
| S7 | 运行时权限代理（broker/worker） | 每次能力调用 |
| S8 | 风险等级与信任等级展示 | 插件市场 UI |

---

## 二、S1 清单必填字段

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

---

## 三、S2 API 版本

```python
PLUGIN_API_VERSION = "1.0"
SUPPORTED_PLUGIN_API = {"1.0"}
```

- 不写 `api_version` → `legacy=True`，只给警告，但**新发布必须写**。
- 写了不支持的版本 → 直接拒绝安装。
- 版本号是硬比较，不做范围匹配。

---

## 四、S3 能力声明（capabilities）

5 个分段**必须齐全**，缺一段即不合格。

```json
"capabilities": {
  "network":    {"enabled": true,  "domains": ["api.example.com"], "methods": ["GET"]},
  "filesystem": {"read": ["data/plugin_data/weather/notes"],
                 "write": ["data/plugin_data/weather/cache"]},
  "process":    {"enabled": false, "allow_argv": []},
  "ui_control": {"enabled": false},
  "config":     {"read_secrets": false, "public_keys": ["theme"]}
}
```

规则：

- `network.enabled=true` 必须同时给 `domains` 和 `methods`（默认 `GET`）。
- 域名只接受合法域名；**回环地址**额外允许字面量
  `localhost` / `127.0.0.1` / `::1`（插件连本地模型、MCP、浏览器调试端口）。
  带端口的地址不允许（端口不属于主机白名单）。
- `filesystem` 的路径必须落在 `data/plugin_data/<插件名>/` 下，
  绝对路径、`..`、盘符路径一律拒绝。
- `process.allow_argv` 必须是**固定 argv 数组**，禁止 shell 元字符
  （`; & | < > ` $ % 换行`），禁止 `cmd/powershell/bash/wscript/cscript` 包装器。
- `config.public_keys` 不允许出现 `key/token/secret/password/credential/private` 类键名。

风险等级由能力自动推导：

| 等级 | 触发条件 |
|---|---|
| high | `process.enabled` 或 `ui_control.enabled` 或 `config.read_secrets` |
| medium | `network.enabled` 或 `filesystem.write` 非空 |
| low | 其余 |

---

## 五、S4 依赖边界

第三方插件只能依赖 `PUBLIC_CORE_MODULES` 里的公共模块，例如：

```
core.safe / core.error_text / core.path_safety / core.document_parser
core.net_guard / core.permission_center / core.audit_log / core.retrieval
core.fts_index / core.plugin_api / core.lazy_config / core.plugin_signer
```

**永远禁止**（`FORBIDDEN_CORE_PREFIXES`）：

```
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

---

## 六、S5 签名与哈希

- `sha256` = 文件字节的 SHA-256（`plugin_repo/.gitattributes` 固定 `* -text`，
  杜绝换行转换破坏哈希）。
- `signature` = 用 `tools/sign_modules.py` 以私钥签名的清单摘要。
- 远程安装：HTTPS + 主机白名单 + RSA 验签，**任一不满足即拒绝**。
- 远程插件即使配置 `allow_unsigned_plugins=true` 也拒绝。
- 本地安装：默认拒绝无签名模块；显式开启才放行。

---

## 七、S7 运行时隔离

插件实际运行在 `core/plugin_broker.py` 的受限 worker 中：

- 只暴露 `ctx.files / ctx.network / ctx.process / ctx.config / ctx.audit`
- 每次能力调用都经过 broker 授权（`_authorize`），超出声明即拒绝
- 网络只允许 http/https，且必须在声明的域名内
- 子进程只允许 manifest 中的固定 argv
- 配置只能读 `public_keys`
- 审计写入 `data/plugin_audit.jsonl`

示例见 `docs/examples/plugins/hello_plugin.py`。

---

## 八、S8 信任等级

| 等级 | 判定 |
|---|---|
| `official` | `first_party=true` 且签名有效 |
| `signed` | 第三方且签名有效 |
| `unsigned` | 无签名（远程一律拒绝，本地默认拒绝） |

插件市场卡片展示：发布者、信任等级、版本、签名状态、API 版本、能力摘要、风险等级。

---

## 九、发布一个新插件

```powershell
# 1. 模块放进 modules/installed/，并在 core/lazy_config.py 登记
# 2. 同步到仓库（会自动生成标准 capabilities）
py -3 tools/rebuild_modules_repo.py --apply
# 3. 签名
$env:X6_KEY_VAULT="E:\xiao6-keys"
py -3 tools/sign_modules.py
# 4. 发布到 GitHub 公共镜像
py -3 tools/sync_plugin_repo.py --apply
# 5. 验证（42/42 必须全过）
py -3 tools/check_plugin_repo.py
py -3 tools/check_plugin_api.py
py -3 -m pytest tests/test_plugin_standard.py -q
```

---

## 十、当前官方模块合规情况（2026-10-21）

```text
模块总数            42
声明 capabilities   42 / 42
5 段齐全            42 / 42
已签名              42 / 42
API 版本 1.0        42 / 42
清单+源码校验通过   42 / 42
legacy（未声明）    0
```

高风险显式声明：

| 模块 | 能力 | 说明 |
|---|---|---|
| `computer_controller` | `ui_control.enabled=true` | 桌面控制 |
| `code_runner` | `process.enabled=true`，`allow_argv=[["python"],["py"]]` | 代码执行 |
| `weather` / `deep_search` | `network.enabled=true` + 域名白名单 | 联网 |
| `browser` / `mcp_client` | `network` 仅回环地址 | 连本地服务 |
