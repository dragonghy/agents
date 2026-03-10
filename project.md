# 多 Agent 协同工作流架构 — 技术可行性方案

> **版本**: v1.1  
> **日期**: 2026-02-15  
> **状态**: 待确认  
> **技术栈**: TypeScript / Node.js  
> **目标读者**: 负责实现的 Agent / 开发者

---

## 1. 方案概述

### 1.1 核心结论

经过市场调研，**目前不存在一个同时满足「分层 Memory + 协调编排 + 自定义 Sub-agent」的一体化平台**。最佳路径是组合现有工具：

| 层级 | 选型 | 职责 |
|------|------|------|
| **Memory 层** | Letta (原 MemGPT) | Session 持久化、Summarization、冷记忆召回、Agent 间共享记忆 |
| **编排层** | 自建 TypeScript Coordinator | 任务状态机、Agent 调度、消息路由、错误恢复 |
| **任务管理** | SQLite (via better-sqlite3) | 任务状态持久化、审计日志 |
| **Agent 实例** | Letta Agent API | 每个职能对应一个 Stateful Agent 实例 |

### 1.2 不使用 LangGraph 的理由

本方案的协作流程本质上是**线性状态机 + 偶尔的回退**，复杂度不需要 LangGraph 的有向图编排能力。自建 Coordinator 有以下优势：

- 逻辑完全确定性，不引入 LLM 调用的不确定性
- 维护成本低，代码量预估 300-500 行 TypeScript
- 调试透明，每次状态流转都有明确日志
- TypeScript 的类型系统天然保障状态机转换的正确性
- 无额外依赖，不引入 LangGraph 的学习曲线和运维复杂度

---

## 2. 架构设计

### 2.1 系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                 Coordinator (TypeScript)                  │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ State    │  │ Message      │  │ Retry & Escalation│  │
│  │ Machine  │  │ Router       │  │ Controller        │  │
│  └────┬─────┘  └──────┬───────┘  └───────────────────┘  │
│       │               │                                   │
│  ┌────┴───────────────┴──────────────────────────────┐   │
│  │             Task Manager (SQLite)                  │   │
│  └────────────────────────────────────────────────────┘   │
└───────────┬───────────────┬───────────────┬──────────────┘
            │               │               │
     ┌──────┴──────┐ ┌─────┴──────┐ ┌──────┴──────┐
     │ Product     │ │ Dev        │ │ QA          │
     │ Agent       │ │ Agent      │ │ Agent       │
     │ (Letta)     │ │ (Letta)    │ │ (Letta)     │
     └──────┬──────┘ └─────┬──────┘ └──────┬──────┘
            │               │               │
     ┌──────┴──────┐ ┌─────┴──────┐ ┌──────┴──────┐
     │ Private     │ │ Private    │ │ Private     │
     │ Memory      │ │ Memory     │ │ Memory      │
     └─────────────┘ └────────────┘ └─────────────┘
            │               │               │
            └───────────────┼───────────────┘
                            │
                  ┌─────────┴─────────┐
                  │ Shared Memory     │
                  │ Block (项目级)     │
                  └───────────────────┘
```

### 2.2 数据流

```
User Input (需求描述)
    │
    ▼
Coordinator: 创建 Task, state = IDEA
    │
    ▼
Product Agent: 生成 PRD → state = PRD_READY
    │
    ▼
Coordinator: 提取 summary + artifact, 路由给 Dev Agent
    │
    ▼
Dev Agent: 实现代码 → state = IMPL_READY
    │
    ▼
Coordinator: 提取 summary + artifact, 路由给 QA Agent
    │
    ▼
QA Agent: 测试验证
    ├─ PASSED → Coordinator 路由给 Product Agent 做最终验收
    │   ├─ ACCEPTED → state = DONE
    │   └─ REVISION_NEEDED → 回到 Dev Agent (带反馈)
    └─ REJECTED → 回到 Dev Agent (带反馈, retry_count++)
         └─ retry_count > MAX_RETRIES → 升级到 Product Agent 做决策
