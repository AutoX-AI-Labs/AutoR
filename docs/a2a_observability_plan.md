# 用 A2A + ACP 实现 Claude Code 实例可观测性

> 2026-04-02 | 基于 A2A spec v0.3、codex-a2a 实现模式、ACP 设计理念

## 核心问题

AutoR 当前通过 `claude -p @prompt --output-format stream-json` 以 subprocess 方式调用 Claude Code。这种方式的根本缺陷是：

```
ResearchManager -> subprocess.Popen("claude -p ...") -> 逐行读 stdout -> 猜测状态
```

- **不可观测**：Claude 在 thinking、执行工具、等待 API 时，stdout 可能数分钟无输出，无法区分"正在工作"和"已卡死"
- **不可控制**：无超时、无取消、无暂停/恢复
- **不可诊断**：错误只是 stderr 文本，需要字符串匹配来猜测错误类型
- **不可扩展**：多实例并发、负载均衡、分布式部署全无可能

## 解决方案：A2A 协议

### 为什么是 A2A

| 方案 | 优势 | 问题 |
|------|------|------|
| `claude -p` subprocess | 零依赖、最简单 | 黑盒、不可观测 |
| 直接调 Anthropic API | 完全控制 | 失去 Claude Code 的工具执行能力（Bash/Read/Write/Edit） |
| **A2A 协议** | **标准化、可观测、可扩展** | 需要写 A2A server wrapper |
| ACP 协议 | REST 友好、事件类型丰富 | **已并入 A2A**，不再独立维护 |

A2A（Agent-to-Agent Protocol）是 Google 主导、Linux Foundation 托管的标准协议：
- **JSON-RPC 2.0** 线格式
- **SSE 流式事件**：`TaskStatusUpdateEvent` + `TaskArtifactUpdateEvent`
- **任务状态机**：submitted → working → completed/failed/canceled/input-required
- **Python SDK**：`pip install a2a-sdk`（Python 3.10+）
- **170+ 合作组织**采用

ACP 的核心设计（Runs、丰富事件类型、trajectory metadata）已并入 A2A，两者现在是同一个协议体系。

### codex-a2a 验证了这个模式

`MyPrototypeWhat/codex-a2a` 是一个 TypeScript 实现，将 OpenAI Codex CLI 包装为 A2A server。核心模式：

```
A2A Client  --JSON-RPC-->  A2A Server  --SDK-->  Codex SDK  --events-->  A2A SSE Stream
                           (codex-a2a)           (codex)
```

**事件映射**（Codex → A2A）：

| Codex 事件 | A2A 映射 |
|------------|---------|
| `thread.started` | status-update: working |
| `agent_message` | 增量文本流（delta tracking） |
| `reasoning` | status-update with thought |
| `command_execution` | status-update + artifact-update（工具调用） |
| `file_change` | artifact-update |
| `error` | status-update: failed |
| `turn.completed` | token usage metrics |

这和我们需要做的完全一致——只是把 Codex 换成 Claude Code。

## 架构设计

### 目标架构

```
                    ┌─────────────────────────────────┐
                    │         AutoR Manager            │
                    │   (ResearchManager, 8-stage loop)│
                    └──────────┬──────────────────────┘
                               │ A2A JSON-RPC
                               │ message/send, message/stream
                               │ tasks/get, tasks/cancel
                               ▼
                    ┌──────────────────────────────────┐
                    │      Claude Code A2A Server       │
                    │   (claude-code-a2a, Python)       │
                    │                                    │
                    │  ┌─── Agent Card ───┐             │
                    │  │ name: claude-code │             │
                    │  │ skills: [research,│             │
                    │  │   code, analysis] │             │
                    │  └──────────────────┘             │
                    │                                    │
                    │  ┌─── ClaudeCodeExecutor ────┐    │
                    │  │                            │    │
                    │  │  Claude Code SDK / API     │    │
                    │  │  (Anthropic Python SDK)    │    │
                    │  │                            │    │
                    │  │  Tool execution:           │    │
                    │  │  - Bash (subprocess)       │    │
                    │  │  - Read/Write/Edit (fs)    │    │
                    │  │  - WebSearch (API)         │    │
                    │  │                            │    │
                    │  │  Events → SSE stream:      │    │
                    │  │  - thinking → status       │    │
                    │  │  - tool_use → status+art   │    │
                    │  │  - text → artifact         │    │
                    │  │  - error → failed          │    │
                    │  └────────────────────────────┘    │
                    └──────────────────────────────────┘
```

