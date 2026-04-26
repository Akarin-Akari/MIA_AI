# Product Overview — MiAO AI

## Product Purpose

60 分钟限时编程挑战的 **Personal AI Agent** 脚手架。解决的核心问题：在极短时间内构建一个具备工具调用、持久记忆、自我校验能力的多 Provider AI 助手，同时保证架构可扩展、代码可测试。

## Target Users

- **直接用户**：参加编程挑战的开发者（即 Akarin 本人）
- **间接用户**：通过 Agent 交互的终端用户（单用户场景）
- **痛点**：60 分钟内从零搭建完整 Agent 极其困难，需要脚手架消除架构决策成本

## Key Features

1. **双 Provider 支持**：Anthropic Claude + OpenAI GPT，通过内部 `CanonicalMessage` 中立格式无缝切换
2. **工具调用（Tool Use）**：ReAct 循环 + `ToolRegistry` 自动同步/异步包裹
3. **三层记忆系统**：WorkingMemory（会话级）+ MarkdownMemory（持久画像）+ SQLite（历史消息）
4. **自我校验（Self-Verification）**：三层校验架构（硬规则 → 结构化校验 → LLM 软兜底）
5. **幻觉防御**：`RepeatedFailureDetector` 检测连续相同失败并注入纠偏

## Business Objectives

- 在 60 分钟内完成 Layer 1 脚手架 + 通过所有 Acceptance Criteria
- 代码质量达到企业级标准（SOLID、DRY、KISS）
- 双 Provider 切换零改动成本

## Success Metrics

- **Acceptance Criteria 通过率**：22/22（100%）
- **测试覆盖**：3 个测试文件 / 5+ 项核心断言全部 pass
- **Provider 切换**：改一行 env 变量即可切换，无代码改动
- **时间控制**：Layer 1 在 08 分钟内完成，Layer 2 在 43 分钟内完成

## Product Principles

1. **Contract-First**：先定义接口契约，再写实现
2. **Provider 中立**：内部只流通 CanonicalMessage，禁止私有格式泄漏
3. **防御性编程**：每个共享资源都有并发保护 + 原子写入
4. **可测试性优先**：所有组件 DI 注入，mock 友好

## Monitoring & Visibility

- **Dashboard Type**: FastAPI + Swagger UI（自动生成 API 文档）
- **Real-time Updates**: SSE（Server-Sent Events）用于流式响应
- **Key Metrics Displayed**: 对话轮次、tool 调用次数、verifier 校正率
- **Sharing Capabilities**: RESTful API + CLI 双入口

## Future Vision

### Potential Enhancements
- **Multi-User Support**：引入 `user_id` 作用域 + `users/{user_id}/` 文件隔离
- **Multi-Worker 部署**：从 `asyncio.Lock` 升级到 `filelock` 跨进程锁
- **RAG 增强**：接入向量数据库做长期记忆检索
