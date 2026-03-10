# Agent-Hub 重构评估：Claude Code Agent Teams 原生能力对比

## 1. 研究背景

Huayang 提出探索使用 Claude Code 原生的 Agent 和 Agent Teams 能力来重构 Agent-Hub 系统。核心动机：

1. **Agent 配置映射**：我们为每个 Agent 做的 System Prompt + 隔离配置，与 Claude Code 原生的 Agent 定义概念高度吻合
2. **消息传递机制**：我们手搓的 P2P 消息系统，与 Agent Teams 提供的通信能力高度相像

本文档评估哪些组件可以用原生能力替代、哪些需要保留、以及推荐的重构路径。

## 2. Claude Code 原生能力概览

### 2.1 Subagents（会话内子代理）

在单个 Claude Code 会话中，可以通过 YAML frontmatter 定义子代理：

```markdown
---
name: code-reviewer
description: Reviews code for quality
tools: Read, Glob, Grep
model: sonnet
disallowedTools: Write, Edit
mcpServers: [agents]
maxTurns: 10
---

You are a code reviewer. Analyze code for quality and security issues.
```

**能力**：
- 自定义 system prompt（Markdown 正文）
- 模型选择（sonnet/opus/haiku）
- 工具白名单/黑名单
- MCP server 配置
- 权限模式控制
- Git worktree 隔离

**限制**：
- 只能向调用者返回结果，子代理之间不能直接通信
- 运行在调用者的上下文窗口内
- 适合聚焦型任务（代码审查、搜索），不适合持久性角色

### 2.2 Agent Teams（多会话团队协作）— 实验性功能

