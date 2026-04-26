# MiAO AI Coding Challenge — 脚手架准备文档 v3.2

> **Challenge**: Personal AI Agent with Tool Use, Memory & Self-Verification
> **时限**: 60 分钟 | **工具**: Claude Code / Cursor
> **本质**: 给 Claude Code/Cursor 执行的提示词文档。用**自然语言约束**告诉 LLM 要做什么、禁忌什么、怎么验收。**不替 LLM 写代码**——写得越多越容易在示例里再次犯错。
> **方法论沉淀**: 五轮评审的完整演进、辩论纪要、修订对照、致谢——抽离到 [`docs/评审历程档案.md`](./评审历程档案.md)（关注点分离：本文档纯指令、档案给人看）

---

## ⚠️ 阅读须知

- **第六节** "脚手架 Prompt" 是给 Claude Code/Cursor 的输入。**只规定行为契约和反模式**，让 LLM 自己思考实现。
- 仅在**接口契约**层面（Type 定义、SQL DDL、配置常量）保留代码——这些不写就有歧义。
- **第七节** "Critical Rules" 是 17 条不可违反的红线铁律。
- **第八节** "雷区清单" 汇总了五轮评审中 Codex 和 Gemini 抓到的所有反模式（共 31 条）。Claude Code 必须主动避开。
- **第九节** "Acceptance Criteria" 是提交前的自检门禁。

---

## 一、背景

MiAO AI** 是新加坡游戏公司 MiAO（2022年成立，51-200人）于 **2026年初** 拆分出的独立AI Agent子公司。LinkedIn显示仅2名关联员工，官网只有一页Rich Sutton引言。公司自称"100% AI driven, no middle management"，JD中宣称的"SGD 95M融资"实为游戏母公司的融资额。

**面试流程完全由AI驱动**：简历筛选→邮件调度→AI Agent语音面试（Lark会议）→面试结束2分钟内自动发送"恭喜通过"邮件→自动发放60分钟Coding Challenge链接。全程未与任何真人交流。

**Coding Challenge规则**：

- 点击Start后60分钟倒计时，不可暂停
- 需确认GitHub账户（面试官可能review commit history）
- 72小时内有效

**本文档目的**：在打开题目之前，预先搭建一个**通用Agent脚手架**（Layer 1），push到private repo。开题后只做增量delta（Layer 2），确保60分钟内完成。

**任务**：60 分钟内构建一个 Personal AI Agent，含 4 个核心模块。

**部署假设（强制声明）**：
本 Agent 是 **single-user Personal Agent**。所有持久化记忆（`profile.json` / `learned_facts.md` / SQLite messages 表）都属于**单一用户**，**禁止**在未引入 `user_id` 作用域改造的前提下让多用户共享同一实例——否则会出现严重的 Data Bleed（用户画像跨账号写穿）。如果题目额外要求多用户支持，**必须先**把 Tier 2 持久层从全局文件改为 `users/{user_id}/profile.json` 作用域设计，并在 SQLite `messages` 表增加 `user_id TEXT` 列并加索引；**不能**靠运行时分桶绕过文件级隔离。

**策略**：

1. **Pre-game**（无时限）：用 Claude Code 生成通用脚手架 Layer 1，3 个测试文件全部通过（含 Test 1-5 共 5+ 项核心断言）
2. **开题后**（60 分钟）：clone repo → `git init` 全新仓库 → 实现 Layer 2 delta → 提交

> 用户已声明开题后会 `git init` 重建仓库，**不讨论 commit history 合规性**，**只讨论技术正确性**。

---

## 二、题目拆解

```
4 个核心模块：
1. Agent Core     — ReAct + RepeatedFailureDetector（防幻觉循环，按 conv_id 分桶）
2. Tool Use       — ToolSpec 中间格式 + Client 双向消息翻译 + 自动 to_thread + 单轮多 tool_calls 按 id 回填
3. Memory         — Working（conv_id 分桶）+ Markdown（asyncio.Lock + atomic write）+ SQLite + 单 Retriever
4. Self-Verify    — 三层校验：tool_results 硬规则 → profile 强校验（带 metadata schema）→ LLM 软兜底（Structured Outputs + 抽样）
```

---

## 三、技术选型

| 方案                   | 优点          | 缺点                 | 60 分钟适配度 |
| -------------------- | ----------- | ------------------ | -------- |
| **FastAPI + 原生 SDK** | 轻量、全控、易调试   | 手搓工具循环             | ★★★★★    |
| LangChain/LangGraph  | 内置 agent 模式 | 重抽象、调试噩梦、版本地狱      | ★★☆☆☆    |
| CrewAI/AutoGen       | 快速出 agent   | 太 opinionated、定制困难 | ★★★☆☆    |
| 纯 CLI 脚本             | 最简单         | 不够工程化、没 API        | ★★★☆☆    |

**最终选型**：

- **LLM**：内部 `CanonicalMessage` + `ToolSpec`，AnthropicClient/OpenAIClient 各自完整双向翻译（Anthropic Messages API / OpenAI Chat Completions API，禁止 Responses API 变体）
- **API**：FastAPI（薄 API 层）+ CLI 双模式入口
- **Memory**：三层架构（Working with conv_id + Markdown with lock + atomic write + SQLite）+ 单一 Retriever 接口
- **测试**：3 个测试文件 / 5+ 项核心断言（provider 翻译 + tool roundtrip + 多 tool_calls / 会话隔离 / verifier 持久化）

---

## 四、设计原则

```
KISS:  不用任何框架抽象，原生 SDK 直接调
DRY:   BaseTool + Registry 模式消除重复
SOLID: 依赖注入，Protocol 抽象，LLM/Memory/Retriever 全部可替换
YAGNI: Layer 1 只放接口和 NoOp 默认；具体 RAG provider 推迟到 Layer 2
```

**三大附加铁律**：

