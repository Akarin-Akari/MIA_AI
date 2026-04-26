# MiAO AI v3.2 — 代码审计报告

> 审计时间：2026-04-26 08:20  
> 审计员：幽浮喵（架构设计 + 运行时安全视角）  
> 工具链：acemcp `search_context` + gitnexus `query` + ripgrep 精确扫描

---

## 🔍 审计 Checklist 逐项过审

### ✅ 运行时安全（10 项 Critical 审计项）

| # | 审计项 | 状态 | 证据 |
|---|--------|------|------|
| 1 | `ToolRegistry.execute` 对同步 tool 用了 `asyncio.to_thread` | ✅ PASS | [registry.py:85-90](file:///f:/MIAO_AI/app/tools/registry.py#L85-L90) — `inspect.iscoroutinefunction` 检测 + `to_thread` 包裹 |
| 2 | `asyncio.Lock` 在 `MarkdownMemory.__init__` 中实例化 | ✅ PASS | [markdown_store.py:45](file:///f:/MIAO_AI/app/memory/markdown_store.py#L45) — `self._lock = asyncio.Lock()` 实例属性 |
| 3 | `MarkdownMemory` 写操作走 atomic write | ✅ PASS | [markdown_store.py:72-76](file:///f:/MIAO_AI/app/memory/markdown_store.py#L72-L76) — `{path}.tmp` → `os.replace` |
| 4 | `SelfVerifier.verify` 在主链路 `await` 阻塞 | ✅ PASS | [core.py:225](file:///f:/MIAO_AI/app/agent/core.py#L225) — `verification = await self._verifier.verify(...)` |
| 5 | `MemoryManager.after_turn` 的 fact extraction 是 `create_task` | ✅ PASS | [manager.py:141](file:///f:/MIAO_AI/app/memory/manager.py#L141) — `asyncio.create_task(self._extract_facts(...))` |
| 6 | `RepeatedFailureDetector` 按 `conv_id` 分桶 | ✅ PASS | [core.py:45](file:///f:/MIAO_AI/app/agent/core.py#L45) — `defaultdict(list)` 按 conv_id key 隔离 |
| 7 | FastAPI 路由正确注入 agent 实例 | ✅ PASS | [factory.py](file:///f:/MIAO_AI/app/factory.py) DI + [main.py](file:///f:/MIAO_AI/app/main.py) `_build_and_set_agent` |
| 8 | README 包含多 worker 部署警告 | ✅ PASS | [README.md:144-148](file:///f:/MIAO_AI/README.md#L144-L148) |
| 9 | `profile.json` 并发写入测试 | ✅ PASS | [test_memory_isolation.py:83-101](file:///f:/MIAO_AI/tests/test_memory_isolation.py#L83-L101) — 双 writer gather |
| 10 | Stage 3 使用 Structured Outputs (forced Tool Use) | ✅ PASS | [verifier.py:267-293](file:///f:/MIAO_AI/app/agent/verifier.py#L267-L293) — `submit_verification` tool |

### ✅ 架构合规（6 项关键契约）

| 维度 | 状态 | 证据 |
|------|------|------|
| **Provider Neutrality** — `tool_call_id` 不泄漏 `tool_use_id` | ✅ PASS | `tool_use_id` 仅出现在 `anthropic_client.py` 的 SDK 序列化层（L93），注释标注 "Anthropic uses tool_use_id"。内部 IR 全程使用 `tool_call_id` |
| **OpenAI 禁用 Responses API** | ✅ PASS | `responses.create` 仅在注释中作为禁令出现，实际调用是 `chat.completions.create` (L178) |
| **主链路顺序**：verify → final_answer → create_task(after_turn) | ✅ PASS | [core.py:223-240](file:///f:/MIAO_AI/app/agent/core.py#L223-L240) — 三段式严格顺序 |
| **after_turn 持久化 final_answer 不是初稿** | ✅ PASS | [core.py:239](file:///f:/MIAO_AI/app/agent/core.py#L239) — 传入 `final_answer`（revised or draft）|
| **Profile metadata schema 强制** | ✅ PASS | [markdown_store.py:108-130](file:///f:/MIAO_AI/app/memory/markdown_store.py#L108-L130) — `{value, type}` 形态 |
| **异常降级不冒泡** | ✅ PASS | [core.py:137-143](file:///f:/MIAO_AI/app/agent/core.py#L137-L143) — `try/except` 全包 + 友好降级消息 |

---

## ⚠️ 发现的问题清单

### 🟡 P2 — 轻微问题（3 项）

#### 1. `routes.py` — 未使用的 `Depends` import
```
File: app/api/routes.py:13
from fastapi import APIRouter, Depends  ← Depends 从未使用
```
- **风险**：纯代码清洁度问题，不影响运行
- **修复**：删除 `Depends`

#### 2. `main.py` — `@app.on_event("startup")` 已被 FastAPI 标记为 deprecated
```
File: app/main.py:90
@app.on_event("startup")  ← FastAPI 推荐改用 lifespan
```
- **风险**：当前版本可用，但未来升级可能需要迁移
- **修复**：改用 `lifespan` context manager 模式（非紧急，笔试场景可忽略）

#### 3. `RepeatedFailureDetector` 文档注释与实际实现的微妙歧义
```
File: docs/脚手架prompt_v3.md (约 L380)
"禁止在 AgentExecutor.__init__ 内 self.detector = RepeatedFailureDetector() 然后所有会话共用"
```
vs 实际代码 `core.py:121`:
```python
self._detector = RepeatedFailureDetector()  # 在 __init__ 中
```

- **分析**：**不是 bug**。脚手架原文禁止的是"所有会话共用一个计数器"的模式，而 `RepeatedFailureDetector` 内部使用 `defaultdict(list)` 按 `conv_id` 做 key 隔离。文档想表达的是方案 (a) "共享实例但按 conv_id 分桶"，代码选择了这个方案并且正确实现。
- **建议**：在注释中补充说明为什么这里是安全的，避免后续维护者误解。

---

## 📊 架构评分

| 维度 | 评分 | 说明 |
|------|------|------|
| **解耦度** | 9/10 | Protocol/ABC 抽象诚实、DI 显式、`CanonicalMessage` 作为唯一跨模块 IR |
| **鲁棒性** | 9/10 | 全链路异常降级、NoOp 默认、try/except 不冒泡 |
| **并发安全** | 9/10 | Lock 位置正确、atomic write 落实、单进程边界明确声明 |
| **认知架构** | 8.5/10 | 三层记忆职责清晰、token budget 有基础实现（max_chars 截断） |
| **可测试性** | 9/10 | Mock 友好、Fixture 正确、20/20 测试通过 |

**综合评分：8.9/10** ✅ — 可以上战场喵！

---

## 🔧 建议修复

以下 3 个 P2 fix 可以立即执行（均为文案/清洁级别，0 风险）：

1. ~~`routes.py` 删除未使用的 `Depends` import~~
2. ~~`main.py` 的 `on_event` → `lifespan`（可选）~~  
3. ~~`core.py:120` 补充注释说明 defaultdict 隔离机制~~

> [!TIP]
> 上述 3 项均为打磨级别改动。脚手架核心架构和运行时安全规则已 **100% 满足**，不存在任何 P0/P1 级别的阻塞问题。主人可以放心进入 Layer 2 开发或直接上战场 ฅ'ω'ฅ