```

---

## 3. Memory 层详细设计 (基于 Letta)

### 3.1 为什么选择 Letta

Letta 原生提供了方案所需的全部三层记忆能力：

| 需求 | Letta 对应能力 |
|------|---------------|
| Session 持久化 (热记忆) | 每个 Agent 拥有 perpetual thread，对话历史完整保留 |
| Summarization (暖记忆) | Context Window 满时自动压缩为递归摘要存入 Memory Block |
| Detail Recall (冷记忆) | `conversation_search` 工具可检索被压缩的原始对话 |
| Agent 间隔离 | 每个 Agent 实例拥有独立的 Memory Blocks |
| 跨 Agent 共享 | Shared Memory Block 可挂载到多个 Agent |

### 3.2 Agent 实例定义

通过 Letta TypeScript SDK 创建三个 Stateful Agent 实例：

```typescript
import Letta from "@letta-ai/letta-client";

const client = new Letta({ apiKey: process.env.LETTA_API_KEY });

// ─── Shared Block：所有 Agent 可读的项目级信息 ───
const projectBlock = await client.blocks.create({
  label: "project_info",
  value: JSON.stringify({
    name: "",
    techStack: [],
    architectureDecisions: [],
    sprintGoal: "",
    constraints: [],
  }),
  limit: 5000,
});

// ─── Product Agent ───
const productAgent = await client.agents.create({
  name: "product-agent",
  model: "anthropic/claude-sonnet-4-5-20250929",
  memoryBlocks: [
    {
      label: "persona",
      value: `你是一位资深产品经理。你的职责是：
- 将用户需求转化为清晰的 PRD 文档
- 定义功能优先级和验收标准
- 对 Dev 和 QA 的产出进行最终验收
你必须在每次回复的末尾输出结构化 JSON（见输出格式要求）。`,
      limit: 5000,
    },
    {
      label: "task_context",
      value: "", // 由 Coordinator 动态注入
      limit: 3000,
    },
  ],
  blockIds: [projectBlock.id],
});

// ─── Dev Agent ───
const devAgent = await client.agents.create({
  name: "dev-agent",
  model: "anthropic/claude-sonnet-4-5-20250929",
  memoryBlocks: [
    {
      label: "persona",
      value: `你是一位高级全栈工程师。你的职责是：
- 根据 PRD 进行技术方案设计和代码实现
- 响应 QA 反馈进行 bug 修复
- 记录关键技术决策和架构选型理由
你必须在每次回复的末尾输出结构化 JSON（见输出格式要求）。`,
      limit: 5000,
    },
    {
      label: "task_context",
      value: "",
      limit: 3000,
    },
  ],
  blockIds: [projectBlock.id],
});

// ─── QA Agent ───
const qaAgent = await client.agents.create({
  name: "qa-agent",
  model: "anthropic/claude-sonnet-4-5-20250929",
  memoryBlocks: [
    {
      label: "persona",
      value: `你是一位资深 QA 工程师。你的职责是：
- 根据 PRD 中的验收标准对代码实现进行验证
- 输出结构化测试报告（包含通过项、失败项、建议）
- 保持独立于 Dev 的视角进行测试
你必须在每次回复的末尾输出结构化 JSON（见输出格式要求）。`,
      limit: 5000,
    },
    {
      label: "task_context",
      value: "",
      limit: 3000,
    },
  ],
  blockIds: [projectBlock.id],
});
```

### 3.3 Memory 隔离与共享机制

```
Product Agent                Dev Agent                  QA Agent
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ [persona]       │   │ [persona]       │   │ [persona]       │
│ 产品经理角色定义  │   │ 工程师角色定义    │   │ QA 角色定义      │
│                 │   │                 │   │                 │
│ [task_context]  │   │ [task_context]  │   │ [task_context]  │
│ 当前任务上下文    │   │ 当前任务上下文    │   │ 当前任务上下文    │
│                 │   │                 │   │                 │
│ [conversation]  │   │ [conversation]  │   │ [conversation]  │
│ 私有对话历史     │   │ 私有对话历史     │   │ 私有对话历史      │
├─────────────────┤   ├─────────────────┤   ├─────────────────┤
│    ▼ SHARED ▼   │   │    ▼ SHARED ▼   │   │    ▼ SHARED ▼   │
│ [project_info]  │   │ [project_info]  │   │ [project_info]  │
│ 项目架构决策     │   │ 项目架构决策     │   │ 项目架构决策      │
│ 技术栈约束       │   │ 技术栈约束       │   │ 技术栈约束        │
│ Sprint 目标     │   │ Sprint 目标     │   │ Sprint 目标      │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