- **Contract Honesty**：抽象层不准撒谎。声称兼容 X 和 Y → 必须有真测试证明
- **Conversation Isolation**：所有有状态组件按 `conversation_id` 分桶（含 RepeatedFailureDetector）
- **Hard Truth Before Soft Truth**：verifier 优先工具结果和结构化数据，LLM 软校验作为最后兜底

---

## 五、Pre-game 策略

```
Pre-game (无时限):
  通用 agent 骨架跑通 + 3 个测试文件全部通过（5+ 项核心断言）→ push 到 private repo
        ↓
开题 (60 min):
  00-03min  读题 → 决策（哪些工具/记忆需求/RAG 是否启用/provider 选择）
  03-08min  git init 全新仓库 → 拷贝 Layer 1 骨架
  08-43min  Layer 2 增量实现（具体 Tool/prompt/可选 RAG provider）
  43-55min  跑通端到端 + 修 bug
  55-60min  补 README Trade-offs → 提交
```

### ⚡ Rehearsal（排练）

正式开题前用假题目跑一次完整 60 分钟流程，**重点排练 5 件事**：

1. **Provider 切换**：Anthropic ↔ OpenAI 各跑一次，schema 翻译不爆
2. **多会话隔离**：API 模式下并发 2 个 conversation 互不污染（含 detector 计数器）
3. **Tool 同步包裹**：故意写 `time.sleep(3)` 的 tool 不卡 Event Loop
4. **完整 tool roundtrip**：双 provider 各跑一次完整 [user → tool_use → tool_result → end_turn] 流程，**OpenAI 用 Chat Completions API 不能 400**
5. **时间预算**：记录 Layer 2 增量实际耗时，验证 35 分钟（08-43min）是否够用；如超时，识别哪些 Layer 1 功能在 rehearsal 中出了问题需修补

### Layer 分层策略

#### Layer 1: Pre-built（通用骨架）

```
✅ LLMClient Protocol + AnthropicClient + OpenAIClient（各自完整双向消息翻译，OpenAI 钉死 Chat Completions API）
✅ CanonicalMessage 内部 IR（provider-neutral 字段命名 tool_call_id）+ ToolSpec + ToolCall + LLMResponse
✅ BaseTool ABC + ToolRegistry（含 to_thread 自动包裹）+ DummyTool
✅ 三层 Memory（WorkingMemory dict[conv_id, deque] + MarkdownMemory with Lock + atomic write + SQLiteStore ISO 8601）
✅ Retriever 接口 + NoOpRetriever（具体 provider 推迟 Layer 2）
✅ MemoryManager（含 token budget + top_k + working_msgs 进主链路）
✅ AgentExecutor（ReAct + RepeatedFailureDetector 按 conv_id 分桶）
✅ SelfVerifier（三层 + Stage 2 metadata schema + Stage 3 Structured Outputs + 抽样路径）+ revised_answer 持久化
✅ FastAPI 路由空壳 + CLI 入口（双模式）
✅ build_agent() 显式 DI wiring（factory.py）
✅ conftest.py + 3 个测试文件（含 5+ 项核心断言，**禁止 `pass` 占位**）
✅ prompts/ 目录（占位 md 文件）
✅ README（含真实 mermaid + 多 worker 警告 + single-user assumption）
✅ .env.example + requirements.txt
```

#### Layer 2: 开题后做（60 分钟 delta）

```
🔧 读题 → 实现具体 Tool（继承 BaseTool）
🔧 题目要 RAG？→ 在 memory/providers/ 下补具体 Retriever 实现
🔧 题目要 FTS5？→ 在 sqlite_store.py 加 FTS5 表
🔧 写 prompts/system.md + prompts/verifier.md
🔧 选 LLM provider → 配置 .env
🔧 跑通端到端 case
🔧 补 README Design Decisions + Trade-offs
```

---

## 六、脚手架 Prompt（复制到 Claude Code / Cursor 执行）

```markdown
# Task: Scaffold a "Personal AI Agent" Python project (v3.2)

## Project Overview

构建一个模块化、生产质量的 Python 脚手架，为 Personal AI Agent 服务。这是**通用骨架**——具体工具、提示词、RAG provider 在 Layer 2 添加。

**最高原则**（不可违反）：**Every abstraction must be honest**——任何声称"provider-agnostic"或"compatible with X and Y"的层，必须有真实测试证明。任何在伪代码或注释里写"X converts as needed"但实际没实现转换逻辑的反模式，都是禁止的。

核心能力：
1. **Tool Use** — 基于 registry 的工具调用，使用内部 `ToolSpec` + 各 provider 独立翻译
2. **Memory** — 3 层记忆（Working with conv_id 分桶 + Markdown with file lock + atomic write + SQLite），可插拔 Retriever
3. **Self-Verification** — 3 层校验：tool_results 硬规则 → structured profile 强校验（带 metadata schema）→ LLM 软兜底（Structured Outputs + 抽样）

## Tech Stack
- Python 3.11+
- FastAPI（薄 API 层，可选 `--api` flag）
- anthropic + openai SDKs
- aiosqlite, aiofiles
- pydantic v2 + pydantic-settings
- pytest + pytest-asyncio（**3 个测试文件含 5+ 项核心断言，禁止 `pass` 占位**）
- uvicorn, python-dotenv

## Project Structure（必须严格按此目录布局）
```