### 与现有代码的关系

```
现有：
  main.py --operator cli  →  ClaudeOperator  →  subprocess("claude -p")
  main.py --operator acp  →  ACPOperator     →  ACPServer (in-process, stub)

目标：
  main.py --operator a2a  →  A2AOperator     →  Claude Code A2A Server (HTTP)
```

`A2AOperator` 实现 `OperatorProtocol`（PR #1 已建立的 ABC），通过 `a2a-sdk` 客户端与 A2A server 通信。

### 可观测性对比

| 维度 | `claude -p` (现状) | A2A (目标) |
|------|-------------------|-----------|
| **任务状态** | 猜测（exit code + 文件是否存在） | 明确（submitted/working/completed/failed） |
| **进度** | 无（stdout 可能沉默数分钟） | SSE 流式事件（thinking/tool_call/text） |
| **Token 用量** | 不可见 | 每次 turn 结束时报告 |
| **工具调用** | 解析 stream-json 文本 | 结构化 `artifact-update` 事件 |
| **错误类型** | 字符串匹配 stderr | 结构化错误码 + failed 状态 |
| **卡死检测** | 不可能（thinking 期间无输出是正常的） | 心跳/超时 + 状态查询 |
| **取消** | `process.terminate()` 暴力终止 | `tasks/cancel` 优雅取消 |
| **多实例** | 不可能 | 每个 server 独立进程，客户端连接不同端口 |
| **人工介入** | 只在 stage 间 | `input-required` 状态支持 stage 内介入 |

## 逐步开发计划

### Phase 1: A2A 基础设施（1 个 PR）

**目标**：搭建 Claude Code A2A Server 骨架，用 stub executor 跑通 A2A 协议流程。

**新增文件**：
```
src/a2a_server/
  __init__.py
  server.py              # A2A HTTP server (a2a-sdk + uvicorn)
  agent_card.py           # Agent Card 定义
  executor.py             # ClaudeCodeExecutor (stub)
```

**具体内容**：

1. `agent_card.py` — 定义 Claude Code 的 Agent Card：
   ```python
   AgentCard(
       name="claude-code-research",
       description="Claude Code research agent for AutoR pipeline",
       skills=[
           AgentSkill(id="research", name="Literature Research", ...),
           AgentSkill(id="code", name="Code Implementation", ...),
           AgentSkill(id="analysis", name="Data Analysis", ...),
           AgentSkill(id="writing", name="Paper Writing", ...),
       ],
       supportedInterfaces=[
           SupportedInterface(protocolBinding="JSON-RPC-2.0", url="...")
       ],
   )
   ```

2. `executor.py` — ClaudeCodeExecutor（先 stub）：
   ```python
   class ClaudeCodeExecutor(AgentExecutor):
       async def execute(self, context: RequestContext) -> EventQueue:
           queue = EventQueue()
           # stub: 直接返回 completed
           queue.add(Task(id=context.task_id, status=TaskStatus(state=TaskState.COMPLETED)))
           return queue

       async def cancel(self, task_id: str) -> None:
           # stub
           pass
   ```

3. `server.py` — A2A HTTP server：
   ```python
   app = A2AStarletteApplication(
       agent_card=build_agent_card(port),
       request_handler=DefaultRequestHandler(executor, InMemoryTaskStore()),
   )
   uvicorn.run(app, host="0.0.0.0", port=port)
   ```

**测试**：
- A2A server 启动、Agent Card 可访问
- `message/send` 返回 completed task
- `tasks/get` 查询任务状态
- `tasks/cancel` 取消任务

**依赖**：`pip install a2a-sdk[http-server]`

---

### Phase 2: A2AOperator 客户端（1 个 PR）

