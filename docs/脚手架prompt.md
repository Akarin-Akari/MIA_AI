# MiAO AI Coding Challenge — 脚手架准备文档 v2

> **Challenge**: Personal AI Agent with Tool Use, Memory & Self-Verification
> **时限**: 60分钟 | **工具**: Claude Code / Cursor
> **版本**: v2 — 综合 Opus 4.7 审查 + 三层记忆架构 + RAG可插拔接口

---

## 背景

**MiAO AI** 是新加坡游戏公司 MiAO（2022年成立，51-200人）于 **2026年初** 拆分出的独立AI Agent子公司。LinkedIn显示仅2名关联员工，官网只有一页Rich Sutton引言。公司自称"100% AI driven, no middle management"，JD中宣称的"SGD 95M融资"实为游戏母公司的融资额。

**面试流程完全由AI驱动**：简历筛选→邮件调度→AI Agent语音面试（Lark会议）→面试结束2分钟内自动发送"恭喜通过"邮件→自动发放60分钟Coding Challenge链接。全程未与任何真人交流。

**Coding Challenge规则**：

- 点击Start后60分钟倒计时，不可暂停
- 需确认GitHub账户（面试官可能review commit history）
- 72小时内有效

**本文档目的**：在打开题目之前，预先搭建一个**通用Agent脚手架**（Layer 1），push到private repo。开题后只做增量delta（Layer 2），确保60分钟内完成。

本文档经过三轮迭代：

1. 初版设计（技术选型 + 模块化架构）
2. Opus 4.7审查（指出过度专一化、应增加弹性空间、LLM不应绑死provider）
3. 三层记忆架构 + RAG可插拔接口（借鉴自作者自研的akari-mem生产级记忆系统的设计模式）

---

## 一、题目拆解

```
4个核心模块：
1. Agent Core     — ReAct循环：思考→行动→观察
2. Tool Use       — 工具注册/调用/结果解析
3. Memory         — 三层记忆：工作记忆 + 情景记忆(md) + 持久化(SQLite+RAG)
4. Self-Verify    — 读取记忆做ground truth校验
```

## 二、技术选型

| 方案                  | 优点        | 缺点                | 60分钟适配度 |
| ------------------- | --------- | ----------------- | ------- |
| **FastAPI + 原生SDK** | 轻量、全控、易调试 | 手搓工具循环            | ★★★★★   |
| LangChain/LangGraph | 内置agent模式 | 重抽象、调试噩梦、版本地狱     | ★★☆☆☆   |
| CrewAI/AutoGen      | 快速出agent  | 太opinionated、定制困难 | ★★★☆☆   |
| 纯CLI脚本              | 最简单       | 不够工程化、没API        | ★★★☆☆   |

**最终选型：**

- **LLM**: LLMClient Protocol 抽象 + Anthropic/OpenAI 双实现（不绑死provider）
- **API**: FastAPI（薄API层）+ CLI 双模式入口（默认CLI，`--api`切换）
- **Memory**: 三层架构（Working + Markdown + SQLite），RAG接口可插拔
- **测试**: 1个smoke test（不搞5个测试文件的奢侈品）

## 三、设计原则

```
KISS:  不用任何框架抽象，原生SDK直接调
DRY:   BaseTool + Registry 模式消除重复
SOLID: 依赖注入，Protocol抽象，LLM/Memory/Vector全部可替换
YAGNI: 只做题目要求的4个能力 + 预留RAG接口（不实现）
```

## 四、Pre-game 策略

```
Pre-game (无时限):
  通用agent骨架跑通 → push到private repo
  Layer 1 只含抽象层 + 最简实现 + 1个smoke test
        ↓
打开题目 (60min):
  00-05min  读题 → 确定具体需求
  05-40min  Layer 2 增量实现（具体工具/prompt/memory策略）
  40-55min  跑通端到端 + 修bug
  55-60min  补README Design Decisions → 提交
```

### ⚡ Rehearsal（排练）

