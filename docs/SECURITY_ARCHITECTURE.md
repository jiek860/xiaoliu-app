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
| `allow_unsigned_plugins` | false | 允许本地无签名插件，仅开发/兼容 |
| `allow_inprocess_plugins` | false | 进程内插件安装，不安全，仅开发调试 |
| `plugin_remote_install` | false | 远程插件下载总开关，默认关闭 |
| `plugin_repo_urls` | 官方 Gitee + GitHub 地址 | 按顺序尝试的插件仓库 HTTPS 源 |
| `plugin_repo_allowlist` | 官方两个 host | 远程插件仓库主机白名单，必须显式匹配 |
| `mcp_allow_dangerous_tools` | false | 允许 MCP 暴露高风险工具 |
| `mcp_allow_remote` | false | 允许 MCP 监听非环回地址 |
| `security.network_mode` | standard | `off/learning/standard` 由 NetGuard 使用 |


## 远程插件双源策略

- 默认 `plugin_remote_install=false`，不会访问任何远程插件仓库。
- 显式启用后，按 `plugin_repo_urls` 顺序尝试 Gitee / GitHub 等 HTTPS 源。
- 每个源都必须通过 `plugin_repo_allowlist` 主机校验。
- 任一 URL 非 HTTPS、带内嵌凭据或主机不在白名单，整组源拒绝使用。
- 所有源下载到的内容都必须通过同一 RSA 签名校验；验签失败不会落盘。
- 远程下载不存在 `allow_unsigned_plugins` 放行路径。


---

## 局域网访问策略（2026-10-22 更新）

### 默认拒绝

`core/net_guard.py` 对私有地址默认拒绝（SSRF 防护）：

```text
http://192.168.1.2:11434/...  purpose=network       → 拒绝：私有/回环/保留地址
```

### 两类显式放行

| 配置 | 粒度 | 写法 |
|---|---|---|
| `security.allow_lan_hosts` | 单台主机 | `"192.168.1.2"` 或 `"192.168.1.2:11434"` |
| `security.allow_lan_cidrs` | 整个网段 | `"192.168.0.0/16"` |

两者取并集。只对下列 purpose 生效：

```text
local_model / local_mcp / local_health
```

### 判断顺序

```text
1. purpose 不在 _LOCAL_PURPOSES          → 拒绝
2. host 为回环（127.0.0.1/localhost/::1） → 按端口规则
3. host 落在 allow_lan_cidrs 私有网段     → 放行
4. host 精确匹配 allow_lan_hosts          → 按是否带端口
5. 其他                                   → 拒绝
```

### 硬性限制（代码级）

```python
if not (ip.is_private and not ip.is_loopback):
    return False      # 公网 IP 永不进入 CIDR 放行分支
```

即使配置了 `0.0.0.0/0` 也无法放行公网地址。

### 实际部署场景

```text
虚拟机（程序）192.168.10.128  ──NAT──>  物理机（Ollama）192.168.1.2:11434
```

必须在 `allow_lan_cidrs` 里声明 `192.168.0.0/16`，否则本地模型请求被拒，
程序会一直退化为云端模式。

### 配套修复

`core/llm_cloud.local_model_purpose()` 按主机名匹配 `ollama_url`，
不再用字符串前缀判断 —— 否则 `127.0.0.1` 与 `localhost` 写法不一致
会让本地请求被当成云端请求，进而被网络守卫拒绝。