**目标**：新增 `A2AOperator` 实现 `OperatorProtocol`，通过 A2A 客户端与 server 通信。

**新增文件**：
```
src/a2a_operator.py       # A2AOperator (OperatorProtocol)
tests/test_a2a_operator.py
```

**修改文件**：
```
main.py                   # 新增 --operator a2a
```

**具体内容**：

```python
class A2AOperator(OperatorProtocol):
    def __init__(self, server_url: str, model: str, ...):
        self.client = A2AClient(server_url)

    def run_stage(self, stage, prompt, paths, attempt_no, continue_session=False):
        # 1. 发送 message/stream
        request = SendMessageRequest(
            message=Message(role="USER", parts=[Part(text=prompt)]),
            # 附加 metadata: stage_slug, workspace, output_path
        )

        # 2. 流式接收事件
        async for event in self.client.send_streaming_message(request):
            if isinstance(event, TaskStatusUpdateEvent):
                # 状态变化 → 日志 + UI
                self._handle_status(event, paths, stage, attempt_no)
            elif isinstance(event, TaskArtifactUpdateEvent):
                # 产物更新 → 日志 + UI
                self._handle_artifact(event, paths, stage, attempt_no)

        # 3. 查询最终结果
        task = await self.client.get_task(GetTaskRequest(id=task_id))
        return self._to_operator_result(task, paths, stage)
```

**关键映射**：
```
A2A TaskState.COMPLETED + stage_file.exists() → OperatorResult(success=True)
A2A TaskState.FAILED → OperatorResult(success=False, stderr=error_message)
A2A TaskState.CANCELED → OperatorResult(success=False, stderr="cancelled")
A2A TaskStatusUpdateEvent → append_jsonl(logs_raw) + ui.show_status()
A2A TaskArtifactUpdateEvent → append_jsonl(logs_raw) + ui.show_status()
```

---

### Phase 3: 真实 Claude API 集成（1 个 PR）

**目标**：在 `ClaudeCodeExecutor` 中接入 Anthropic Python SDK，实现真实的 Claude API 调用 + 工具执行。

**修改文件**：
```
src/a2a_server/executor.py   # 替换 stub 为真实实现
```

**核心逻辑**（参考 codex-a2a 的事件映射模式）：

```python
class ClaudeCodeExecutor(AgentExecutor):
    async def execute(self, context: RequestContext) -> EventQueue:
        queue = EventQueue()
        prompt = context.message.parts[0].text

        # 1. 调用 Anthropic API（流式）
        async with anthropic.AsyncAnthropic() as client:
            stream = client.messages.stream(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                tools=self._available_tools(),
                max_tokens=8192,
            )

            async for event in stream:
                match event.type:
                    case "content_block_start":
                        if event.content_block.type == "thinking":
                            # thinking → status-update
                            queue.add(TaskStatusUpdateEvent(
                                status=TaskStatus(state=TaskState.WORKING,
                                    message="Thinking..."),
                            ))
                        elif event.content_block.type == "tool_use":
                            # tool_use → status-update + artifact-update
                            tool_result = await self._execute_tool(event.content_block)
                            queue.add(TaskArtifactUpdateEvent(
                                artifact=Artifact(parts=[Part(text=tool_result)]),
                            ))

                    case "content_block_delta":
                        if event.delta.type == "text_delta":
                            # 文本增量 → artifact-update
                            queue.add(TaskArtifactUpdateEvent(
                                artifact=Artifact(parts=[Part(text=event.delta.text)]),
                            ))

            # 2. 组装最终结果
            queue.add(Task(
                id=context.task_id,
                status=TaskStatus(state=TaskState.COMPLETED),
                artifacts=[...],
            ))
        return queue
```

**工具执行**（在 server 进程内）：
```python
async def _execute_tool(self, tool_use):
    match tool_use.name:
        case "Bash":
            result = subprocess.run(tool_use.input["command"], ...)
            return result.stdout
        case "Read":
            return Path(tool_use.input["file_path"]).read_text()
        case "Write":
            Path(tool_use.input["file_path"]).write_text(tool_use.input["content"])
            return "OK"
        case "Edit":
            # sed-like replacement
            ...
```

