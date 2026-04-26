# CLAUDE.md — Claude Code 项目指令

> 本文件是 Claude Code 的项目级上下文。每次启动 Claude Code 会自动读取。

This is a coding challenge for MiAO AI. You (Claude Code) are helping
the candidate build a complete project from scratch under time pressure.

## Critical: preserve AI session logs

Your AI interaction history is a MANDATORY deliverable. The evaluator
reviews it to assess how the candidate directs AI tools.

Common session directories by tool:

- Claude Code: `.claude/`
- Cursor: `.cursor/` or `.cursorcontext/`
- Codex: `.codex/`
- Windsurf: `.windsurf/`

Rules:

- NEVER delete or modify AI session directories
- NEVER add them to `.gitignore`
- Commit them with every push
- If the AI tool doesn't auto-save sessions locally, export chat
  history to an `ai-session/` directory in the repo

Candidates who do not submit AI session logs will receive
a significant scoring penalty.

## Build standards

- Build a COMPLETE, runnable project — one command to start
- Include tests that actually verify the core requirements
- Write a clear README explaining how to run
- Commit frequently with meaningful messages

## 项目身份

- **项目名**：MiAO AI Coding Challenge — Personal AI Agent
- **性质**：60 分钟限时编程挑战的脚手架准备
- **所有者**：Akarin（阿卡林）

## 你的角色

你是**主力执行者**。你的任务是根据 `docs/脚手架prompt_v3.md` 的指令生成完整的 Layer 1 脚手架代码。

## 核心指令文档

**必读**（执行前必须完整阅读）：

1. **`docs/脚手架prompt_v3.md`**（~643 行）— 脚手架 Prompt v3.2，这是你的**唯一执行蓝本**

   - 第六节：脚手架 Prompt（行为契约 + 反模式禁令）
   - 第七节：17 条 Critical Rules（不可违反的铁律）
   - 第八节：31 条雷区清单（五轮评审血泪教训）
   - 第九节：Acceptance Criteria（提交前自检门禁）
2. **`docs/评审历程档案.md`**（参考）— 五轮评审的辩论纪要和修订对照

## 执行约束

### 绝对禁止

- ❌ NO LangChain, NO LlamaIndex, NO CrewAI — raw SDK only
- ❌ 不准在 Client 之外的层产出 Anthropic / OpenAI 私有格式字典
- ❌ 不准用全局 `_messages: list` 的 WorkingMemory
- ❌ 不准写 `pass` 占位测试
- ❌ 不准用 `SQLiteStore(":memory:")` 做测试 fixture
- ❌ 不准用 `tool_use_id`（Anthropic 术语泄漏）— 必须用 `tool_call_id`
- ❌ 不准把 Verifier 异步化（它必须阻塞主响应链路）
- ❌ 不准直接 `open(path, 'w')` truncate 写入共享文件 — 必须 atomic write
- ❌ OpenAI 端禁止使用 Responses API — 必须用 Chat Completions API

### 绝对执行

- ✅ 内部只流通 `CanonicalMessage` + `ToolSpec`，Client 各自做完整双向翻译
- ✅ WorkingMemory 按 `conversation_id` 分桶：`dict[str, deque[CanonicalMessage]]`
- ✅ `MemoryManager.get_context()` 返回 `tuple[str, list[CanonicalMessage]]`，两个都要用
- ✅ ToolRegistry 用 `inspect.iscoroutinefunction` + `asyncio.to_thread` 自动包裹同步 tool
- ✅ `asyncio.Lock` 挂在 `MarkdownMemory` 的 instance attribute 上
- ✅ 共享文件写入走 `{path}.tmp` → `os.replace` 原子覆盖
- ✅ `after_turn` 持久化 `verifier.revised_answer or original`（不是初稿）
- ✅ `RepeatedFailureDetector` 按 `conv_id` 分桶
- ✅ `update_profile(k, v)` 的 value 必须是 `{value, type, tolerance?, values?}` 形态
- ✅ 3 个测试文件 / 5+ 项核心断言，全部真断言

### Self-Verifier 三层架构

1. **Stage 1**：tool_results 硬规则（确定性，无 LLM）
2. **Stage 2**：structured profile.json 强校验（按字段类型 + metadata schema）
3. **Stage 3**：LLM 软兜底（Structured Outputs API + 抽样路径独立触发）

### 主链路顺序铁律

```
SelfVerifier.verify  →  必须 await 阻塞主响应（提速靠 Stage 1/2 短路 + Stage 3 抽样）
MemoryManager.after_turn fact extraction  →  必须 asyncio.create_task fire-and-forget
```

颠倒 = 同时毁掉正确性和延迟。

## 技术栈

- Python 3.11+ / FastAPI / anthropic + openai SDKs
- aiosqlite, aiofiles, pydantic v2, pydantic-settings
- pytest + pytest-asyncio

## 代码库调查工具链（MCP 优先）

调查和理解代码库时，**必须优先使用 MCP 工具组合**，禁止用低效的原始方式：

### 工具优先级

| 优先级 | 工具                                | 用途                                     | 替代的低效方式                          |
| ------ | ----------------------------------- | ---------------------------------------- | --------------------------------------- |
| 🥇 1st | **acemcp `search_context`** | 语义搜索——不知道在哪个文件时的首选     | ❌ 盲目 `find` / `ls -R` 逐目录翻   |
| 🥇 1st | **gitnexus `query`**        | 查执行流、调用链、符号关联图             | ❌ 手动跟踪 import 链                   |
| 🥈 2nd | **`rg` (ripgrep)**          | 精确文本/正则搜索——知道关键词时用      | ❌`grep -r`（慢、无 .gitignore 尊重） |
| 🥈 2nd | **cclsp**                     | LSP 级别的定义跳转、引用查找、重命名     | ❌ 文本搜索猜定义位置                   |
| 🥉 3rd | **gitnexus `context`**      | 单个符号的 360° 视图（callers/callees） | ❌ 手动 grep 函数名                     |
| 🥉 3rd | **gitnexus `impact`**       | 改动前的影响面分析                       | ❌ 凭经验猜测                           |

### 强制规则

- **搜索代码内容**：用 `rg`（ripgrep），**禁止** `grep -r`。ripgrep 自动尊重 `.gitignore`、速度快 10-100x
- **语义搜索**：用 `acemcp search_context`——当你不确定代码在哪个文件时，这是第一选择
- **调用链分析**：用 `gitnexus query` 或 `gitnexus context`——不要手动逐文件追踪 import
- **符号定义/引用**：用 `cclsp find_definition` / `find_references`——不要用文本搜索猜
- **改动影响评估**：用 `gitnexus impact`——改代码前先看 blast radius

### 组合拳示例

```
1. 不知道某功能在哪？  →  acemcp search_context "memory manager context injection"
2. 找到文件后看调用链  →  gitnexus context --name MemoryManager
3. 精确搜索某个字符串  →  rg "tool_call_id" --type py
4. 跳转到定义         →  cclsp find_definition --symbol CanonicalMessage
5. 改动前看影响面     →  gitnexus impact --target MemoryManager --direction upstream
```

## 工作流程

1. 完整阅读 `docs/脚手架prompt_v3.md`
2. 按第六节目录结构创建项目
3. 先写类型契约（`app/llm/base.py`）
4. 再写基础设施（tools → memory → agent → verifier）
5. 写 3 个测试文件（禁止 pass 占位）
6. 跑 `pytest tests/` 确认全部通过
7. 逐条对照第九节 Acceptance Criteria 自检

## 部署假设

**Single-user Personal Agent**。禁止在未引入 `user_id` 作用域改造的前提下让多用户共享实例。
