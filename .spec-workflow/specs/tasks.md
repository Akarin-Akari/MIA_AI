# Tasks Document — MiAO AI Personal Agent

> 按 Layer 分层策略和依赖顺序排列。每个 Task 标注文件、依赖和验收标准。

---

## Layer 1 — 核心脚手架（前 8 分钟）

- [ ] 1. 创建类型契约 `app/llm/base.py`
  - File: `app/llm/base.py`
  - 定义 `CanonicalMessage`, `ToolCall`, `ToolSpec`, `BaseLLMClient(Protocol)`
  - **铁律**：`tool_call_id`（禁止 `tool_use_id`）
  - Purpose: 所有模块的共享类型基础
  - _Requirements: R1.3, R1.4_

- [ ] 2. 实现 Anthropic Client `app/llm/anthropic_client.py`
  - File: `app/llm/anthropic_client.py`
  - 实现 `marshal(CanonicalMessage → Anthropic format)` + `unmarshal(Anthropic → CanonicalMessage)`
  - 翻译 `ToolSpec → Anthropic tool schema`
  - _Leverage: `app/llm/base.py`_
  - _Requirements: R1.1, R1.3_

- [ ] 3. 实现 OpenAI Client `app/llm/openai_client.py`
  - File: `app/llm/openai_client.py`
  - 实现 `marshal/unmarshal` 到 OpenAI **Chat Completions API** 格式
  - **铁律**：禁止 Responses API
  - 翻译 `ToolSpec → OpenAI function schema`
  - _Leverage: `app/llm/base.py`_
  - _Requirements: R1.2, R1.3, R1.5_

- [ ] 4. 实现 ToolRegistry `app/tools/registry.py`
  - File: `app/tools/registry.py`
  - `register(name, fn, spec)` / `execute(name, args) → str`
  - `inspect.iscoroutinefunction` 检测 + `asyncio.to_thread` 自动包裹同步 tool
  - _Requirements: R2.1, R2.2_

- [ ] 5. 实现内置工具 `app/tools/builtin.py`
  - File: `app/tools/builtin.py`
  - 实现 `get_current_time`, `update_profile` 等基础工具
  - `update_profile(k, v)` 的 value 必须是 `{value, type, tolerance?, values?}` 形态
  - _Leverage: `app/tools/registry.py`_
  - _Requirements: R2.1, R3.3_

- [ ] 6. 实现 WorkingMemory `app/memory/working.py`
  - File: `app/memory/working.py`
  - `dict[str, deque[CanonicalMessage]]` 按 conv_id 分桶
  - `add(conv_id, msg)` / `get(conv_id) → list[CanonicalMessage]`
  - _Requirements: R3.6_

- [ ] 7. 实现 MarkdownMemory `app/memory/markdown.py`
  - File: `app/memory/markdown.py`
  - 读写 `profile.json` + `learned_facts.md`
  - `asyncio.Lock` 必须为 **instance attribute**（`self._lock = asyncio.Lock()`）
  - 写入走 `{path}.tmp` → `os.replace` 原子覆盖
  - _Requirements: R3.3, R3.4, R3.5_

- [ ] 8. 实现 SQLiteMemory `app/memory/sqlite.py`
  - File: `app/memory/sqlite.py`
  - aiosqlite 异步操作 `messages` 表 + `facts` 表
  - 初始化时 auto-create 表（DDL 见 design.md）
  - _Requirements: R3.1_

- [ ] 9. 实现 MemoryManager `app/memory/manager.py`
  - File: `app/memory/manager.py`
  - `get_context(conv_id) → tuple[str, list[CanonicalMessage]]`
  - `after_turn()`: fact extraction 用 `asyncio.create_task`（fire-and-forget）
  - 持久化 `verifier.revised_answer or original`
  - _Leverage: `working.py`, `markdown.py`, `sqlite.py`_
  - _Requirements: R3.1, R3.2, R4.5_