正式开题前，**用假题目跑一次完整流程**（如"做一个能查天气+记忆用户偏好+自我验证的agent"），验证脚手架是否60分钟内能完成delta部分。如果不能，说明脚手架需要再瘦身。

---

## 五、Layer 分层策略

### Layer 1: Pre-built（通用骨架，现在做）

```
✅ LLMClient Protocol + AnthropicClient + OpenAIClient
✅ BaseTool ABC + ToolRegistry + 1个DummyTool
✅ 三层Memory:
   - WorkingMemory (list[Message])
   - MarkdownMemory (md文件读写)
   - SQLiteStore (纯CRUD, 无FTS5)
✅ RAG可插拔接口:
   - EmbeddingProvider Protocol + NoOpEmbedding
   - VectorStore Protocol + NoOpVectorStore
   - Factory + providers/目录
✅ MemoryManager (编排三层)
✅ AgentExecutor ReAct骨架（不含具体prompt）
✅ SelfVerifier 骨架（verify方法框架，prompt留空）
✅ FastAPI路由空壳 + CLI入口（双模式）
✅ conftest.py + 1个smoke test
✅ prompts/ 目录（先建好，放空md文件）
✅ README模板（含mermaid + "What I Would Build Next"）
✅ .env.example + requirements.txt
```

### Layer 2: 开题后做（60分钟 delta）

```
🔧 读题 → 确定具体工具 → 实现具体Tool
🔧 确定Memory需求 → 选择是否加FTS5 / 启用RAG
🔧 写 prompts/system.md + prompts/verifier.md
🔧 确定LLM provider → 选Anthropic/OpenAI/自定义
🔧 跑通端到端case
🔧 补README Design Decisions + Trade-offs
```

---

## 六、脚手架 Prompt（复制到 Claude Code / Cursor 执行）

