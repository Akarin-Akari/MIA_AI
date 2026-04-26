# Requirements Document — MiAO AI Personal Agent

## Introduction

60 分钟限时编程挑战：构建一个支持双 LLM Provider 的 Personal AI Agent，具备工具调用、三层记忆、自我校验能力。本文档定义了从脚手架 Prompt v3.2 提炼的完整功能需求和验收标准。

## Alignment with Product Vision

本需求直接对应产品四大核心模块：LLM 双 Provider 通信、Tool Use、Memory、Self-Verification。所有需求均服务于"60 分钟内交付可工作的 Agent"这一产品目标。

---

## Requirements

### R1 - LLM 双 Provider 通信

**User Story:** 作为开发者，我需要 Agent 能够通过统一接口调用 Anthropic 和 OpenAI，以便切换 Provider 时零代码改动。

#### Acceptance Criteria

1. WHEN 配置 `LLM_PROVIDER=anthropic` THEN Agent SHALL 通过 Anthropic Messages API 发送请求
2. WHEN 配置 `LLM_PROVIDER=openai` THEN Agent SHALL 通过 OpenAI Chat Completions API 发送请求
3. WHEN Client 发送请求 THEN 内部消息格式 SHALL 为 `CanonicalMessage`（中立格式）
4. WHEN Client 收到响应 THEN 响应 SHALL 被翻译回 `CanonicalMessage` 后返回
5. IF OpenAI Client 使用 Responses API THEN 系统 SHALL 拒绝启动（**禁止 Responses API**）

### R2 - 工具调用（Tool Use）

**User Story:** 作为终端用户，我需要 Agent 能够调用外部工具获取信息或执行操作，以便得到准确的回答。

#### Acceptance Criteria

1. WHEN Agent 需要调用工具 THEN ReAct 循环 SHALL 执行 [think → tool_use → tool_result → think → end_turn]
2. WHEN 注册同步工具（含 `time.sleep`）THEN ToolRegistry SHALL 通过 `asyncio.to_thread` 卸载到线程池
3. WHEN 单轮返回多个 ToolCall THEN 每个 tool_result SHALL 按 `tool_call_id` 回填（不按位置 zip）
4. WHEN 工具执行失败 THEN tool_result SHALL 包含错误信息，Agent SHALL 继续推理
5. WHEN 同一工具连续失败 3 次 THEN RepeatedFailureDetector SHALL 注入纠偏消息

### R3 - 三层记忆系统

**User Story:** 作为终端用户，我需要 Agent 记住我的偏好和历史对话，以便提供个性化服务。

#### Acceptance Criteria

1. WHEN 新对话开始 THEN MemoryManager.get_context() SHALL 返回 `tuple[str, list[CanonicalMessage]]`
2. WHEN 对话结束 THEN after_turn SHALL 异步提取事实（`asyncio.create_task` fire-and-forget）
3. WHEN 更新 profile THEN update_profile(k, v) 的 value SHALL 为 `{value, type, tolerance?, values?}` 形态
4. WHEN 并发写入 profile.json THEN asyncio.Lock SHALL 保护写入（Lock 必须为 instance attribute）
5. WHEN 写入 profile.json THEN 写操作 SHALL 走 `{path}.tmp` → `os.replace` 原子覆盖
6. WHEN 多个 conversation 并发运行 THEN WorkingMemory SHALL 按 conv_id 隔离（互不污染）

### R4 - 自我校验（Self-Verification）

**User Story:** 作为终端用户，我需要 Agent 在回答前自动校验准确性，以便减少错误信息。

#### Acceptance Criteria

1. WHEN Agent 生成回答 THEN SelfVerifier.verify SHALL 在主链路 `await` 阻塞执行（**禁止 create_task**）
2. WHEN Stage 1 检测到 tool_result 与回答矛盾 THEN 校验 SHALL 短路返回修正
3. WHEN Stage 2 检测到 profile.json 字段类型不匹配 THEN 校验 SHALL 短路返回修正
4. WHEN Stage 3 LLM 软兜底触发 THEN SHALL 使用 Structured Outputs API
5. WHEN verifier 返回 revised_answer THEN after_turn 持久化的 SHALL 是修正后的答案（不是初稿）

---

## Non-Functional Requirements

### Code Architecture and Modularity
- **单一职责**：每个文件只负责一个关注点（LLM / Tool / Memory / Verification）
- **模块化**：组件通过 Protocol/ABC 接口解耦，DI 注入
- **依赖管理**：单向依赖，禁止循环引用
- **清晰接口**：`CanonicalMessage` + `ToolSpec` 是唯一跨模块通信格式

### Performance
- TTFB 不因 memory extraction 阻塞（fire-and-forget）
- 同步 tool 不阻塞 Event Loop（to_thread 卸载）
- Stage 1/2 短路避免不必要的 LLM 调用

### Security
- API Key 通过 pydantic-settings 从环境变量加载，禁止硬编码
- Single-user assumption，禁止多用户共享实例

### Reliability
- 文件写入原子化（tmp + os.replace），防止 crash 导致数据损坏
- 工具执行异常不冒泡到 Agent 主循环
- RepeatedFailureDetector 防止无限循环

### Usability
- CLI 模式和 API 模式双入口
- 改一行 env 变量即可切换 Provider
- README 包含完整启动指南 + 多 Worker 警告