- [ ] 10. 实现 SelfVerifier `app/verification/verifier.py`
  - File: `app/verification/verifier.py`
  - Stage 1: tool_results 硬规则（确定性，无 LLM）
  - Stage 2: profile.json 结构化校验（metadata schema）
  - Stage 3: LLM 软兜底（Structured Outputs API + 抽样）
  - _Requirements: R4.1, R4.2, R4.3, R4.4_

- [ ] 11. 实现 RepeatedFailureDetector `app/agent/detector.py`
  - File: `app/agent/detector.py`
  - 按 `conv_id` 分桶的失败计数器
  - 连续 3 次相同特征指纹 → 注入纠偏消息
  - _Requirements: R2.5_

- [ ] 12. 实现 AgentExecutor `app/agent/executor.py`
  - File: `app/agent/executor.py`
  - ReAct 循环：[user → LLM → tool_use? → tool_result → LLM → end_turn]
  - 主链路铁律：`await verifier.verify()` → `create_task(memory.after_turn())`
  - _Leverage: 所有上游模块_
  - _Requirements: R2.1, R4.1, R4.5_

- [ ] 13. 实现 DI 工厂 `app/factory.py`
  - File: `app/factory.py`
  - `build_agent(config) → AgentExecutor` 装配所有组件
  - 显式 DI，禁止模块级全局变量
  - _Requirements: 架构要求_

- [ ] 14. 实现 Config `app/config.py`
  - File: `app/config.py`
  - pydantic-settings `BaseSettings` 子类
  - 字段：`LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEFAULT_MODEL`, `DATA_DIR`
  - _Requirements: 架构要求_

- [ ] 15. 实现 FastAPI 入口 `app/main.py`
  - File: `app/main.py`
  - `/chat` POST 端点 + CLI 入口
  - 通过 `factory.build_agent()` 注入 agent 实例
  - _Leverage: `app/factory.py`_
  - _Requirements: 架构要求_

---

## Layer 1 — 测试（与实现并行）

- [ ] 16. 编写 `tests/conftest.py`
  - File: `tests/conftest.py`
  - 共享 fixture：`tmp_path` SQLite DB、mock LLM client、mock tool
  - **禁止** `:memory:` SQLite

- [ ] 17. 编写 `tests/test_tool_roundtrip.py`
  - File: `tests/test_tool_roundtrip.py`
  - 双 Provider 完整 tool roundtrip
  - 单轮多 tool_calls 按 id 回填
  - 同步 tool 不阻塞 Event Loop
  - _Requirements: R1, R2_

- [ ] 18. 编写 `tests/test_memory.py`
  - File: `tests/test_memory.py`
  - 并发写入锁有效性（instance Lock 鉴伪）
  - Atomic write 故障注入（mock os.replace 抛异常）
  - 多 conv_id 隔离
  - _Requirements: R3_

- [ ] 19. 编写 `tests/test_verification.py`
  - File: `tests/test_verification.py`
  - Stage 1/2/3 各自触发路径
  - revised_answer 持久化正确性
  - 主链路顺序正确性
  - _Requirements: R4_

---

## Layer 2 — 增量功能（08-43 分钟）

- [ ] 20. 流式输出（SSE）
  - 给 `/chat` 端点增加 SSE streaming
  - AgentExecutor 支持 yield token
  - _Optional, 取决于题目要求_

- [ ] 21. 多轮对话上下文窗口管理
  - WorkingMemory 增加 token budget 裁剪
  - 保留最近 N 轮 + 系统消息

- [ ] 22. 增强错误处理
  - 所有异常路径加 structured logging
  - API 层返回标准 error response

---

## Layer 3 — 锦上添花（43-55 分钟）

- [ ] 23. README 完善
  - 启动指南 + API 示例
  - 多 Worker 部署警告
  - 架构图（Mermaid）

- [ ] 24. 最终自检
  - 逐条对照 Acceptance Criteria（22 项）
  - `pytest tests/` 全部 pass
  - ruff check + mypy 无 error