```markdown
# Task: Scaffold a "Personal AI Agent" Python project

## Project Overview
Build a modular, production-quality Python project for a Personal AI Agent.
This is a **generic scaffold** — concrete tools, prompts, and memory strategies
will be added later based on specific requirements. Focus on clean abstractions
and pluggable interfaces.

Core capabilities:
1. **Tool Use** — registry-based tool calling with JSON schema
2. **Memory** — 3-tier memory (working + markdown + SQLite), pluggable RAG
3. **Self-Verification** — agent reviews its own output before returning

## Tech Stack
- **Python 3.11+**
- **FastAPI** — thin API layer (optional, `--api` flag)
- **LLM**: abstract `LLMClient` Protocol + Anthropic & OpenAI implementations
- **SQLite** (via `aiosqlite`) — long-term memory, zero-config
- **aiofiles** — async markdown file I/O
- **Pydantic v2** — data models & validation
- **pytest + pytest-asyncio** — 1 smoke test
- **uvicorn** — ASGI server
- **python-dotenv** — env management
- **litellm** (optional) — universal LLM fallback

## Project Structure

```
personal-ai-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Dual entry: CLI (default) + FastAPI (--api)
│   ├── config.py               # Settings via pydantic-settings
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py           # POST /chat, GET /memory, GET /health
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── core.py             # AgentExecutor: ReAct loop (think→act→observe)
│   │   └── verifier.py         # SelfVerifier: validate output before return
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py             # LLMClient Protocol + LLMResponse model
│   │   ├── anthropic_client.py # Anthropic SDK implementation
│   │   └── openai_client.py    # OpenAI SDK implementation
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseTool ABC with execute() + to_schema()
│   │   ├── registry.py         # ToolRegistry: register/lookup/list tools
│   │   └── dummy.py            # DummyTool: proves registry works
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── base.py             # MemoryStore ABC
│   │   ├── manager.py          # MemoryManager: orchestrates 3 tiers
│   │   ├── working.py          # Tier 1: in-memory conversation messages
│   │   ├── markdown_store.py   # Tier 2: md files (facts, profile, summaries)
│   │   ├── sqlite_store.py     # Tier 3: SQLite persistent CRUD
│   │   ├── embedding.py        # RAG interface: EmbeddingProvider Protocol
│   │   ├── vector_store.py     # RAG interface: VectorStore Protocol
│   │   ├── factory.py          # Factory: create_embedding / create_vector_store
│   │   └── providers/          # Concrete RAG implementations (fill on demand)
│   │       └── __init__.py
│   └── models/
│       ├── __init__.py
│       └── schemas.py          # ChatRequest, ChatResponse, Message, etc.
├── prompts/                    # Prompt-as-config: edit prompts without touching code
│   ├── system.md               # System prompt (fill based on challenge requirements)
│   ├── verifier.md             # Verification prompt template
│   └── memory_extract.md       # Fact extraction prompt template
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # in-memory fixtures + mock LLM
│   └── test_smoke.py           # 1 end-to-end smoke test: "agent completes 1 ReAct loop"
├── memory/                     # Runtime markdown memory directory (gitignored)
│   └── .gitkeep
├── .env.example                # API keys template
├── .gitignore
├── requirements.txt
├── pyproject.toml              # project metadata + pytest config
└── README.md                   # Architecture + Quick Start + Design Decisions
```

## Detailed Implementation Requirements

### 1. LLM Client (`app/llm/`)

Abstract LLM interface — never lock to a single provider.

- `base.py`:
  ```python
  from typing import Protocol, runtime_checkable

  @runtime_checkable
  class LLMClient(Protocol):
      async def call(
          self,
          messages: list[dict],
          tools: list[dict] | None = None,
          model: str | None = None,
      ) -> "LLMResponse": ...

  @dataclass
  class LLMResponse:
      content: str                          # text response
      tool_calls: list[ToolCall] | None     # tool invocations
      stop_reason: str                      # "end_turn" | "tool_use"
      raw: Any = None                       # original API response

  @dataclass
  class ToolCall:
      id: str
      name: str
      input: dict
  ```

- `anthropic_client.py`:
  ```python
  class AnthropicClient:
      def __init__(self, api_key: str, model: str):
          self.client = anthropic.AsyncAnthropic(api_key=api_key)
          self.model = model

      async def call(self, messages, tools=None, model=None) -> LLMResponse:
          response = await self.client.messages.create(
              model=model or self.model,
              messages=messages,
              tools=tools or [],
              max_tokens=4096,
          )
          # Normalize to LLMResponse
          ...
  ```

- `openai_client.py`: Same pattern with `openai.AsyncOpenAI`.

### 2. Agent Core (`app/agent/core.py`)
- Class `AgentExecutor` with async `run(user_message: str, conversation_id: str) -> AgentResponse`
- Dependency injection: `__init__(self, llm: LLMClient, tools: ToolRegistry, memory: MemoryManager, verifier: SelfVerifier)`
- Implement ReAct loop:
  ```
  while iterations < max_iterations (default 10):
      # Load memory context (md files + recent history)
      context = await memory.get_context(conversation_id)
      system_prompt = load_prompt("system.md") + "\n" + context

      response = await llm.call(messages, tools=tools.schemas())
      if response.stop_reason == "end_turn":
          break
      if response.stop_reason == "tool_use":
          for tc in response.tool_calls:
              result = await tools.execute(tc.name, tc.input)
              messages.append(tool_result_message(tc, result))
          continue
  ```
- After loop: SelfVerifier → MemoryManager.after_turn()
- **Never crash**: wrap tool execution and LLM calls in try/except, log errors gracefully

### 3. Tool System (`app/tools/`)
- `BaseTool` ABC:
  ```python
  class BaseTool(ABC):
      name: str
      description: str

      @abstractmethod
      def input_schema(self) -> dict: ...  # JSON Schema

      @abstractmethod
      async def execute(self, **kwargs) -> str: ...

      def to_schema(self) -> dict:
          """Format for LLM tool_use API (works with both Anthropic & OpenAI)."""
          return {
              "name": self.name,
              "description": self.description,
              "input_schema": self.input_schema(),
          }
  ```
- `ToolRegistry`:
  ```python
  class ToolRegistry:
      def register(self, tool: BaseTool) -> None
      def get(self, name: str) -> BaseTool
      async def execute(self, tool_name: str, tool_input: dict) -> str
      def schemas(self) -> list[dict]  # all tool schemas for LLM
      def list_tools(self) -> list[str]  # tool names
  ```
- Pre-build **only** `DummyTool` (returns "dummy response") to prove registry works.
- **Concrete tools (Calculator, DateTime, WebSearch, etc.) are NOT pre-built** — add based on challenge requirements.

### 4. Memory System (`app/memory/`) — 3-Tier Architecture

#### Tier 1: Working Memory (`working.py`)
```python
class WorkingMemory:
    """Current conversation context. In-memory, per-session."""

    def __init__(self):
        self._messages: list[Message] = []

    def append(self, message: Message): ...
    def get_messages(self) -> list[Message]: ...
    def clear(self): ...
