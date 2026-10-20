# 第二阶段：产品竞争力落地

## 状态说明

- 已落地代码 + 测试
- 已有底座，仍需 UI/业务接线
- 需要外部环境/证书/真实账号验收

## 1. 模型接入

`core/llm_providers.py` 已支持 OpenAI、Anthropic、Gemini、OpenRouter、Azure OpenAI、LM Studio、llama.cpp、vLLM。`core/llm_cloud.py` 已支持 `cloud_provider` 走 provider adapter；默认留空时保持原有 OpenAI-compatible 路径。

## 2. 能力探测与路由

`core/model_router.py` 提供静态能力矩阵 + provider 默认能力 + 运行时 override，按 tool calling、JSON、vision、context window 路由，本地失败自动转云端，未知模型保守降级，并返回 fallback chain。`LLMClient.route_request()` 已接入。

## 3. RAG

`core/rag_pipeline.py` 提供增量文件清单、页码/offset/chunk 引用定位、ACL roles、混合检索、RRF 融合、轻量 rerank 和原子写入。`KnowledgeQnA` 已接入 ingest/search；CLI 为 `python tools/rag_admin.py`。

## 4. GUI Agent

已有 `computer_agent` 的 Observe -> Plan -> Act -> Verify -> Replan 主链。本阶段补充 `core/gui_agent_quality.py`：UIA/OCR/视觉双通道定位、动作后验证、有界重试、失败修复计划、DPI/多显示器坐标转换、中文/多行/IME 输入 paste 策略。

## 5. 插件市场产品化

`core/plugin_registry.py` 提供 SemVer、宿主/API 兼容检查、官方/签名/未签名信任等级、更新选择、blocked 版本区分和安装账本。UI 已展示发布者、信任等级、版本、签名、API、能力和风险。`docs/examples/plugins/hello_plugin.py` 提供受限 SDK 示例。

## 6. 多用户/团队版

`core/team_policy.py` 提供 owner/admin/editor/viewer/auditor 角色、权限、用户隔离、集中配置覆盖、脱敏审计导出。CLI 为 `python tools/team_admin.py`。

## 验收命令

    python -m pytest tests/test_llm_providers.py tests/test_llm_cloud_provider.py tests/test_model_router.py tests/test_rag_pipeline.py tests/test_gui_agent_quality.py tests/test_plugin_registry.py tests/test_team_policy.py -q

## 仍需接线

- 设置页已增加 provider 选择器；Azure deployment 使用 cloud_model 字段，API version 仍建议增加独立输入
- 管理端增加团队/角色/集中配置页面
- 插件市场增加检查更新/更新/回滚按钮
- RAG 管理页增加文档、ACL、引用预览
- GUI Agent 将修复计划接入 computer_agent 的 trace UI

## 发布前 P0

- 干净 Windows 10/11 安装/升级/卸载
- 真实 Ollama + 云端模型 E2E
- 8 小时长稳
- Authenticode 签名
- PyQt5 许可证决策

## 非环境类收尾（已完成）

- RAG 管理窗口：导入文件/目录、ACL 角色、检索引用、删除来源。
- 团队管理窗口：用户表、角色设置、集中配置、审计导出。
- 插件市场：检查更新后可直接应用兼容更新，自动保留回滚副本；单插件可回滚。
- 电脑 Agent 窗口：展示重试修复计划和动作验证原因。
- 设置页：模型服务商选择器。
- 命令面板可通过「RAG管理」「团队管理」「多用户」打开对应窗口。