**关键规则**：
- `persona` 和 `task_context` 是 Agent 私有的 Block，只有该 Agent 和 Coordinator 可以修改
- `project_info` 是 Shared Block (通过 `blockIds` 挂载)，所有 Agent 可读，只有 Product Agent 和 Coordinator 可写
- 对话历史 (conversation) 是 Letta 原生管理的 perpetual thread，完全隔离

### 3.4 Memory 生命周期管理

```
Agent 被唤起
    │
    ▼
Coordinator 通过 Letta API 向 Agent 发送消息
(包含上一个 Agent 的 summary + artifact)
    │
    ▼
Agent 在其 perpetual thread 中继续工作
(自动拥有之前所有对话上下文)
    │
    ▼
Context Window 接近上限 (由 Letta 自动检测)
    │
    ▼
Letta 自动触发 Summarization：
- 早期对话被压缩为摘要，存入 Memory Block
- 原始对话存入 archival memory (向量数据库)
- Session 中替换为摘要版本
    │
    ▼
Agent 需要早期细节时：
- 自动调用 conversation_search 工具
- 从 archival memory 中语义检索相关片段
- 临时注入当前 Context (用完后在下次压缩时移除)
```

---

## 4. Coordinator 详细设计

### 4.1 核心职责

Coordinator 是一个**纯 TypeScript 程序**，不使用 LLM。它的逻辑完全确定性：

1. **任务状态管理**：维护任务的生命周期状态
2. **Agent 调度**：根据当前状态决定唤起哪个 Agent
3. **消息路由**：将上游 Agent 的产出格式化后传递给下游 Agent
4. **错误恢复**：管理重试计数、超时检测、升级逻辑

### 4.2 类型定义与状态机

```typescript
// ─── src/types.ts ───

export enum TaskState {
  IDEA = "idea",
  PRD_READY = "prd_ready",
  IMPL_READY = "impl_ready",
  QA_PASSED = "qa_passed",
  QA_REJECTED = "qa_rejected",
  ACCEPTED = "accepted",
  REVISION_NEEDED = "revision_needed",
  ESCALATED = "escalated",
  DONE = "done",
}

export type AgentRole = "product" | "dev" | "qa";

export interface Task {
  id: string;
  userInput: string;
  state: TaskState;
  retryCount: number;
  prdSummary: string | null;
  acceptanceCriteria: string[] | null;
  implSummary: string | null;
  qaReport: QAReport | null;
  lastFeedback: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface QAReport {
  verdict: "PASSED" | "REJECTED";
  passedItems: string[];
  failedItems: string[];
  suggestions: string[];
}

export interface AgentResult {
  summary: string;
  artifactType: "prd" | "code" | "test_report" | "decision";
  artifactRef: string;
  nextHint: string;
  metadata: {
    confidence: number;
    decisionsEade: string[];
  };
}

export interface Transition {
  nextAgent: AgentRole;
  targetState: TaskState | null; // null = Agent 输出决定下一个状态
}
```

```typescript
// ─── src/state-machine.ts ───

import { TaskState, type Transition } from "./types.js";

export const MAX_RETRIES = 3;

export const TRANSITIONS: Partial<Record<TaskState, Transition>> = {
  [TaskState.IDEA]:            { nextAgent: "product", targetState: TaskState.PRD_READY },
  [TaskState.PRD_READY]:       { nextAgent: "dev",     targetState: TaskState.IMPL_READY },
  [TaskState.IMPL_READY]:      { nextAgent: "qa",      targetState: null },
  [TaskState.QA_PASSED]:       { nextAgent: "product", targetState: null },
  [TaskState.QA_REJECTED]:     { nextAgent: "dev",     targetState: TaskState.IMPL_READY },
  [TaskState.REVISION_NEEDED]: { nextAgent: "dev",     targetState: TaskState.IMPL_READY },
};

export const TERMINAL_STATES = new Set([TaskState.DONE, TaskState.ESCALATED]);
```

