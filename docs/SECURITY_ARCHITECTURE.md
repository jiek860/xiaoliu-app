# 安全架构与信任边界

## 目标

把签名从直接加载降级为来源证明，把真正的安全决策放到统一的
能力授权和工具执行层。

## 信任边界

| 边界 | 信任级别 | 执行位置 | 关键控制 |
|---|---|---|---|
| 用户输入 | 可信 | 主进程 | 正常权限流程 |
| 浏览器/搜索/知识库/MCP/插件返回 | 不可信 | 主进程/worker | provenance + 外部内容标记 + 副作用工具拒绝 |
| 官方随包模块 | 官方来源，但仍需审计 | 主进程兼容层 | 签名、AST 边界、权限审计 |
| 第三方插件 | 不可信 | 独立 worker | 受限 SDK、JSON-RPC broker、Job Object、能力白名单 |
| MCP 子进程 | 不可信 | 独立子进程 | 启动确认、最小环境、固定 cwd、Job Object、输出上限 |

## 能力模型

清单 `capabilities` 由 `core/plugin_capabilities.py` 校验和归一化：

- `network`: 域名、HTTP 方法。
- `filesystem`: 插件专属根目录下的读写范围。
- `process`: 固定 argv，禁止 shell/wrapper。
- `ui_control`: 默认关闭。
- `config`: 仅公开键；`read_secrets` 默认关闭。

缺省全部拒绝。没有 `capabilities` 的旧插件标记为 legacy，只能使用空能力集。

## 运行时授权

- `PermissionCenter.authorize_capability()` 负责 once/session/always、撤销和审计。
- `PluginBroker` 是插件 worker 的唯一能力出口。
- `NetGuard` 是网络出口的统一策略点。
- `SafeHttp.open_url()` 强制只允许 http/https，并拒绝 URL 内嵌凭据。
- `AuditLog` 对所有 allow/deny 记录做统一脱敏。

## 不可声称的保证

当前实现是进程隔离 + 能力代理 + 受限 SDK，**不是 VM 级沙盒**。
Python worker 内仍可能存在解释器层面的逃逸路径；因此：

- 第三方插件必须经过签名和人工审核。
- 若要求绝不能访问网络/文件的强保证，需要 Windows AppContainer、
  WFP/防火墙、低权限用户或容器等 OS 级边界。
- Prompt 文本包装不能替代工具执行层策略。

## 关键开关

| 配置 | 默认 | 说明 |
|---|---|---|
| `allow_unsigned_plugins` | false | 允许无签名插件，仅开发/兼容 |
| `allow_inprocess_plugins` | false | 进程内插件安装，不安全，仅开发调试 |
| `mcp_allow_dangerous_tools` | false | 允许 MCP 暴露高风险工具 |
| `mcp_allow_remote` | false | 允许 MCP 监听非环回地址 |
| `security.network_mode` | standard | `off/learning/standard` 由 NetGuard 使用 |
