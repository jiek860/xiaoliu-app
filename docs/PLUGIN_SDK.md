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