### 4.3 Coordinator 核心逻辑

```typescript
// ─── src/coordinator.ts ───

import Letta from "@letta-ai/letta-client";
import { TaskDatabase } from "./database.js";
import { buildMessage } from "./message-builder.js";
import { parseAgentResponse } from "./response-parser.js";
import { TRANSITIONS, TERMINAL_STATES, MAX_RETRIES } from "./state-machine.js";
import { TaskState, type Task, type AgentRole } from "./types.js";
import { config } from "./config.js";

export class Coordinator {
  private client: Letta;
  private db: TaskDatabase;
  private agents: Record<AgentRole, string>; // role → Letta agent ID

  constructor() {
    this.client = new Letta({ apiKey: config.lettaApiKey });
    this.db = new TaskDatabase(config.dbPath);
    this.agents = {
      product: config.productAgentId,
      dev: config.devAgentId,
      qa: config.qaAgentId,
    };
  }

  /** 主循环：驱动一个任务从 IDEA 到 DONE */
  async runTask(userInput: string): Promise<Task> {
    let task = this.db.createTask(userInput);
    console.log(`[Task ${task.id}] Created, state: ${task.state}`);

    while (!TERMINAL_STATES.has(task.state)) {
      const transition = TRANSITIONS[task.state];
      if (!transition) break;

      const { nextAgent } = transition;
      const agentId = this.agents[nextAgent];

      // 1. 构造发送给 Agent 的消息
      const message = buildMessage(task, nextAgent);

      // 2. 通过 Letta API 发送消息
      console.log(`[Task ${task.id}] Dispatching to ${nextAgent} agent...`);
      const response = await this.client.agents.messages.create(agentId, {
        input: message,
      });

      // 3. 解析 Agent 响应
      const result = parseAgentResponse(response, nextAgent);

      // 4. 更新任务状态
      const prevState = task.state;
      task = this.updateTaskState(task, result, nextAgent);

      // 5. 记录审计日志
      this.db.logTransition({
        taskId: task.id,
        fromState: prevState,
        toState: task.state,
        agentName: nextAgent,
        summary: result.summary,
        artifactRef: result.artifactRef,
      });

      console.log(`[Task ${task.id}] ${prevState} → ${task.state}`);
    }

    return task;
  }

  /** 根据 Agent 响应更新任务状态 */
  private updateTaskState(
    task: Task,
    result: AgentResult,
    agent: AgentRole
  ): Task {
    const updated = { ...task, updatedAt: new Date().toISOString() };

    // ─── Product Agent: 生成 PRD ───
    if (agent === "product" && task.state === TaskState.IDEA) {
      updated.state = TaskState.PRD_READY;
      updated.prdSummary = result.summary;
      updated.acceptanceCriteria = result.metadata.decisionsEade; // 从结构化输出提取
    }

    // ─── Dev Agent: 完成实现 ───
    else if (agent === "dev") {
      updated.state = TaskState.IMPL_READY;
      updated.implSummary = result.summary;
    }

    // ─── QA Agent: 验证结果（有分支） ───
    else if (agent === "qa") {
      const qaReport = JSON.parse(result.artifactRef);
      if (qaReport.verdict === "PASSED") {
        updated.state = TaskState.QA_PASSED;
        updated.qaReport = qaReport;
      } else {
        updated.retryCount += 1;
        if (updated.retryCount > MAX_RETRIES) {
          updated.state = TaskState.ESCALATED;
        } else {
          updated.state = TaskState.QA_REJECTED;
          updated.lastFeedback = JSON.stringify(qaReport);
        }
      }
    }

    // ─── Product Agent: 最终验收（有分支） ───
    else if (agent === "product" && task.state === TaskState.QA_PASSED) {
      const decision = JSON.parse(result.artifactRef);
      if (decision.verdict === "ACCEPTED") {
        updated.state = TaskState.DONE;
      } else {
        updated.state = TaskState.REVISION_NEEDED;
        updated.lastFeedback = decision.revisionNotes;
      }
    }

    this.db.updateTask(updated);
    return updated;
  }
}
```

