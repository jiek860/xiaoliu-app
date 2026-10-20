# Isolated Plugin SDK 示例

`hello_plugin.py` 展示插件在隔离 worker 中如何通过 broker 访问：

- `ctx.files.read/write`：仅限插件专属 `data/plugin_data/<name>/`
- `ctx.network.request`：域名必须在 manifest capabilities 中声明
- `ctx.process.run`：只允许 manifest 中固定的 argv
- `ctx.config.get_public`：只能读取公开配置键
- `ctx.audit.record`：写入审计

## 发布步骤

1. 在 `modules_repo/manifest.json` 增加插件条目和 `capabilities`。
2. 运行 `python tools/sign_modules.py` 重新签名。
3. 运行 `python tools/sync_plugin_repo.py --apply` 同步到 GitHub 公共镜像。
4. 运行 `python tools/check_plugin_repo.py` 验证哈希和签名。

远程插件下载默认关闭；发布不会改变 `plugin_remote_install=false` 的安全默认值。