```
启用方式：CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

一个"领导"Agent 协调多个独立的"队友"Agent：

**能力**：
- 队友之间可以直接 P2P 通信（不经过领导中转）
- 共享任务列表（含依赖关系），队友自主认领任务
- 每个队友是独立的 Claude Code 会话
- 支持 tmux / iTerm2 分屏显示
- 队友加载相同的项目上下文（CLAUDE.md、MCP servers、skills）

**限制**：
- 实验性功能，默认禁用，已知存在 session 恢复和任务延迟问题
- 不支持嵌套团队（队友不能再建团队）
- 领导固定，不能将队友提升为领导
- 无持久化 agent profile（session 结束即消失）
- 不支持自定义 agent ID（使用生成的 ID）
- Token 成本线性增长（3 个队友 ≈ 3-4x 单会话开销）

### 2.3 Claude Agent SDK

提供 Python/TypeScript SDK 编程式控制 Claude Code：

- 创建带自定义 prompt 和工具限制的 agent
- MCP 集成
- Hook 机制（工具执行前后）
- 会话持久化和恢复
- 权限模式控制

## 3. 逐组件对比

### 3.1 Agent 配置与 System Prompt

| 维度 | Agent-Hub 当前 | Claude Code 原生 | 差距 |
|------|-------------|-----------------|------|
| System Prompt 定义 | `agents/<template>/system_prompt.md` | Agent YAML frontmatter + Markdown | **高度匹配** |
| 角色模板化 | `agents.yaml` 中 template 字段 | `.claude/agents/` 目录下的 .md 文件 | **高度匹配** |
| 工具权限控制 | 全 agent 共享同一套 MCP tools | 可按 agent 配置 tools 白/黑名单 | **原生更细粒度** |
| MCP Server 配置 | 统一通过 daemon proxy | 可按 agent 指定不同 MCP servers | **原生更灵活** |
| 模型选择 | 统一 Claude Code 默认 | 可按 agent 指定 model | **原生更灵活** |
| 动态实例化 | agents.yaml 定义 → setup-agents.py 生成 | CLI/SDK 直接创建 | **原生更简单** |

**结论**：Agent 配置是**最适合迁移**的部分。我们的 `system_prompt.md` + `agents.yaml` 组合可以直接映射到 Claude Code 的 Agent 定义格式。

### 3.2 Agent 间通信

| 维度 | Agent-Hub 当前 | Claude Code Agent Teams | 差距 |
|------|-------------|------------------------|------|
| P2P 消息 | 自建 SQLite + MCP tools | 内置 teammate 消息 | **功能相似** |
| 消息持久化 | SQLite 存储，跨 session 保留 | 仅 session 内有效 | **我们更强** |
| 消息历史查询 | get_conversation, get_inbox | 无历史查询 API | **我们更强** |
| 已读标记 | mark_messages_read | 无 | **我们独有** |
| 消息与任务分离 | 消息和 ticket 是独立系统 | 消息和 task list 绑定 | **架构差异** |

**结论**：Agent Teams 的通信能力**功能相似但持久化不足**。如果我们的 agent 需要跨 session 保留消息历史（当前确实依赖），则无法完全替代。

### 3.3 任务分发与协调

| 维度 | Agent-Hub 当前 | Claude Code Agent Teams | 差距 |
|------|-------------|------------------------|------|
| 任务管理 | Leantime tickets（外部系统） | 内置共享任务列表 | **不同架构** |
| 任务分配 | Daemon auto-dispatch（idle 检测 + tmux send-keys） | 队友自主认领 | **不同模式** |
| 任务依赖 | DEPENDS_ON 模式（手动） | 内置任务依赖关系 | **原生更强** |
| Ticket 生命周期 | Dev→QA→Product reassign | 无角色化流转 | **我们独有** |
| Staleness 检测 | Dispatcher 检测卡住的 ticket | 无 | **我们独有** |
| 定时调度 | Daily journal、schedule 机制 | 无 | **我们独有** |

**结论**：任务分发**架构差异最大**。Agent Teams 的自主认领模式适合对等协作，但不适合我们的角色化流水线（Product→Dev→QA→Product）。Leantime 集成也无法被替代。

### 3.4 Agent 生命周期管理

| 维度 | Agent-Hub 当前 | Claude Code 原生 | 差距 |
|------|-------------|-----------------|------|
| Agent 启动 | tmux 窗口 + Claude Code CLI | Agent Teams 自动管理 | **原生更简单** |
| Agent 持久化 | 独立 tmux session，永驻运行 | Session 结束即消失 | **我们更强** |
| Agent Profile | SQLite 存储 identity/context/expertise | 无 | **我们独有** |
| Agent 命名 | `<template>-<name>` 格式 | 生成的 ID | **我们更友好** |
| Workspace 隔离 | 每个 agent 独立 cwd | Git worktree 隔离 | **方式不同** |

**结论**：Agent Teams 的生命周期管理**更简单但不够持久**。我们的 agent 设计为长期运行的角色实体，不是临时任务执行者。

### 3.5 可观测性

| 维度 | Agent-Hub 当前 | Claude Code 原生 | 差距 |
|------|-------------|-----------------|------|
| Web Dashboard | React SPA + REST API + WebSocket | 无（仅 CLI） | **我们独有** |
| Terminal 查看 | tmux attach | 分屏显示 | **功能相似** |
| Agent 状态 | API + Web UI | CLI 内查看 | **我们更丰富** |

## 4. 重构方案评估

### 方案 A：全面迁移到 Agent Teams（不推荐）

**做法**：放弃 daemon + Leantime，全部使用 Agent Teams 原生能力。

**优点**：
- 大幅简化基础设施
- 不需要维护自定义 MCP daemon

**风险与问题**：
- Agent Teams 是**实验性功能**，生产稳定性未验证
- 丢失持久化能力（消息历史、agent profile、跨 session 状态）
- 丢失 Leantime 集成（我们的核心差异化特性）
- 丢失 Web Dashboard
- 丢失角色化流水线（Product→Dev→QA）
- 丢失 auto-dispatch、staleness 检测、journal 调度
- 回退到"并行 N 个 Claude 会话"模式——正是我们与竞品的差异化所在

**评价**：**不推荐**。这会丢失 Agent-Hub 的核心价值主张。Agent Teams 目前是为平等协作场景设计的，而非角色化分工流水线。

### 方案 B：渐进式采纳原生能力（推荐）

**做法**：保留核心架构（daemon + Leantime + 角色分工），在特定组件上采纳原生能力。

#### B1：Agent 配置标准化（高价值，低风险）

**当前**：
```
agents/<template>/system_prompt.md  → 自定义格式
agents/<template>/CLAUDE.md         → Claude Code 原生
agents.yaml                         → 自定义配置
setup-agents.py                     → 自定义生成脚本
```

**迁移到**：
```
.claude/agents/<role>.md            → 标准 Agent 定义格式
  - YAML frontmatter: tools, model, mcpServers, permissions
  - Markdown body: system prompt