```

#### Tier 2: Markdown Memory (`markdown_store.py`)
```python
class MarkdownMemory:
    """Medium-term memory via markdown files.
    Inspired by Claude Code's CLAUDE.md pattern.
    Agent writes notes to help itself remember across conversations."""

    def __init__(self, base_dir: str = "./memory"):
        self.base_dir = Path(base_dir)

    async def append_fact(self, fact: str):
        """Append a learned fact to learned_facts.md"""

    async def update_profile(self, key: str, value: str):
        """Update user_profile.md with a key-value pair"""

    async def save_summary(self, conv_id: str, summary: str):
        """Save conversation summary to conversations/{conv_id}/summary.md"""

    async def get_context(self) -> str:
        """Load all md files as context string for system prompt injection"""
```

Runtime file structure:
```
memory/
├── user_profile.md            # "Name: Akarin, Timezone: UTC+8, ..."
├── learned_facts.md           # "- User prefers Python\n- User has a cat"
└── conversations/
    └── {conv_id}/
        └── summary.md         # Auto-generated conversation summary
```

#### Tier 3: SQLite Store (`sqlite_store.py`)
```python
class SQLiteStore(MemoryStore):
    """Long-term persistent memory. Plain CRUD, no FTS5 by default.
    Optionally backed by VectorStore for semantic search (RAG)."""

    def __init__(self, db_path: str, vector_store: VectorStore | None = None):
        self._vector = vector_store or NoOpVectorStore()

    async def save(self, conv_id, role, content, metadata=None):
        row_id = await self._insert(...)         # Always: SQLite
        await self._vector.add(f"msg_{row_id}")  # Optional: vector index

    async def get_history(self, conv_id, limit=50) -> list[MemoryEntry]: ...

    async def search(self, query, limit=5) -> list[MemoryEntry]:
        # Try vector search first (if RAG enabled)
        results = await self._vector.search(query, limit)
        if results:
            return results
        # Fallback: SQLite LIKE search
        return await self._keyword_search(query, limit)
```

Tables:
```sql
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    fact            TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_facts_conv ON facts(conversation_id);
```

#### RAG Pluggable Interface (`embedding.py` + `vector_store.py`)
```python
# embedding.py
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimension(self) -> int: ...
    @property
    def model_name(self) -> str: ...

class NoOpEmbedding:
    """Default: RAG disabled. Zero overhead."""
    async def embed(self, texts): return []
    @property
    def dimension(self): return 0
    @property
    def model_name(self): return "none"

# vector_store.py
class VectorStore(Protocol):
    async def add(self, id: str, text: str, metadata: dict | None = None): ...
    async def search(self, query: str, limit: int = 5) -> list[dict]: ...
    async def delete(self, id: str): ...

class NoOpVectorStore:
    """Default: disabled. Falls back to SQLite keyword search."""
    async def add(self, *a, **kw): pass
    async def search(self, *a, **kw): return []
    async def delete(self, *a, **kw): pass

