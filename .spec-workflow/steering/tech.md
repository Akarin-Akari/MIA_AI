# Technology Stack — MiAO AI

## Project Type

Python 后端 API 服务 + CLI 工具。Personal AI Agent，支持双 LLM Provider（Anthropic / OpenAI）的工具调用、记忆管理和自我校验。

## Core Technologies

### Primary Language
- **Language**: Python 3.11+
- **Runtime**: CPython with asyncio event loop
- **Package Manager**: pip + requirements.txt（或 pyproject.toml）

### Key Dependencies

| 依赖 | 用途 | 版本要求 |
|------|------|---------|
| **FastAPI** | Web 框架（API 入口） | latest |
| **anthropic** | Anthropic Claude SDK | latest |
| **openai** | OpenAI GPT SDK（**仅 Chat Completions API**） | latest |
| **pydantic** | 数据验证 + Settings | v2+ |
| **pydantic-settings** | 环境变量管理 | v2+ |
| **aiosqlite** | 异步 SQLite 驱动 | latest |
| **aiofiles** | 异步文件 I/O | latest |
| **uvicorn** | ASGI 服务器 | latest |

### Application Architecture

**分层架构**（由外向内）：

```
API Layer (FastAPI routes)
  └── AgentExecutor (ReAct 循环核心)
        ├── LLMClient (AnthropicClient / OpenAIClient)
        │     └── 双向翻译: CanonicalMessage ↔ Provider 私有格式
        ├── ToolRegistry (工具注册 + 自动同步包裹)
        ├── MemoryManager (三层记忆编排)
        │     ├── WorkingMemory (会话级, dict[str, deque])
        │     ├── MarkdownMemory (持久画像, profile.json + learned_facts.md)
        │     └── SQLiteMemory (历史消息, aiosqlite)
        └── SelfVerifier (三层校验)
              ├── Stage 1: tool_results 硬规则
              ├── Stage 2: profile.json 结构化校验
              └── Stage 3: LLM 软兜底 (抽样)
```

### Data Storage
- **Primary storage**: SQLite（aiosqlite 异步驱动）— `messages` 表 + `facts` 表
- **Persistent state**: JSON 文件（`profile.json`）+ Markdown 文件（`learned_facts.md`）
- **Caching**: WorkingMemory（内存中的 `dict[str, deque[CanonicalMessage]]`）
- **Data formats**: JSON（profile）、Markdown（facts）、SQLite（messages）

### External Integrations
- **APIs**: Anthropic Messages API / OpenAI Chat Completions API
- **Protocols**: HTTPS REST
- **Authentication**: API Key（`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`）

## Development Environment

### Build & Development Tools
- **Build System**: pip install + uvicorn 启动
- **Development workflow**: `uvicorn app.main:app --reload` 热重载

### Code Quality Tools
- **Static Analysis**: mypy（类型检查）、ruff（lint）
- **Formatting**: ruff format（或 black）
- **Testing Framework**: pytest + pytest-asyncio
- **Documentation**: docstring（Google style）

### Version Control
- **VCS**: Git
- **Branching Strategy**: trunk-based（60 分钟挑战直接在 main 开发）

## Deployment & Distribution
- **Target Platform**: 本地开发环境（单进程 uvicorn）
- **Distribution Method**: 源码直接运行
- **Installation**: `pip install -r requirements.txt`

## Technical Requirements & Constraints

### Performance Requirements
- **TTFB**：memory extraction 必须 fire-and-forget，不阻塞主响应
- **Event Loop**：同步 tool 必须通过 `asyncio.to_thread` 卸载，禁止阻塞

### Compatibility Requirements
- **Python**: 3.11+（需要 `asyncio.TaskGroup` 等新特性）
- **OS**: Windows / macOS / Linux

### Security & Compliance
- **API Key 管理**：pydantic-settings 从环境变量读取，禁止硬编码
- **数据隔离**：Single-user assumption，禁止多用户共享实例

### Scalability & Reliability
- **并发模型**：单进程 asyncio（`asyncio.Lock` 保护共享文件）
- **多 Worker 警告**：如需 gunicorn 多 worker，必须引入 `filelock` 跨进程锁
- **Atomic Write**：所有共享文件写入走 `{path}.tmp` → `os.replace`

## Technical Decisions & Rationale

### Decision Log
1. **Raw SDK over LangChain**：60 分钟挑战中框架开销 > 收益，raw SDK 更可控
2. **CanonicalMessage 中立格式**：避免 provider 锁定，实现真正的 O（开闭原则）
3. **三层 Verifier**：Stage 1/2 确定性短路 → Stage 3 抽样兜底，平衡正确性与延迟
4. **SQLite over PostgreSQL**：零部署成本，aiosqlite 够用
5. **pydantic v2**：性能提升 + Structured Outputs 原生支持

## Known Limitations

- **单进程 Lock**：`asyncio.Lock` 无法防御多 Worker 并发（已在 README 声明）
- **无 RAG**：当前无向量检索，长期记忆靠 Markdown 文件（60 分钟内不实现）
- **无 Streaming**：Layer 1 不含流式输出（Layer 2 可选增量）
