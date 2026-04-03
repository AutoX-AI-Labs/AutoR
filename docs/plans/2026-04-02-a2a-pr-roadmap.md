# A2A 驱动 AutoR 可观测性：PR 路线图

> 2026-04-02 | 分支 `ziyan/acp-refactor`

## 目标

```
当前: Manager → ClaudeOperator → subprocess("claude -p") → 解析 stdout（黑盒）
目标: Manager → A2AOperator   → A2A Client → Claude Code A2A Server → Anthropic API
                                  ↑ SSE 事件流: 任务状态、工具调用、token 用量、错误码
```

用 Google A2A 协议（JSON-RPC 2.0 + SSE）替代 subprocess 调用，实现：
- 结构化任务状态（submitted/working/completed/failed/canceled）
- 实时可观测（thinking、tool_use、text 增量流式事件）
- 结构化错误码（替代字符串匹配 stderr）
- 优雅取消（`tasks/cancel` 替代 `process.terminate()`）
- 多实例并发（每个 server 独立进程）

## 已完成（commit 1-3，在分支上）

```
7bfb5f1 fix: operator recovery — attempt persistence, resume detection, interrupt logging
98f9191 feat: add JSON-RPC 2.0 + ACP protocol layer for operator communication
4efc3f2 docs: initialize project
```

这 3 个 commit 包含以下基础设施（对应逻辑 PR 1-3）：

| # | 内容 | 关键文件 | 测试 |
|---|------|---------|------|
| 1 | `OperatorProtocol` ABC | `src/operator_protocol.py`, `src/manager.py`, `src/operator.py` | 3 |
| 2 | Operator recovery 修复 | `src/operator.py`, `src/utils.py` | 17 |
| 3 | JSON-RPC 2.0 + ACP 类型 + 过渡 operator/server | `src/jsonrpc.py`, `src/acp_types.py`, `src/acp_operator.py`, `src/acp_server.py`, `main.py` | 85 |

共 105 个新测试，全部通过。

过渡代码（`acp_*`）将在 PR 7 清理，被 A2A 标准实现替代。

## 待开发（PR 4-7）

### PR 4: A2A Server 骨架（~300 行）

引入 `a2a-sdk` 依赖，搭建 Claude Code A2A Server。Stub executor，跑通协议。

```
新建:
  src/a2a/__init__.py
  src/a2a/server.py          # A2AStarletteApplication + uvicorn
  src/a2a/agent_card.py      # AgentCard 定义
  src/a2a/executor.py        # ClaudeCodeExecutor(AgentExecutor) — stub
  tests/test_a2a_server.py   # server 启动、message/send、tasks/get、tasks/cancel
```

依赖: `a2a-sdk[http-server]`

---

### PR 5: A2AOperator 客户端（~300 行）

新增 `A2AOperator` 实现 `OperatorProtocol`，通过 A2A 客户端与 server 通信。

```
新建:
  src/a2a_operator.py         # A2AOperator(OperatorProtocol)
  tests/test_a2a_operator.py  # 端到端: operator + server
修改:
  main.py                     # --operator a2a
```

核心: `message/stream` → SSE 事件 → `logs_raw.jsonl` + UI → `OperatorResult`

---

### PR 6: Anthropic SDK 集成（~500 行）

替换 stub executor 为真实 Claude API 调用 + 本地工具执行。

```
修改:
  src/a2a/executor.py         # Anthropic SDK 流式调用
新建:
  src/a2a/tools.py            # Bash/Read/Write/Edit 本地执行
  tests/test_executor_integration.py
```

事件映射（参考 codex-a2a 模式）:
```
Claude thinking      → TaskStatusUpdateEvent(WORKING)
Claude tool_use      → TaskStatusUpdateEvent + TaskArtifactUpdateEvent
Claude text delta    → TaskArtifactUpdateEvent
Claude message_stop  → Task(COMPLETED)
Claude API error     → Task(FAILED)
```

依赖: `anthropic`

---

### PR 7: 清理过渡代码（~200 行）

删除自建 ACP 实现，统一到 A2A。

```
删除:
  src/acp_operator.py, src/acp_server.py, src/acp_types.py
  tests/test_acp_operator.py, tests/test_acp_server.py, tests/test_acp_types.py, tests/test_acp_integration.py
修改:
  main.py              # --operator acp 作为 a2a 别名
更新:
  docs/                # 最终架构文档
```

---

## 依赖关系

```
已完成 1-3 (OperatorProtocol + JSON-RPC + Recovery)
  │
  ├── PR 4 (A2A Server 骨架)
  │     │
  │     └── PR 5 (A2AOperator 客户端)
  │           │
  │           └── PR 6 (Anthropic SDK 集成)
  │                 │
  │                 └── PR 7 (清理)
  │
  └── (已有 CLI 路径不受影响)
```