**事件映射**（Claude API → A2A，类比 codex-a2a）：

| Claude API 事件 | A2A 事件 |
|-----------------|---------|
| `content_block_start (thinking)` | `TaskStatusUpdateEvent(WORKING, "Thinking...")` |
| `content_block_delta (text)` | `TaskArtifactUpdateEvent(text delta)` |
| `content_block_start (tool_use)` | `TaskStatusUpdateEvent(WORKING, "Calling {tool}")` |
| 工具执行完成 | `TaskArtifactUpdateEvent(tool result)` |
| `message_stop` | `TaskStatusUpdateEvent(COMPLETED)` |
| API 异常 | `TaskStatusUpdateEvent(FAILED, error_message)` |

---

### Phase 4: 可观测性 Dashboard（1 个 PR）

**目标**：利用 A2A 的结构化事件构建实时 run dashboard。

由于所有 A2A 事件都已经写入 `logs_raw.jsonl`（Phase 2 的 `A2AOperator` 做的），dashboard 只需要消费这些日志：

```
src/dashboard/
  server.py          # 简单的 HTTP server，提供 run 状态 API
  templates/
    index.html        # 单页面 dashboard
```

功能：
- Run 列表 + 状态总览
- 每个 stage 的实时状态（submitted/working/completed/failed）
- Token 用量统计
- 工具调用时间线
- 错误率和恢复模式

---

### Phase 5: 多实例并发（未来）

A2A 天然支持多 server 实例。每个 Claude Code A2A Server 是独立进程：

```
AutoR Manager
  ├── A2A Server :50001 (Stage 01-03, 轻量级)
  ├── A2A Server :50002 (Stage 04-05, 实验执行, GPU)
  └── A2A Server :50003 (Stage 06-08, 写作分析)
```

通过 Agent Card 的 `skills` 字段做能力路由。

## 依赖管理

```
# 新增依赖
a2a-sdk[http-server]    # A2A Python SDK + Starlette server
anthropic               # Anthropic Python SDK (Claude API)
uvicorn                 # ASGI server

# 已有（无变化）
# Python 3.10+ stdlib only
```

建议在 `pyproject.toml` 中设为 optional extras：
```toml
[project.optional-dependencies]
a2a = ["a2a-sdk[http-server]", "anthropic", "uvicorn"]
```

这样 `--operator cli`（默认）路径不需要安装额外依赖。

## 与已有代码的兼容性

| 组件 | 变化 |
|------|------|
| `src/operator_protocol.py` | 不变 — A2AOperator 实现这个 ABC |
| `src/operator.py` | 不变 — CLI 路径作为 fallback |
| `src/manager.py` | 不变 — 只依赖 OperatorProtocol |
| `src/utils.py` | 不变 |
| `src/prompts/*.md` | 不变 — prompt 模板与传输层无关 |
| `main.py` | 微改 — 新增 `--operator a2a` 分支 |
| `src/jsonrpc.py` | 保留 — A2A 本身就用 JSON-RPC 2.0 |
| `src/acp_types.py` | 逐步废弃 — 被 a2a-sdk 的类型替代 |
| `src/acp_operator.py` | 逐步废弃 — 被 A2AOperator 替代 |
| `src/acp_server.py` | 逐步废弃 — 被 A2A server 替代 |

之前做的 PR #1（OperatorProtocol ABC）是正确的基础，A2AOperator 直接实现它。
PR #2（jsonrpc.py）的 ErrorCode 和 JsonRpcException 在 A2A 体系中仍然有用。
PR #3-6（acp_*）作为过渡实现，最终被 a2a-sdk 的标准实现替代。

## 总结

```
Phase 1: A2A Server 骨架 (stub)        → 跑通协议
Phase 2: A2AOperator 客户端             → AutoR 可以用 A2A 调用 agent
Phase 3: 真实 Claude API + 工具执行     → 替代 claude -p
Phase 4: 可观测性 Dashboard             → 利用结构化事件
Phase 5: 多实例并发                      → 分布式研究执行
```

每个 Phase 独立可交付、可测试、不破坏现有功能。