# factory.py
def create_embedding(config: Settings) -> EmbeddingProvider:
    match config.embedding_provider:
        case "openai":
            from .providers.openai_embed import OpenAIEmbedding
            return OpenAIEmbedding(config.embedding_api_key, config.embedding_model)
        case "local":
            from .providers.local_embed import LocalEmbedding
            return LocalEmbedding(config.embedding_model)
        case _:
            return NoOpEmbedding()

def create_vector_store(config: Settings, embedding: EmbeddingProvider) -> VectorStore:
    match config.vector_store:
        case "chroma":
            from .providers.chroma_store import ChromaStore
            return ChromaStore(embedding)
        case _:
            return NoOpVectorStore()
```

#### Memory Manager (`manager.py`)
```python
class MemoryManager:
    """Orchestrates 3-tier memory."""

    def __init__(self, working: WorkingMemory, markdown: MarkdownMemory,
                 sqlite: SQLiteStore, llm: LLMClient):
        self.working = working
        self.markdown = markdown
        self.sqlite = sqlite
        self._llm = llm  # for fact extraction

    async def get_context(self, conv_id: str) -> str:
        """Build full context for system prompt injection."""
        md_context = await self.markdown.get_context()
        history = await self.sqlite.get_history(conv_id, limit=10)
        return f"{md_context}\n\n## Recent History\n{format_history(history)}"

    async def after_turn(self, conv_id, user_msg, agent_response):
        """Post-turn hook: persist to all tiers."""
        self.working.append(user_msg)
        self.working.append(agent_response)
        await self.sqlite.save(conv_id, "user", user_msg.content)
        await self.sqlite.save(conv_id, "assistant", agent_response.content)
        # LLM-powered fact extraction → write to markdown
        facts = await self._extract_facts(user_msg, agent_response)
        for fact in facts:
            await self.markdown.append_fact(fact)
```

### 5. Self-Verification (`app/agent/verifier.py`)
```python
class SelfVerifier:
    def __init__(self, llm: LLMClient, memory: MarkdownMemory):
        self._llm = llm
        self._memory = memory

    async def verify(self, question, answer, tool_results) -> VerificationResult:
        # Load known facts from markdown memory as ground truth
        known_context = await self._memory.get_context()
        prompt = load_prompt("verifier.md").format(
            question=question,
            answer=answer,
            tool_results=tool_results,
            known_facts=known_context,
        )
        result = await self._llm.call([{"role": "user", "content": prompt}])
        return parse_verification(result.content)

@dataclass
class VerificationResult:
    is_valid: bool
    confidence: float
    issues: list[str]
    revised_answer: str | None
```

### 6. Dual Entry Point (`app/main.py`)
```python
import sys, asyncio

def main():
    if "--api" in sys.argv:
        # FastAPI mode
        import uvicorn
        uvicorn.run("app.api.routes:app", host="0.0.0.0", port=8000, reload=True)
    else:
        # CLI interactive mode (default)
        asyncio.run(cli_loop())

async def cli_loop():
    agent = build_agent()  # wire up all dependencies
    print("Personal AI Agent ready. Type 'quit' to exit.")
    while True:
        user_input = input("\n> ")
        if user_input.lower() in ("quit", "exit"):
            break
        response = await agent.run(user_input, conversation_id="cli-session")
        print(f"\n{response.content}")
```

### 7. Configuration (`app/config.py`)
```python
class Settings(BaseSettings):
    # LLM
    llm_provider: str = "anthropic"          # "anthropic" | "openai" | "litellm"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    model_name: str = ""                     # Fill based on provider (leave flexible)
    max_iterations: int = 10

    # Memory
    db_path: str = "memory.db"
    memory_dir: str = "./memory"             # markdown memory directory

    # RAG (optional, disabled by default)
    rag_enabled: bool = False
    embedding_provider: str = "none"         # "none" | "openai" | "local"
    embedding_model: str = ""
    embedding_api_key: str = ""
    vector_store: str = "none"               # "none" | "chroma" | "qdrant"

    # General
    log_level: str = "INFO"
    verification_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env")