### 4.4 消息构造器

```typescript
// ─── src/message-builder.ts ───

import { TaskState, type Task, type AgentRole } from "./types.js";

export function buildMessage(task: Task, agent: AgentRole): string {
  // ─── Product Agent: 生成 PRD ───
  if (agent === "product" && task.state === TaskState.IDEA) {
    return `新需求到达，请生成 PRD。

## 用户需求
${task.userInput}

## 输出要求
请输出结构化的 PRD，包含：
1. 功能概述
2. 详细需求描述
3. 验收标准 (具体、可测试)
4. 技术约束 (如有)

请在回复末尾输出 JSON：
\`\`\`json
{"summary": "...", "acceptance_criteria": ["...", "..."]}
\`\`\``;
  }

  // ─── Dev Agent: 实现代码 ───
  if (agent === "dev") {
    const feedback =
      task.state === TaskState.QA_REJECTED ||
      task.state === TaskState.REVISION_NEEDED
        ? `\n\n## 反馈信息（第 ${task.retryCount} 次修改）\n${task.lastFeedback}`
        : "";

    return `请根据以下 PRD 进行实现。

## PRD 摘要
${task.prdSummary}

## 验收标准
${JSON.stringify(task.acceptanceCriteria, null, 2)}
${feedback}

## 输出要求
1. 完成代码实现
2. 回复末尾输出 JSON：
\`\`\`json
{"summary": "...", "files_changed": ["..."], "decisions": ["..."]}
\`\`\``;
  }

  // ─── QA Agent: 测试验证 ───
  if (agent === "qa") {
    return `请对以下实现进行测试验证。

## PRD 验收标准
${JSON.stringify(task.acceptanceCriteria, null, 2)}

## 实现摘要
${task.implSummary}

## 输出要求
请输出结构化测试报告，回复末尾输出 JSON：
\`\`\`json
{"verdict": "PASSED|REJECTED", "passed_items": [...], "failed_items": [...], "suggestions": [...]}
\`\`\``;
  }

  // ─── Product Agent: 最终验收 ───
  if (agent === "product" && task.state === TaskState.QA_PASSED) {
    return `QA 已通过，请进行最终验收。

## 原始 PRD 摘要
${task.prdSummary}

## 实现摘要
${task.implSummary}

## QA 测试报告
${JSON.stringify(task.qaReport, null, 2)}

## 输出要求
\`\`\`json
{"verdict": "ACCEPTED|REVISION_NEEDED", "reason": "...", "revision_notes": "..."}
\`\`\``;
  }

  throw new Error(`No message template for agent=${agent}, state=${task.state}`);
}
```

### 4.5 响应解析器

```typescript
// ─── src/response-parser.ts ───

import type { AgentRole, AgentResult } from "./types.js";

/**
 * 从 Letta Agent 的响应中提取结构化 JSON。
 * Agent 被要求在回复末尾输出 ```json ... ``` 块。
 */