personal-ai-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Dual entry: CLI (default) + FastAPI (--api)
│   ├── factory.py              # build_agent(): 显式 DI wiring
│   ├── config.py               # Settings + DEFAULT_MODELS
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py           # POST /chat, GET /memory, GET /health
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── core.py             # AgentExecutor: ReAct + RepeatedFailureDetector
│   │   └── verifier.py         # SelfVerifier: 3-stage check
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py             # CanonicalMessage + ToolSpec + ToolCall + LLMResponse + LLMClient Protocol
│   │   ├── anthropic_client.py # 完整双向翻译（含 tool roundtrip）
│   │   └── openai_client.py    # 完整双向翻译（含 tool roundtrip）
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py             # BaseTool ABC
│   │   ├── registry.py         # ToolRegistry: 自动 to_thread
│   │   └── dummy.py            # DummyTool
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── manager.py          # MemoryManager
│   │   ├── working.py          # dict[conv_id, deque]
│   │   ├── markdown_store.py   # asyncio.Lock + JSON profile + atomic write
│   │   ├── sqlite_store.py     # ISO 8601
│   │   ├── retriever.py        # Retriever Protocol + NoOpRetriever
│   │   └── providers/          # Layer 2 fill
│   │       └── __init__.py
│   └── models/
│       ├── __init__.py
│       └── schemas.py
├── prompts/
│   ├── system.md               # 占位
│   ├── verifier.md             # 占位
│   └── memory_extract.md       # 占位
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_provider_translation.py  # 含完整 tool roundtrip 测试
│   ├── test_memory_isolation.py
│   └── test_verifier_persistence.py  # 真断言，禁止 `pass` 占位
├── memory/                     # gitignored
│   └── .gitkeep
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml
└── README.md

```
## Required Internal Type Contracts（必须使用这些精确类型）

```python
# app/llm/base.py
@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict          # JSON Schema

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall]
    stop_reason: str          # "end_turn" | "tool_use"
    raw: Any = None

@dataclass
class CanonicalMessage:
    """Internal canonical message format. NEVER pass provider-specific dicts directly to a Client.

    Field naming is provider-NEUTRAL. We use `tool_call_id` (NOT `tool_use_id`) deliberately to
    avoid Anthropic-term leakage into the internal IR — a leak would re-bias implementers toward
    'think Anthropic first, OpenAI as fallback' and is a recurring contract-honesty pitfall.
    """
    role: str                 # "user" | "assistant" | "tool_result"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None  # only for assistant role
    tool_call_id: str | None = None           # only for tool_result role; provider-neutral name
```

```python
# app/agent/verifier.py
@dataclass
class VerificationResult:
    is_valid: bool
    confidence: float
    issues: list[str]
    revised_answer: str | None    # if not None, replaces original answer
```

```sql
-- SQLite schema
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL  -- ISO 8601 with timezone
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);

CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    fact            TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_conv ON facts(conversation_id);
```

```python
# app/config.py
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
}
```

## Module Behavioral Contracts（用自然语言约束，自行决定实现）

### 1. LLM Clients (`app/llm/`)

**铁律**（绝不违反）：

- **OpenAI 接口面钉死**：`OpenAIClient` **必须**使用 **Chat Completions API**（`messages` + `tools` + `message.tool_calls` + `role="tool"` + function tool schema 形态），**禁止**使用 Responses API（`input` + `output` 形态）变体。Responses API 的 tool_call 协议不同 → mock SDK roundtrip 通过但接真实 SDK 时立刻协议漂移。Anthropic 端使用标准 Messages API（`tool_use` / `tool_result` content blocks）。
- 内部只流通 `CanonicalMessage` + `ToolSpec`。**禁止任何上游代码（agent core / tool registry / verifier）直接产出 Anthropic / OpenAI 私有格式字典**
- 每个 Client（`AnthropicClient` / `OpenAIClient`）必须**独立完成**完整双向翻译——不仅是 tool spec，还包括完整的 message roundtrip：
  - **入站翻译（必须完整）**：把 `system: str` + `messages: list[CanonicalMessage]` + `tools: list[ToolSpec]` 转成 SDK 接受的格式。包括：tool spec 形状、message 结构、role 命名、tool_call 字段、tool_result 包装、system prompt 注入位置（Anthropic 单独参数 / OpenAI messages[0]）
  - **出站翻译（必须完整）**：把 SDK 返回值标准化为 `LLMResponse`。包括：抽取 text content、抽取 tool_calls（Anthropic content blocks / OpenAI message.tool_calls）、统一 stop_reason 命名（`"end_turn"` / `"tool_use"`）

**禁止的反模式**（评审抓到的真实雷点）：

- 写一个全局函数 `format_tool_result_message()` 偏向 Anthropic 格式，然后让 OpenAIClient「convert as needed」——如果 OpenAIClient 没有真的 convert，第一笔工具调用就 400 Bad Request
- 在 Client 之外的层产出私有格式字典再传给 Client
- 单方法假装兼容（v2 `to_schema()` 的反模式）

**单轮多 tool_calls 契约**（Critical）：

- 一个 assistant turn 可能同时返回**多个** `ToolCall`（并行工具调用）
- 后续 `tool_result` 消息**必须**按 `ToolCall.id` 精确回填，**禁止**依赖顺序、位置或 zip 配对来匹配
- 双 provider Client 都必须正确处理：
  - **入站**：把 `list[CanonicalMessage]` 中多个 `tool_result`（每个携带 `tool_call_id`）按 id 串接成 SDK 格式（Anthropic 多 `tool_result` content blocks / OpenAI 多个 `role="tool"` 消息带 `tool_call_id`）
  - **出站**：把 SDK 返回的多 tool_call 全部抽出为 `LLMResponse.tool_calls: list[ToolCall]`，**禁止**只取第一个
- 实现者切勿假设"一次只有一个 tool_call"——这是隐性陷阱

**验收标准**：`tests/test_provider_translation.py` 必须包含：

- 完整 tool-use roundtrip 集成测试（mock SDK 也行），覆盖 Anthropic + OpenAI 双方都能跑通完整 [user_msg → assistant_tool_call → tool_result → assistant_end_turn] 流程
- **单轮多 tool_calls 测试**：单轮 assistant 同时返回 2 个 ToolCall（不同 id 不同 name），传 2 个对应的 `tool_result` 按 id 回填，双 provider 各跑一遍验证不串号、不丢消息、顺序对应正确

### 2. Tool System (`app/tools/`)

- `BaseTool` 抽象类提供 `name`, `description`, `parameters() -> dict`, `execute(...)`（同步或异步）, 基类实现的 `to_spec() -> ToolSpec`
- `ToolRegistry` 提供 `register / get / specs / list_tools / execute(name, input) -> str`
- `ToolRegistry.execute` **必须**用 `inspect.iscoroutinefunction` 检测 execute 类型，**同步函数自动用 `asyncio.to_thread` 包裹**
  - **禁止假设所有 tool 都是 async**——这是 v2 的反模式
- 异常**必须**捕获并返回 `"ERROR: ..."` 字符串，不准 raise 出 registry
- 仅 pre-build `DummyTool`（返回 `"dummy ok"`）作为 smoke

### 3. Memory System (`app/memory/`)

#### Tier 1 — `WorkingMemory`

- 数据结构：`dict[str, deque[CanonicalMessage]]`，按 `conversation_id` 分桶，每桶 `maxlen` 可配（默认 50）
- 接口：`append(conv_id, msg)` / `get_messages(conv_id)` / `clear(conv_id | None)`
- **禁止全局 `_messages: list`**——这是 v2 最大的硬伤之一

#### Tier 2 — `MarkdownMemory`

- 文件布局：
  - `profile.json`（结构化 key-value，**JSON 不是 markdown**——markdown 不适合原子 update）
  - `learned_facts.md`（append-only natural-language facts）
  - `conversations/{conv_id}/summary.md`（一次性写入）
- **隔离域声明**：`profile.json` 和 `learned_facts.md` 是 **single-user 全局文件**。本脚手架默认 single-user 假设。如果题目要求多用户，**必须先**改造为 `users/{user_id}/profile.json` 等用户作用域路径——否则用户画像会跨账号写穿（Data Bleed），属于严重隐私事故。
- 所有写操作**必须**用 `asyncio.Lock` 保护
- **Atomic Write 铁律**：所有 `profile.json` / `learned_facts.md` 写入**必须**走 atomic write 模式（先写 `{path}.tmp` → `os.replace({path}.tmp, {path})` 原子覆盖），**禁止**直接 `open(path, 'w')` 后 truncate 写入。进程在写入中途被 kill / Uvicorn worker 异常退出 / 断电 → JSON 文件会变成损坏的半成品且不可恢复，相当于把整份用户画像清零。
- **Lock 实例化位置铁律**：`asyncio.Lock` **必须**作为 `MarkdownMemory` 的 instance attribute（在 `__init__` 中创建），**禁止**在 Request Handler / route 函数 / 方法局部内 `new` 新 Lock。局部 Lock 在不同请求间不共享 → 完全失效，并发写还是会破坏 `profile.json`。这条规则必须用并发文件写入测试验证（见 Acceptance Criteria）。
- 提供：`get_profile() / update_profile(k, v) / append_fact(s) / save_summary(conv_id, s) / get_top_k_facts(k=5)`
- **profile 字段 metadata schema 闭合铁律**：`update_profile(key, value)` 写入的 `value` **必须**是符合 Stage 2 verifier 期望的 metadata 形态：`{"value": <实际值>, "type": "number"|"date"|"enum"|"text", "tolerance"?: <数字>, "values"?: [<枚举值>]}`。**禁止**用平面 KV 存（如 `update_profile("age", 28)` 直接存数字 28）——否则 Stage 2 强校验拿不到 type 信息会全部跳过到 Stage 3 软兜底，让 Stage 2 形同虚设。`get_profile()` 返回的也必须是带 metadata 的完整结构。
- **README 必须明确警告**：`asyncio.Lock` 只解决单进程并发。多 Uvicorn worker 或 API + CLI 同跑情况下，必须额外引入 `filelock`（跨进程锁），否则禁用此组件

#### Tier 3 — `SQLiteStore`

- 用 `aiosqlite`
- 接口：`initialize() / save(conv_id, role, content, metadata) -> int / get_history(conv_id, limit) -> list / keyword_search(query, limit) -> list`
- 时间戳**必须**用 `datetime.now(timezone.utc).isoformat()`
- 默认无 FTS5（Layer 2 题目要求时再加）

#### `Retriever` 接口

- 单一 Protocol：`async def add(doc_id, text, metadata) / async def search(query, limit) -> list`
- 默认实现 `NoOpRetriever`（add 空操作，search 返回 `[]`）
- 具体 provider（OpenAIRetriever / ChromaRetriever）推迟到 Layer 2 的 `memory/providers/`

#### `MemoryManager` —— 必须真正接入主链路

- 接口：
  - `get_context(conv_id, max_chars=4000, top_k_facts=5, history_limit=10) -> tuple[str, list[CanonicalMessage]]`
    - 返回元组的两个字段都**必须**被 `AgentExecutor` 真正使用
    - 第一个进 system prompt，第二个进 messages 序列开头
  - `after_turn(conv_id, user_msg, agent_response)`
    - **持久化 verifier 校正后的最终答案，不是初稿**
    - Fact extraction 必须用 `asyncio.create_task` fire-and-forget
- `get_context` 必须有 `max_chars` 截断
- **禁止反模式**：`load all md files` 无 budget——v2 的反模式

### 4. Agent Core (`app/agent/core.py`)

- `AgentExecutor.run(user_message, conversation_id) -> CanonicalMessage` 异步方法
- 实现 ReAct 循环（最多 `max_iterations` 次，默认 10）
- 每次工具调用前**必须**经 `RepeatedFailureDetector.record(tool_name, tool_input)` 记录
- `RepeatedFailureDetector`：连续 N 次（默认 3）相同 (name + json input) → `should_intervene()` 返回 True → 注入 `[SYSTEM] You called X with same input N times. Try a DIFFERENT approach.` → 重置 detector
- **Detector 作用域铁律**：`RepeatedFailureDetector` 的内部计数器**必须**按 `conversation_id` 严格隔离——推荐两种实现之一：(a) `dict[conv_id, Detector]` 按 conv_id 分桶（推荐，状态可跨 turn 累积）；(b) 每次 `AgentExecutor.run()` 调用时**新实例化**一个 Detector（简单但跨 turn 累积失效）。**禁止**在 `AgentExecutor.__init__` 内 `self.detector = RepeatedFailureDetector()` 然后所有会话共用——FastAPI 高并发场景下不同 conversation 的失败计数会互相污染，触发灾难性误拦截。
- `end_turn` 时：调用 `SelfVerifier.verify` → `final_answer = verification.revised_answer or response.content` → 通过 `MemoryManager.after_turn` 持久化 final
- 异常处理：LLM/tool 异常**必须**捕获并降级，**绝不允许冒泡导致 agent 进程挂掉**

**主链路顺序铁律**：

- `SelfVerifier.verify` **必须 await 阻塞**主响应链路。verifier 的核心职责就是**拦截幻觉并输出 `revised_answer` 替换初稿**——把它扔到 `asyncio.create_task` 异步执行 = 修正答案永远拿不到 = 等于白干 verifier
- 提速依赖 verifier 内部的 Stage 1/2 短路（无 LLM、纯确定性规则）+ Stage 3 抽样限制（默认 0.1），**而不是把 verifier 整体异步化**
- 反向铁律见 `MemoryManager.after_turn`：fact extraction / memory 总结等**非关键路径必须** fire-and-forget（`asyncio.create_task`）。颠倒这两者会同时毁掉正确性和延迟：异步 verifier → 修正丢失；同步 fact extraction → TTFB 翻倍

**关键**：把 `working_msgs`（来自 `MemoryManager.get_context`）真正拼进 LLM 调用的 messages 列表头部。**禁止只用 system_ctx 字符串而忽略 working_msgs**——这是 v2 的反模式。

### 5. Self-Verifier (`app/agent/verifier.py`) — 三层校验

#### Stage 1 — `tool_results` 硬规则（确定性，无 LLM）

- 检测 `tool_results` 中含 `"ERROR"` 但 answer 包含成功语义词的矛盾
- **不能**只匹配单一关键词字符串。建议用语义词集（`successfully` / `已完成` / `done` / `成功` / `好了`）+ 否定前缀检测（`未`、`没` 等）
- 如果工具是数据返回型（不是动作型），还要检查 answer 是否引用了 tool 实际返回的数据点

#### Stage 2 — structured `profile.json` 一致性（确定性，无 LLM）

- **禁止反模式**：用 `key in answer and str(value) not in answer` 这种字符串包含校验。**这种太脆，漏报误报多**
- **必须**按字段类型做强校验：
  - **数字字段**：从 answer 用正则抽数字 → 与 profile 值比较（容许误差由 metadata 配置）
  - **日期字段**：解析日期 → 比较
  - **枚举字段**：白名单精确匹配
  - **自由文本字段**：跳过 Stage 2，交给 Stage 3
- profile 字段需要 metadata 描述类型（与 `MarkdownMemory.update_profile` 写入形态严格一致），例如：
  
  ```json
  {
    "timezone": {"value": "UTC+8", "type": "enum", "values": ["UTC+8", "UTC-5", ...]},
    "age": {"value": 28, "type": "number", "tolerance": 0}
  }
  ```

#### Stage 3 — LLM 软兜底

- 触发条件**至少**两条独立路径（**禁止只在 Stage 1-2 命中后才触发**）：
  - **路径 A（被动）**：Stage 1-2 命中 issues → 必触发（除非 `soft_fallback=False`）
  - **路径 B（主动抽样）**：对**高风险答案**按 `verifier_sampling_rate`（默认 0.1）抽样复核，独立于 Stage 1-2
    - 高风险定义：含数字、含承诺动词（"将会"、"保证"、"一定"）、长度超阈值（默认 200 字）
- 输入：question + answer + tool_results + issues + profile
- 输出 JSON：`{is_valid, confidence, issues, revised_answer}`
- **Structured Outputs 铁律**：Stage 3 LLM 调用**必须**使用 SDK 原生 Structured Outputs 能力强制 JSON 输出——OpenAI 端用 `response_format={"type": "json_schema", "json_schema": {...}}`，Anthropic 端用强制 Tool Use（定义一个 `submit_verification` 工具让模型必须 call）。**禁止**只在 prompt 里写"请输出 JSON"然后强解析——LLM 极易加 markdown 围栏 / 解释性废话 / 转义错误，生产环境裸解析失败率 5-15%。
- 解析必须健壮（fallback 兜底，不替代 Structured Outputs）：容忍 code-fenced JSON、容忍解析失败 fallback 到 `VerificationResult(False, 0.5, fallback_issues, None)`

### 6. Dual Entry (`app/main.py`) + Explicit DI (`app/factory.py`)

- `main.py` 检测 `--api` flag → uvicorn 启动 / 否则 CLI 交互循环
- `factory.py` **必须**提供 `async def build_agent(settings: Settings) -> AgentExecutor`：
  - 根据 `settings.llm_provider` 选 Anthropic 或 OpenAI Client，model 用 `settings.resolved_model()`
  - 装配 Memory 三层 + NoOpRetriever
  - 装配 ToolRegistry + DummyTool
  - 装配 SelfVerifier
  - 返回 AgentExecutor，所有依赖**显式注入**
- **禁止**：模块级全局可变 agent 实例

### 7. Configuration (`app/config.py`)

- `Settings(BaseSettings)` 至少包含：
  - LLM: `llm_provider` / `anthropic_api_key` / `openai_api_key` / `model_name (空字符串则 fallback)` / `max_iterations`
  - Memory: `db_path` / `memory_dir` / `working_max_per_conv`
  - RAG: `rag_enabled` / `retriever_provider`
  - Verifier: `verification_enabled` / `verifier_soft_fallback` / `verifier_sampling_rate`
  - General: `log_level`
- `resolved_model() -> str` 返回 `model_name or DEFAULT_MODELS[provider]`
- `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`

### 8. Tests (`tests/`) — 3 个测试文件 / 5+ 项核心断言

#### `test_provider_translation.py`

- **测试 1**：`AnthropicClient._to_anthropic_tool(spec)` 输出 `{"name", "description", "input_schema"}` 形状
- **测试 2**：`OpenAIClient._to_openai_tool(spec)` 输出 `{"type": "function", "function": {"name", "description", "parameters"}}` 形状
- **测试 3**：两者输出对同一 spec **不相等**（contract honesty 硬证据）
- **测试 4（必须有）**：完整 tool-use roundtrip 集成测试（mock SDK），双 provider 各跑一次完整 [user_msg → tool_use → tool_result → end_turn] 流程，验证 message 和 tool_result 在两边都能正确 marshal/unmarshal
- **测试 5（必须有）**：单轮多 tool_calls 测试。Mock LLM 返回**单个 assistant 消息含两个 ToolCall**（不同 id 不同 name），随后传两个对应的 `tool_result` `CanonicalMessage`（按 id 不按位置匹配）。验证：
  - 双 provider 都能正确入站翻译成 SDK 多 tool_call 格式
  - 双 provider 都能正确出站把 SDK 返回的多 tool_call 抽成 `LLMResponse.tool_calls`
  - 把回填的 tool_result 串到下一轮 LLM 输入时不串号、不丢消息

#### `test_memory_isolation.py`

- 测试 conv-A 和 conv-B 互不污染
- 测试 `clear("conv-A")` 不影响 conv-B
- 测试 deque maxlen 截断行为

#### `test_verifier_persistence.py`（**禁止 `pass` 占位**）

- 端到端：mock LLM 返回 "wrong"，mock verifier 返回 `revised_answer="right"`
- 调用 `agent.run(...)` 后断言：
  - 返回内容是 "right"，**不是** "wrong"
  - SQLite 持久化的 assistant content 是 "right"
  - WorkingMemory 中存的也是 "right"
- **fixture 必须避免反模式**：禁止 `SQLiteStore(":memory:")` + 多次 connect（`:memory:` 跨连接不共享数据）。改用 `tmp_path / "test.db"` 临时文件 DB

### 9. README

- **真实** mermaid 流程图（不是占位符 `[mermaid diagram showing: ...]`——v2 的反模式）
- Quick Start 命令行可执行
- Design Decisions 列核心哲学：
  - Honest abstractions
  - Conv_id isolation（含 RepeatedFailureDetector）
  - 3-stage verifier with metadata schema + Structured Outputs + sampling
  - Async safety by default + atomic write
  - Pluggable Retriever
  - Prompt-as-config
  - DI in factory.py
  - Single-user assumption（多用户需 `users/{user_id}/` 改造）
- **必须明确警告**：多 Uvicorn worker 部署需引入 `filelock` 或禁用 MarkdownMemory
- Trade-offs 章节占位
- "What I Would Build Next" 列 5 项

## Code Style

- Type hints everywhere
- Google-style docstrings
- Async/await consistently
- Logging with stdlib `logging`（**NOT print**，除 CLI 模式用户输出）
- Constants in UPPER_SNAKE_CASE

---

## 七、Critical Rules（v3.2 hardened — 不可违反的 17 条铁律）

> 这些铁律是五轮辩论的核心成果，是 Claude Code 必须坚守的红线。

1. **NO LangChain, NO LlamaIndex, NO CrewAI** — raw SDK only
2. **No abstraction shall lie** — 声称兼容必须有真测试证明（包括完整 tool roundtrip）
3. **Every conv_id must be honored** — 禁止全局可变状态共享对话（含 RepeatedFailureDetector）
4. **Hard truth before soft truth** — verifier 优先 `tool_results` 和 structured data
5. **Sync I/O must be wrapped** — `asyncio.to_thread` for sync execute, `asyncio.Lock` for shared file（**Lock 必须挂在 instance attribute 上，禁止 Request Handler 局部 new**）
6. **Persist FINAL answer, not initial** — `after_turn` 用 `verifier.revised_answer or original`
7. **Default models in config** — `DEFAULT_MODELS` per provider
8. **DI in factory.py** — 禁止隐式全局
9. **Never crash agent loop** — try/except + 降级返回
10. **No `pass` placeholder tests** — 每个测试必须真断言
11. **No `:memory:` + multi-connect SQLite fixture** — 用临时文件 DB
12. **Provider-neutral IR field naming** — 内部 IR `CanonicalMessage` 必须用 provider 中立字段名（`tool_call_id` 而非 `tool_use_id`），禁止 Anthropic/OpenAI 术语泄漏到中立层
13. **Multi tool_calls roundtrip by id** — 单轮多 ToolCall 必须按 `id` 严格回填 tool_result，禁止依赖顺序、位置或 zip 配对
14. **Verifier blocks main response, memory extraction is fire-and-forget** — 主链路顺序铁律：verifier 必须 `await` 阻塞主响应（依靠 Stage 1/2 短路 + Stage 3 抽样限制提速），fact/memory extraction 必须 `asyncio.create_task` 后台执行；颠倒会同时毁掉正确性和延迟
15. **Profile metadata schema 闭合**（v3.2 新增）— `update_profile(key, value)` 写入的 `value` 必须是 `{value, type, tolerance?, values?}` 形态。**禁止**平面 KV 存储——Stage 2 强校验需要 type 信息才能跑
16. **OpenAI must use Chat Completions API**（v3.2 新增）— `OpenAIClient` 必须使用 Chat Completions API（`messages` + `message.tool_calls` + `role="tool"`），**禁止** Responses API 变体；Anthropic 端使用标准 Messages API
17. **Atomic write for shared files**（v3.2 新增）— `profile.json` / `learned_facts.md` 等共享文件写入必须走 atomic write（`{path}.tmp` → `os.replace`），**禁止**直接 truncate 写入；崩溃中途会让 JSON 文件损坏

---

## 八、雷区清单（五轮评审抓到的反模式 — 共 31 条）

> Claude Code 实施时必须**主动避开**以下所有反模式。每条都是真实辩论中血淋淋的教训。

### 🔴 Critical（破坏 contract honesty / 数据隔离）

| #   | 反模式                                                                                             | 来源           | 为什么是雷                                                                                |
| --- | ----------------------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------ |
| C1  | `BaseTool.to_schema()` 返回单一格式但声称兼容多 provider                                                    | v2 hardcoded | OpenAI 第一笔请求 400 Bad Request                                                         |
| C2  | `format_tool_result_message()` 偏向某 provider，让另一 Client "convert as needed" 但实际未实现               | v3 草稿        | 同上，更隐蔽                                                                               |
| C3  | `WorkingMemory._messages: list[Message]` 全局共享                                                   | v2 hardcoded | API 模式下多对话互相污染                                                                       |
| C4  | `MemoryManager.get_context()` 不返回 working_msgs，或 AgentExecutor 不使用它                             | v2 hardcoded | Tier 1 名义存在实际悬空                                                                      |
| C5  | `CanonicalMessage` 用 `tool_use_id` 字段（Anthropic 术语泄漏到中立 IR）                                     | 第四轮评审        | 把实现者脑回路重新带回"先 Anthropic 后 OpenAI"的老坑——必须用 `tool_call_id` 等中立命名                       |
| C6  | 假设 assistant 一轮只返回一个 ToolCall；多 tool_calls 按位置/顺序匹配 tool_result                                 | 第四轮评审        | "单工具能过、双工具乱套"的假兼容；必须按 `ToolCall.id` 严格回填                                             |
| C7  | `profile.json` / `learned_facts.md` 全局单文件，但启用 `--api` 接受多用户                                     | 第四轮评审        | 多用户写穿同一文件 → Data Bleed → 严重隐私泄露；必须 single-user assumption 或 `users/{user_id}/` 作用域改造 |
| C8  | `update_profile(k, v)` 平面 KV 存储（如直接 `update_profile("age", 28)` 存数字 28），不带 Stage 2 期望的 metadata | 第五轮评审        | Stage 2 强校验拿不到 type/tolerance/values 全部跳过 → Stage 2 形同虚设；必须存 `{value, type, ...}` 形态 |
| C9  | OpenAI 端使用 Responses API（`input` + `output`）变体而非 Chat Completions API                           | 第五轮评审        | tool_call 协议不同 → mock SDK 通过但接真实 SDK 协议漂移；必须钉死 Chat Completions API                  |

### 🟡 High（运行时陷阱）

| #   | 反模式                                                                    | 来源           | 为什么是雷                                                                                                                                |
| --- | ---------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| H1  | 假设所有 tool execute 都是 async，没用 `inspect.iscoroutinefunction`            | v2 hardcoded | 同步 tool 阻塞 Event Loop                                                                                                                |
| H2  | 共享文件无 `asyncio.Lock`                                                   | v2 hardcoded | FastAPI 并发竞争损坏 profile.json                                                                                                          |
| H3  | `asyncio.Lock` 只解决单进程，但 README 没警告多 worker 部署                          | v3 unhandled | 多 Uvicorn worker 仍会跨进程写穿                                                                                                             |
| H4  | ReAct 循环无 RepeatedFailureDetector                                      | v2 hardcoded | 连续犯错傻等 max_iterations 次                                                                                                              |
| H5  | **主链路顺序颠倒**：verifier 异步化（绕过主响应链路）或 memory/fact extraction 同步化（挡在主响应前）  | 第四轮评审反驳      | verifier 必须阻塞才能让 `revised_answer` 替换初稿；memory extraction 必须 fire-and-forget。颠倒后果：异步 verifier → 修正答案永远丢失；同步 fact extraction → TTFB 翻倍 |
| H6  | `after_turn` 持久化初稿而非 verifier 校正后                                      | v2 hardcoded | revised_answer 永远丢失                                                                                                                  |
| H7  | `asyncio.Lock` 实例化在 Request Handler / route 函数 / 方法局部内                 | 第四轮评审        | 局部 Lock 在并发请求间不共享 → 完全失效；必须挂在 `MarkdownMemory` 的 instance attribute 上，并写并发文件写入测试验证                                                   |
| H8  | `MarkdownMemory` 写入直接 `open(path, 'w')` truncate 后写入，未走 atomic write   | 第五轮评审        | 写入中途进程被 kill / 断电 → JSON 文件损坏不可恢复，整份用户画像清零；必须 `{path}.tmp` → `os.replace` 原子覆盖                                                       |
| H9  | `RepeatedFailureDetector` 在 `AgentExecutor.__init__` 内一次性实例化，所有会话共用计数器 | 第五轮评审        | FastAPI 高并发场景下不同 conversation 失败计数互相污染 → 灾难性误拦截；必须按 conv_id 分桶或每次 run() 新实例化                                                         |

### 🟠 Medium（实现脆弱）

| #   | 反模式                                                                | 来源           | 为什么是雷                                                                                |
| --- | ------------------------------------------------------------------ | ------------ | ------------------------------------------------------------------------------------ |
| M1  | Stage 2 用 `key in answer and str(value) not in answer` 字符串包含校验     | v3 实现        | 漏报误报极多，profile 业务边界论的实现配不上                                                           |
| M2  | Stage 3 LLM 软兜底只在 Stage 1-2 命中后才触发                                 | v3 实现        | 1-2 漏掉的错误，3 永远看不到                                                                    |
| M3  | `MarkdownMemory.update_profile` 在 markdown 里更新 key-value           | v2 hardcoded | 解析+替换非平凡，60min 内极易踩坑                                                                 |
| M4  | `MemoryManager.get_context` 无 max_chars budget，load all md files   | v2 hardcoded | prompt 持续膨胀，旧记忆污染当前任务                                                                |
| M5  | 双层 RAG 接口（Embedding + VectorStore），且 `add()` 签名前后不一致               | v2 hardcoded | contract 自相矛盾，Layer 1 偏胖                                                             |
| M6  | Stage 3 仅靠 prompt 让 LLM 输出 JSON 然后强解析（无 Structured Outputs API 强制） | 第五轮评审        | LLM 加 markdown 围栏 / 解释性废话 / 转义错误，生产环境裸解析失败率 5-15%；必须用 `response_format` 或强制 Tool Use |

### 🟢 Low（测试与文档诚信）

| #   | 反模式                                                    | 来源           | 为什么是雷                    |
| --- | ------------------------------------------------------ | ------------ | ------------------------ |
| L1  | 测试用 `pass` 占位，但文档声称"3 tests pass"                      | v3 实现        | 文档自信度 > 真实完备度，过度承诺       |
| L2  | `SQLiteStore(":memory:")` + 每方法新连接                     | v3 fixture   | `:memory:` 跨连接不共享数据，测试假阳 |
| L3  | README 的 mermaid 是占位符 `[mermaid diagram showing: ...]` | v2 hardcoded | 提交时面试官看到笑话               |
| L4  | `config.model_name = ""` 默认空字符串                        | v2 hardcoded | 配置不全会传空到 API             |
| L5  | SQLite `created_at TEXT` 无格式说明                         | v2 hardcoded | 时间戳格式不一致                 |
| L6  | `build_agent()` 在 main.py 调用但未定义                       | v2 hardcoded | DI wiring 留坑             |
| L7  | 双方共识：**文档自信度 > 真实完备度**——声称的能力比代码实现的多                   | v3 meta-risk | 自我欺骗                     |

---

## 九、Acceptance Criteria（提交前必须全部通过）

- [ ] `pytest tests/` 全部通过（**没有 `pass` 占位**）
- [ ] `python -m app.main` 在 CLI 模式下能完成至少 1 个 ReAct 循环
- [ ] `python -m app.main --api` 启动后 `/health` 返回 200
- [ ] **OpenAI 和 Anthropic provider 各自能完成一次完整 tool-use roundtrip**（用 mock SDK），关键点：
  - 双 provider 都能 marshal/unmarshal `assistant tool_call` 和 `tool_result` 消息
  - 没有任何 Anthropic 私有格式漏到 OpenAIClient.call() 输入
- [ ] **OpenAI 用 Chat Completions API**：`OpenAIClient` 调用代码可静态确认走 `chat.completions.create`，不是 `responses.create`
- [ ] **单轮多 tool_calls 测试通过**：单轮 assistant 同时返回 2 个 ToolCall，2 个 tool_result 按 `id` 回填，双 provider 都不串号、不丢消息、顺序对应正确
- [ ] 多 conv_id 并发请求互不污染（验证 conv-A 的 working memory 和 conv-B 完全隔离）
- [ ] **并发文件写入锁有效性测试通过**：N 个并发请求同时调用 `update_profile`，profile.json 内容不损坏；该测试**必须**能区分"Lock 在 instance attribute"（通过）vs"Lock 在 Request Handler 局部"（失败）
- [ ] **Atomic write 验证**：`MarkdownMemory` 写操作可静态确认有 `{path}.tmp` + `os.replace`；通过 mock `os.replace` 抛异常做故障注入，验证原文件不会被 truncate 损坏（即 `.tmp` 写失败时原 `profile.json` 保持完整）
- [ ] 同步 tool（如内含 `time.sleep(1)`）不阻塞 Event Loop
- [ ] `RepeatedFailureDetector` 能识别连续 3 次相同 tool 调用并注入纠偏
- [ ] **RepeatedFailureDetector 隔离测试**：并发两个不同 conv_id 各跑 3 次相同失败工具调用，conv-A 触发拦截不影响 conv-B 计数
- [ ] verifier 校正后的 answer 真的被持久化（不是 initial）；测试中 mock verifier 返回 `revised_answer="X"` → SQLite 中存的是 X，不是初稿
- [ ] **主链路顺序正确**：`SelfVerifier.verify` 在主链路 `await` 阻塞（**禁止**异步任务）；memory/fact extraction 是 `asyncio.create_task` fire-and-forget（**禁止**阻塞主响应）
- [ ] Self-Verifier 三层都有真实路径触发：
  - Stage 1 能检测"工具失败但答案声称成功"
  - Stage 2 用强校验（按字段类型，含 metadata schema）而非字符串包含
  - Stage 3 用 SDK Structured Outputs API（OpenAI `response_format` / Anthropic 强制 Tool Use），既能被 1-2 触发，**也能通过抽样独立触发**
- [ ] **profile metadata schema 一致性**：`update_profile(k, v)` 写入的 v 是 `{value, type, ...}` 形态，且 Stage 2 verifier 实际能消费这些 metadata 字段
- [ ] **持久化作用域声明清晰**：README + Tier 2 章节明确声明 single-user assumption；如题目要求多用户，已改造为 `users/{user_id}/...` 作用域
- [ ] README 包含**真实** mermaid（不是占位符）+ 多 worker 警告 + single-user assumption
- [ ] **测试用语统一**：全文不再混用"3 个测试"和"5+ 项断言"，统一表述为"3 个测试文件 / 5+ 项核心断言"
- [ ] **雷区清单（第八节）所有反模式均未出现**——尤其是 v3.1 / v3.2 新增的 C5-C9, H5/H7-H9, M6

---

**v3.2 总评**：方向已正、铁律 17 条已立、雷区 30 条已编纂、五轮评审共 11 项工程修订（v3.1 共识 5 项 + v3.2 工程微调 6 项）已全部落地；G-C1 经主审复议采纳——评审历史抽离至 [`docs/评审历程档案.md`](./评审历程档案.md)，本主文档瘦身为纯执行指令集。Layer 1 已完全具备进入 rehearsal 的条件，开题前用假题目实战演练 1 次即可上战场。