```

### 8. Tests (`tests/`)
- `conftest.py`:
  - Fixture: in-memory SQLite (`:memory:`)
  - Fixture: temp directory for markdown memory
  - Fixture: MockLLMClient that returns a predictable end_turn response
- `test_smoke.py`:
  - **1 test**: `test_agent_completes_one_react_loop`
    - Build agent with mock LLM + DummyTool + in-memory stores
    - Send a message → assert agent returns a response without crashing
    - Assert working memory has 2 entries (user + assistant)

### 9. README.md Template
Pre-build with these sections:

```markdown
# Personal AI Agent

> A modular AI agent with tool use, 3-tier memory, and self-verification.

## Architecture

[mermaid diagram showing: User → API/CLI → AgentExecutor → LLM
                                              ↕           ↕
                                          ToolRegistry  MemoryManager
                                                        ↕
                                              Working / Markdown / SQLite+RAG]

## Quick Start
pip install -r requirements.txt
cp .env.example .env  # fill API keys
python -m app.main              # CLI mode
python -m app.main --api        # API mode (FastAPI on :8000)

## Design Decisions
- **No LangChain**: Raw SDK for full control and debuggability
- **3-Tier Memory**: Cognitive-inspired architecture (working/episodic/persistent)
- **RAG as Plugin**: Interface-only by default, zero overhead when disabled
- **LLM Abstraction**: Protocol-based, swap providers in 1 line
- **Prompt-as-Config**: Markdown files in prompts/, no hardcoded strings

## Trade-offs
- [Fill based on challenge]

## What I Would Build Next (with more time)
- Vector-backed semantic memory (ChromaDB/Qdrant behind the existing interface)
- Streaming responses via SSE
- Multi-agent orchestration
- Conversation branching and rollback
- Observability dashboard (token usage, tool call traces)
```

## Code Style
- Type hints everywhere
- Google-style docstrings
- Async/await consistently
- Logging with stdlib `logging`
- No print statements (except CLI mode user-facing output)
- Constants in UPPER_SNAKE_CASE

## Critical Rules
- **NO LangChain, NO LlamaIndex, NO CrewAI** — raw SDK only
- Every module must be independently importable and testable
- **Dependency injection** over global state
- All I/O operations must be async
- Error handling: **never let exceptions crash the agent loop**, catch and log gracefully
- **LLM provider must be swappable** via config, not hardcoded
- **NoOp defaults everywhere**: RAG disabled? NoOpVectorStore. No API key? Graceful error.
```

---

## 七、Pre-built 代码量估算

| 模块                                 | 预估行数      | 说明                             |
| ---------------------------------- | --------- | ------------------------------ |
| `llm/` (base + 2 clients)          | ~120行     | Protocol + Anthropic + OpenAI  |
| `tools/` (base + registry + dummy) | ~80行      | ABC + Registry + 1 DummyTool   |
| `memory/` (全部)                     | ~250行     | 3层 + RAG接口 + factory + manager |
| `agent/` (core + verifier)         | ~100行     | ReAct骨架 + Verifier框架           |
| `main.py` + `config.py`            | ~60行      | 双模式入口 + Settings               |
| `api/routes.py`                    | ~40行      | 3个endpoint空壳                   |
| `tests/`                           | ~50行      | conftest + 1 smoke test        |
| `prompts/`                         | ~10行      | 空md文件                          |
| **Total**                          | **~710行** | 目标500-800行 ✓                   |

## 八、使用方式

1. **现在**：复制第六节的prompt → Claude Code 生成脚手架 → push到private repo
2. **Rehearsal**：用假题目跑一次完整60分钟流程，验证delta可完成
3. **正式开题**：clone repo → 读题 → Layer 2 增量实现 → 提交
