# Xiao6 AI Agent

A Chinese-first Windows desktop AI agent: local Ollama / cloud models,
web search, desktop automation, voice, long-term memory, command palette,
multi-agent chat, MCP and signed plugins.

## Highlights

- Local-first data, BYO API keys
- OpenAI, Anthropic, Gemini, OpenRouter, Azure OpenAI, LM Studio,
  llama.cpp and vLLM adapters
- Capability-aware model routing with local-to-cloud fallback
- Incremental RAG with page/offset citations, ACL roles and hybrid rerank
- UIA + OCR/vision dual-channel GUI agent, action verification and replanning
- MCP client/server, signed plugin repository, version/trust/update/rollback
- Team roles, user isolation, central config and audit export
- Explicit permissions, network policy, plugin broker/worker isolation

## Requirements

- Windows 10/11 for desktop-control features
- Python 3.10 / 3.11 / 3.12
- Optional: Ollama, 7-Zip, Tesseract, Playwright Chromium

## Quick Start

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_all_envs.ps1
```

Then run `启动PyQt.bat` or:

```powershell
python run.py
```

## Security Defaults

- Remote plugin installation is disabled by default.
- Remote plugins require HTTPS, a host allowlist and a valid RSA signature.
- Third-party/unsigned plugins are denied by default.
- Desktop actions are classified and audited; dangerous actions require approval.
- MCP child processes use a minimal environment and bounded output.

## Documentation

- `ARCHITECTURE.md` - architecture overview
- `docs/PRODUCT_PHASE2.md` - product capability roadmap and status
- `docs/PLUGIN_SDK.md` - isolated plugin SDK
- `docs/30_模块规则与API参考.md` - module API reference


## Phase-2 capabilities (2026-10-20)

- Provider adapters: OpenAI, Anthropic, Gemini, OpenRouter, Azure OpenAI,
  LM Studio, llama.cpp, vLLM and custom OpenAI-compatible endpoints.
- Capability routing: tool calling, JSON mode, vision, context window,
  with local-to-cloud fallback.
- Incremental ACL-aware RAG with page/offset citations and hybrid rerank.
- Team RBAC, login binding, per-user directories, central config and audit export.
- Plugin version/trust/compatibility checks, update and rollback ledger.
- UIA + OCR/vision GUI agent with verification, retries and DPI/IME handling.
- Usage and estimated-cost dashboard.

See `docs/PRODUCT_PHASE2.md` and `docs/PLUGIN_SDK.md`.