export function parseAgentResponse(
  response: { messages: Array<{ content?: string }> },
  agent: AgentRole
): AgentResult {
  // 拼接所有文本内容
  const fullText = response.messages
    .map((m) => m.content ?? "")
    .join("\n");

  // 提取最后一个 JSON 代码块
  const jsonMatch = fullText.match(/```json\s*([\s\S]*?)\s*```/g);
  if (!jsonMatch) {
    // 容错：如果 Agent 没有输出 JSON，用全文作为 summary
    console.warn(`[${agent}] No structured JSON found, using full text as summary`);
    return {
      summary: fullText.slice(0, 500),
      artifactType: agent === "product" ? "prd" : agent === "dev" ? "code" : "test_report",
      artifactRef: "",
      nextHint: "",
      metadata: { confidence: 0.5, decisionsEade: [] },
    };
  }

  // 取最后一个 JSON 块（Agent 可能在中间也输出了 JSON）
  const lastJson = jsonMatch[jsonMatch.length - 1];
  const cleaned = lastJson.replace(/```json\s*/, "").replace(/\s*```/, "");

  try {
    const parsed = JSON.parse(cleaned);
    return {
      summary: parsed.summary ?? "",
      artifactType: agent === "product" ? "prd" : agent === "dev" ? "code" : "test_report",
      artifactRef: cleaned, // 保留原始 JSON 供下游使用
      nextHint: parsed.next_hint ?? "",
      metadata: {
        confidence: parsed.confidence ?? 0.8,
        decisionsEade: parsed.acceptance_criteria ?? parsed.decisions ?? [],
      },
    };
  } catch (e) {
    console.error(`[${agent}] Failed to parse JSON:`, e);
    return {
      summary: fullText.slice(0, 500),
      artifactType: "prd",
      artifactRef: cleaned,
      nextHint: "",
      metadata: { confidence: 0.5, decisionsEade: [] },
    };
  }
}
```

### 4.6 升级仲裁（唯一使用 LLM 的 Coordinator 逻辑）

```typescript
// ─── src/escalation.ts ───

import type Letta from "@letta-ai/letta-client";
import type { Task } from "./types.js";

/**
 * 当 QA 和 Dev 反复循环超过 MAX_RETRIES 时，
 * 升级到 Product Agent 做仲裁决策。
 */
export async function handleEscalation(
  client: Letta,
  productAgentId: string,
  task: Task
): Promise<{ decision: "LOWER_BAR" | "SPLIT_TASK" | "REDEFINE"; reason: string; action: string }> {
  const message = `Dev 和 QA 已经循环了 ${task.retryCount} 次未能达成一致。

## QA 的主要反馈
${task.lastFeedback}

## Dev 最近的实现摘要
${task.implSummary}

请做出以下决策之一：
1. LOWER_BAR - 降低验收标准，接受当前实现
2. SPLIT_TASK - 将任务拆分为更小的子任务
3. REDEFINE - 重新定义需求

\`\`\`json
{"decision": "LOWER_BAR|SPLIT_TASK|REDEFINE", "reason": "...", "action": "..."}
\`\`\``;

  const response = await client.agents.messages.create(productAgentId, {
    input: message,
  });

  // 复用 response parser 的 JSON 提取逻辑
  const fullText = response.messages.map((m) => m.content ?? "").join("\n");
  const match = fullText.match(/```json\s*([\s\S]*?)\s*```/);
  return JSON.parse(match![1]);
}
```

---

## 5. Task Manager (SQLite) 设计

### 5.1 数据库层

```typescript
// ─── src/database.ts ───

import Database from "better-sqlite3";
import { randomUUID } from "node:crypto";
import { TaskState, type Task } from "./types.js";