agents.yaml                         → 仅保留实例化配置（谁用什么 agent 模板）
```

**好处**：
- 利用 Claude Code 原生的 agent 加载机制
- 工具权限可以按角色细粒度控制（如 QA 不能 Write，Product 不能 Bash）
- 模型选择按角色优化（Product 用 opus 做决策，Dev 用 sonnet 写代码）
- 减少自定义代码量

**风险**：低。这是配置层面的变更，不影响运行时架构。

#### B2：Agent SDK 替代 tmux 管理（中等价值，中等风险）

**当前**：
```python
# dispatcher.py
subprocess.run(["tmux", "send-keys", "-l", "-t", f"{session}:{agent}", msg])
```

**迁移到**：
```python
# 使用 Agent SDK 管理 agent 会话
from claude_agent_sdk import Session
session = Session(agent="dev-alex", system_prompt=..., mcp_servers=[...])
session.send(message)
result = await session.query(prompt)
```

**好处**：
- 更可靠的 agent 状态检测（不依赖 tmux pane 输出解析）
- 编程式的错误处理和重试
- 原生支持会话恢复
- 不依赖 tmux（可以在非 tmux 环境运行）

**风险**：
- Agent SDK 是否稳定用于长时间运行的 agent？
- 需要重写 dispatcher.py 的核心逻辑
- 需要验证 SDK 与我们的 MCP daemon 的兼容性

**建议**：先在隔离环境中验证 SDK 的 session 管理能力，确认可行后再迁移。

#### B3：Subagents 增强角色内能力（低价值，低风险）

**当前**：每个 agent 是单一的 Claude Code 会话。

**增强**：在现有 agent 内使用 Subagents 处理特定子任务：
- Dev agent 内启用 `code-reviewer` subagent 做自审
- QA agent 内启用 `test-designer` subagent 设计测试场景
- Product agent 内启用 `researcher` subagent 做竞品分析

**好处**：补充性增强，不影响现有架构。

### 方案 C：新建基于 Agent SDK 的下一代架构（远期方向）

**做法**：用 Agent SDK 重新实现核心框架，保留 Leantime 和角色分工概念。

```
新架构：
┌──────────────────────────────────────┐
│         Agent-Hub Orchestrator       │
│  (Python, 基于 Claude Agent SDK)     │
│                                      │
│  ┌──────────┐  ┌──────────────────┐ │
│  │ Agent    │  │ Session Manager  │ │
│  │ Registry │  │ (SDK Sessions)   │ │
│  └──────────┘  └──────────────────┘ │
│  ┌──────────┐  ┌──────────────────┐ │
│  │ Dispatch │  │ Leantime Client  │ │
│  │ Engine   │  │                  │ │
│  └──────────┘  └──────────────────┘ │
└──────────────────────────────────────┘
          │              │
    ┌─────┴─────┐  ┌────┴─────┐
    │ Claude    │  │ Leantime │
    │ Agent SDK │  │          │
    │ Sessions  │  │          │
    └───────────┘  └──────────┘
```

**好处**：
- 不依赖 tmux
- 原生 agent 管理（启动、停止、恢复、状态检测）
- 保留所有差异化特性（Leantime、角色分工、dispatch）
- 更容易打包和分发（pip install）

**风险**：工作量大，Agent SDK 成熟度待验证。

## 5. Huayang 决策（2026-03-10）

### ✅ M1：Agent 配置标准化 — 批准执行

将 system_prompt.md 迁移到 `.claude/agents/<role>.md` 格式，利用 YAML frontmatter 定义工具权限和模型。纯配置变更，风险最低、价值明确。

**执行 ticket**: #196，分配给 dev-alex。

### ❌ M2：Agent SDK 可行性 PoC — 否决

### ❌ M3：基于 SDK 的架构重写 — 否决

**否决原因**（Huayang 原话）：
1. **SDK 生命周期管理过于局限**：目前太局限于把 Claude Code 作为唯一的 Agent
2. **多供应商兼容性**：Agent-Hub 未来需要支持多种不同的 Agent（如 Gemini 或其他模型），强绑定 Anthropic SDK 会被单一供应商锁定，无法兼容异构 Agent
3. **M3 依赖 M2**：既然 SDK 路线不可行，基于 SDK 的架构重写自然也不需要了

**战略决策**：调度编排、生命周期和消息系统，继续使用自建系统（跨模型、更灵活）。仅执行 M1 配置标准化。

## 6. 风险提示

1. **迁移期间的兼容性**：新旧系统切换期间可能出现功能断裂（通过保留旧文件支持回退来缓解）
2. **核心价值不能丢失**：Agent-Hub 的差异化是"角色分工 + Leantime + Milestone 驱动"，重构不能削弱这些

## 7. 总结

| 能力 | 原生替代可行性 | 决策 |
|------|-------------|------|
| Agent 配置/System Prompt | **高** | ✅ 迁移到 `.claude/agents/` 格式 |
| Agent 间 P2P 通信 | 中（缺持久化） | ❌ 保留自建系统 |
| 任务分发/Dispatch | 低 | ❌ 保留自建系统 |
| Leantime 集成 | 无 | ❌ 保留（核心差异化） |
| Agent 生命周期 | 中 | ❌ 保留自建系统（多供应商兼容） |
| Web Dashboard | 无 | ❌ 保留 |
| 角色化流水线 | 低 | ❌ 保留（核心差异化） |

**最终结论**：仅在 **Agent 配置层** 采纳 Claude Code 原生格式；其余组件全部保留自建系统，确保跨模型兼容和架构灵活性。
