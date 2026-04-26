# Project Structure — MiAO AI

## Directory Organization

```
miao-ai/
├── app/                        # 主应用代码
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口 + CLI 入口
│   ├── config.py               # pydantic-settings 配置
│   ├── factory.py              # DI 工厂：build_agent() 装配所有组件
│   │
│   ├── llm/                    # LLM 客户端层
│   │   ├── __init__.py
│   │   ├── base.py             # CanonicalMessage / ToolCall / ToolSpec / BaseLLMClient(Protocol)
│   │   ├── anthropic_client.py # AnthropicClient: 双向翻译 Anthropic ↔ Canonical
│   │   └── openai_client.py    # OpenAIClient: 双向翻译 OpenAI ↔ Canonical
│   │
│   ├── tools/                  # 工具系统
│   │   ├── __init__.py
│   │   ├── registry.py         # ToolRegistry: 注册 + 执行 + 同步包裹
│   │   └── builtin.py          # 内置工具实现（get_time, update_profile 等）
│   │
│   ├── memory/                 # 三层记忆系统
│   │   ├── __init__.py
│   │   ├── working.py          # WorkingMemory: dict[str, deque[CanonicalMessage]]
│   │   ├── markdown.py         # MarkdownMemory: profile.json + learned_facts.md（含 asyncio.Lock + atomic write）
│   │   ├── sqlite.py           # SQLiteMemory: aiosqlite messages/facts 表
│   │   └── manager.py          # MemoryManager: 编排三层 + get_context() + after_turn()
│   │
│   ├── verification/           # 自我校验
│   │   ├── __init__.py
│   │   └── verifier.py         # SelfVerifier: Stage 1/2/3 三层校验
│   │
│   └── agent/                  # Agent 执行器
│       ├── __init__.py
│       ├── executor.py         # AgentExecutor: ReAct 循环 + 主链路编排
│       └── detector.py         # RepeatedFailureDetector: 幻觉循环检测
│
├── tests/                      # 测试文件
│   ├── __init__.py
│   ├── conftest.py             # 共享 fixture（tmp_path DB, mock LLM client）
│   ├── test_tool_roundtrip.py  # Tool 完整往返测试（双 provider）
│   ├── test_memory.py          # 记忆系统测试（并发锁 + atomic write）
│   └── test_verification.py    # Verifier 三层触发测试
│
├── data/                       # 运行时数据（gitignore）
│   ├── profile.json            # 用户画像
│   ├── learned_facts.md        # 提取的事实
│   └── agent.db                # SQLite 数据库
│
├── requirements.txt            # Python 依赖
├── README.md                   # 项目说明 + 多 Worker 警告
├── claude.md                   # Claude Code 项目指令
├── agent.md                    # Codex 项目指令
├── gemini.md                   # Gemini CLI 项目指令
└── .env.example                # 环境变量模板
```

## Naming Conventions

### Files
- **模块文件**: `snake_case.py`（如 `anthropic_client.py`）
- **测试文件**: `test_<module>.py`（如 `test_memory.py`）
- **配置文件**: `snake_case.py`（如 `config.py`）

### Code
- **Classes/Types**: `PascalCase`（如 `CanonicalMessage`, `AgentExecutor`）
- **Functions/Methods**: `snake_case`（如 `get_context`, `after_turn`）
- **Constants**: `UPPER_SNAKE_CASE`（如 `MAX_TURNS`, `DEFAULT_MODEL`）
- **Variables**: `snake_case`（如 `conv_id`, `tool_spec`）
- **Protocol/ABC**: `PascalCase` + 语义命名（如 `BaseLLMClient`）

## Import Patterns

### Import Order（PEP 8 + isort）
1. 标准库（`asyncio`, `inspect`, `pathlib`）
2. 第三方库（`fastapi`, `pydantic`, `anthropic`, `openai`）
3. 项目内部模块（`app.llm.base`, `app.tools.registry`）

### 绝对导入
```python
# ✅ 正确：绝对导入
from app.llm.base import CanonicalMessage, ToolSpec
from app.tools.registry import ToolRegistry

# ❌ 禁止：相对导入跨层
from ..llm.base import CanonicalMessage
```

## Code Structure Patterns

### 模块组织
```
1. 标准库 / 第三方 import
2. 项目内部 import
3. 常量定义
4. Pydantic Model / dataclass 定义
5. Protocol / ABC 接口定义
6. 主类实现
7. 辅助函数
```

### 函数组织
```
1. 参数校验
2. 核心逻辑
3. 异常处理（try/except 不冒泡，降级为 NoOp）
4. 返回值
```

## Module Boundaries

### 核心隔离规则

```
app/llm/         →  只关心 LLM 通信，不知道 Memory/Tool 的存在
app/tools/       →  只关心工具注册和执行，不知道 LLM 的存在
app/memory/      →  只关心数据持久化，不知道 LLM/Tool 的存在
app/verification/→  只关心校验逻辑，通过 DI 获取所需数据
app/agent/       →  编排层，组合上述所有组件
```

### 依赖方向（单向，禁止反转）

```
main.py → factory.py → agent/ → {llm/, tools/, memory/, verification/}
                                    ↓
                              app/llm/base.py（共享类型契约）
```

## Code Size Guidelines

- **文件大小**：≤ 300 行（超过则拆分）
- **函数大小**：≤ 50 行（超过则提取子函数）
- **类复杂度**：≤ 10 个 public 方法
- **嵌套深度**：≤ 3 层（用 early return 降低嵌套）

## Documentation Standards

- 所有 public class/method 必须有 docstring（Google style）
- 复杂逻辑需要 inline comment 解释 **why**，而非 **what**
- 代码注释语言与代码库保持一致（英文）
- README 必须包含多 Worker 部署警告