export class TaskDatabase {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma("journal_mode = WAL");
    this.migrate();
  }

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS tasks (
        id                  TEXT PRIMARY KEY,
        user_input          TEXT NOT NULL,
        state               TEXT NOT NULL DEFAULT 'idea',
        retry_count         INTEGER DEFAULT 0,
        prd_summary         TEXT,
        acceptance_criteria TEXT,          -- JSON array
        impl_summary        TEXT,
        qa_report           TEXT,          -- JSON
        last_feedback       TEXT,
        created_at          TEXT DEFAULT (datetime('now')),
        updated_at          TEXT DEFAULT (datetime('now'))
      );

      CREATE TABLE IF NOT EXISTS task_transitions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id       TEXT NOT NULL REFERENCES tasks(id),
        from_state    TEXT NOT NULL,
        to_state      TEXT NOT NULL,
        agent_name    TEXT NOT NULL,
        summary       TEXT,
        artifact_ref  TEXT,
        created_at    TEXT DEFAULT (datetime('now'))
      );

      CREATE TABLE IF NOT EXISTS agents (
        name            TEXT PRIMARY KEY,
        letta_agent_id  TEXT NOT NULL,
        status          TEXT DEFAULT 'idle',
        last_active_at  TEXT
      );
    `);
  }

  createTask(userInput: string): Task {
    const id = randomUUID();
    this.db
      .prepare(
        `INSERT INTO tasks (id, user_input, state) VALUES (?, ?, ?)`
      )
      .run(id, userInput, TaskState.IDEA);

    return this.getTask(id)!;
  }

  getTask(id: string): Task | null {
    const row = this.db
      .prepare(`SELECT * FROM tasks WHERE id = ?`)
      .get(id) as Record<string, unknown> | undefined;

    if (!row) return null;

    return {
      id: row.id as string,
      userInput: row.user_input as string,
      state: row.state as TaskState,
      retryCount: row.retry_count as number,
      prdSummary: row.prd_summary as string | null,
      acceptanceCriteria: row.acceptance_criteria
        ? JSON.parse(row.acceptance_criteria as string)
        : null,
      implSummary: row.impl_summary as string | null,
      qaReport: row.qa_report ? JSON.parse(row.qa_report as string) : null,
      lastFeedback: row.last_feedback as string | null,
      createdAt: row.created_at as string,
      updatedAt: row.updated_at as string,
    };
  }

  updateTask(task: Task): void {
    this.db
      .prepare(
        `UPDATE tasks SET
          state = ?, retry_count = ?, prd_summary = ?,
          acceptance_criteria = ?, impl_summary = ?,
          qa_report = ?, last_feedback = ?, updated_at = datetime('now')
        WHERE id = ?`
      )
      .run(
        task.state,
        task.retryCount,
        task.prdSummary,
        task.acceptanceCriteria ? JSON.stringify(task.acceptanceCriteria) : null,
        task.implSummary,
        task.qaReport ? JSON.stringify(task.qaReport) : null,
        task.lastFeedback,
        task.id
      );
  }

  logTransition(params: {
    taskId: string;
    fromState: string;
    toState: string;
    agentName: string;
    summary: string;
    artifactRef: string;
  }): void {
    this.db
      .prepare(
        `INSERT INTO task_transitions
          (task_id, from_state, to_state, agent_name, summary, artifact_ref)
        VALUES (?, ?, ?, ?, ?, ?)`
      )
      .run(
        params.taskId,
        params.fromState,
        params.toState,
        params.agentName,
        params.summary,
        params.artifactRef
      );
  }

  /** 获取任务的完整流转历史 */
  getTaskHistory(taskId: string) {
    return this.db
      .prepare(
        `SELECT * FROM task_transitions WHERE task_id = ? ORDER BY created_at`
      )
      .all(taskId);
  }
}
```

---

## 6. 交付物协议 (Handoff Protocol)

### 6.1 Agent 输出格式规范

每个 Agent 的输出必须包含结构化的 JSON 尾部，Coordinator 通过正则解析提取：

```json
{
    "summary": "用自然语言概括本次做了什么、为什么这么做",
    "artifact_type": "prd | code | test_report | decision",
    "artifact_ref": "文件路径或内联内容",
    "next_hint": "给下游 Agent 的关注点提示",
    "metadata": {
        "confidence": 0.85,
        "decisions": ["选择 PostgreSQL 而非 MySQL 因为...", "..."]
    }
}
```

### 6.2 Coordinator 的消息构造规则

Coordinator 向下游 Agent 传递的消息**只包含**：
1. 上游 Agent 的 `summary` (而非完整输出)
2. 上游 Agent 的 `artifact_ref` (如有必要)
3. 当前任务的 `acceptance_criteria`
4. 如果是回退，附带反馈信息

**不传递**上游 Agent 的完整对话历史——这是 Context 隔离的关键。

---

## 7. 项目文件结构

