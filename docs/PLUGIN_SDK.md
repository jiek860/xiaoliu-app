# Isolated Plugin SDK

> 完整的强制性规范（清单必填字段、能力 5 段、依赖边界、签名、风险等级）
> 见 **`docs/PLUGIN_STANDARD.md`**。本文只讲怎么写一个插件。

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