```
one-person-company/
├── src/
│   ├── index.ts              # 入口：CLI
│   ├── coordinator.ts        # 核心编排逻辑
│   ├── state-machine.ts      # 状态定义和转换规则
│   ├── message-builder.ts    # 为每个 Agent 构造消息的模板
│   ├── response-parser.ts    # 解析 Agent 输出中的结构化 JSON
│   ├── escalation.ts         # 升级仲裁逻辑
│   ├── database.ts           # SQLite 操作封装
│   ├── types.ts              # 全部类型定义
│   └── config.ts             # Agent ID、模型配置、重试参数
├── agents/
│   ├── setup.ts              # 初始化脚本：在 Letta 上创建三个 Agent 实例
│   └── prompts/
│       ├── product.md        # Product Agent 的完整 persona prompt
│       ├── dev.md            # Dev Agent 的完整 persona prompt
│       └── qa.md             # QA Agent 的完整 persona prompt
├── artifacts/                 # Agent 产出物存储目录
│   └── {task_id}/
│       ├── prd.md
│       ├── code/
│       └── test_report.md
├── tests/
│   ├── coordinator.test.ts
│   ├── state-machine.test.ts
│   └── message-builder.test.ts
├── package.json
├── tsconfig.json
└── README.md
```

---

## 8. 依赖清单

```json
{
  "dependencies": {
    "@letta-ai/letta-client": "^0.1.0",
    "better-sqlite3": "^11.0.0"
  },
  "devDependencies": {
    "@types/better-sqlite3": "^7.6.0",
    "@types/node": "^22.0.0",
    "typescript": "^5.7.0",
    "tsx": "^4.0.0",
    "vitest": "^3.0.0"
  }
}
```

不需要：LangChain, LangGraph, CrewAI, 或任何其他 Agent 框架。

---

## 9. 实施步骤

### Phase 1: 基础设施搭建 (预估 1-2 天)

1. 部署 Letta Server (`docker run letta/letta:latest`)
2. 运行 `agents/setup.ts`：创建三个 Agent 实例 + Shared Block
3. 验证：手动通过 Letta API 向每个 Agent 发消息，确认 Memory 隔离和共享正常

### Phase 2: Coordinator 核心逻辑 (预估 2-3 天)

1. `types.ts` + `state-machine.ts`：类型定义和状态转换规则
2. `database.ts`：SQLite 初始化、CRUD、审计日志
3. `message-builder.ts`：各状态下的消息模板
4. `response-parser.ts`：从 Agent 输出中提取结构化 JSON
5. `coordinator.ts`：主循环逻辑
6. `index.ts`：CLI 入口

### Phase 3: 端到端测试 (预估 1-2 天)

1. 用简单需求（如"创建一个 TODO List API"）跑完整流程
2. 验证状态流转正确性
3. 验证 Memory 持久化（重启后 Agent 能恢复上下文）
4. 验证 QA 打回 → Dev 修复 → QA 重验的回退流程
5. 验证超过 MAX_RETRIES 的升级流程

### Phase 4: 优化与扩展 (持续)

1. 产出物文件存储（`artifacts/` 目录）
2. Coordinator 的 HTTP API（可选，用 Hono 或 Fastify）
3. 根据实际使用调优 Agent prompt 和 Memory Block 大小

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Letta API 不稳定或 breaking change | 高 | 在 Coordinator 层做 API 适配封装，隔离 SDK 的直接调用 |
| Agent 输出不符合结构化格式要求 | 中 | response-parser 做容错处理；persona prompt 强调输出格式；设置格式校验重试 |
| Context Window 超限丢失关键信息 | 中 | 利用 Letta archival memory + conversation_search 做召回；关键决策写入 Shared Block |
| Dev 和 QA 无限循环 | 低 | MAX_RETRIES 硬限制 + 升级机制 |
| Token 成本过高 | 中 | 监控 token 消耗；非关键 Agent 用轻量模型；Summarization 控制 Context 大小 |

---

## 11. 未来扩展点

- **新增 Agent 角色**：如 DevOps Agent、Security Agent，只需在 Letta 上创建新实例，在状态机中添加新状态
- **并行执行**：当多个任务互不依赖时，Coordinator 可以 `Promise.all` 并发调度
- **人类介入点**：在任何状态转换前增加人工审批（Coordinator 暂停等待 `stdin` 或 webhook 确认）
- **MCP 集成**：将成熟的 Agent 能力封装为 MCP Server，接入 Cursor / Claude Desktop
- **Context Repositories**：利用 Letta 的 git-based 记忆版本控制，实现多 Agent 并发记忆管理
