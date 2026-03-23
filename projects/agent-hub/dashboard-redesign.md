# Web UI Dashboard 重设计方案

> Status: 设计稿
> Ticket: #388
> Author: product-kevin
> Date: 2026-03-21

## 问题分析

### 当前状态

6 个页面中，Dashboard 和 Agents **高度雷同**：
- 相同数据源（`/api/v1/agents` + `/api/v1/usage`）
- 相同轮询间隔（5s agents, 30s usage）
- Dashboard = Agent 卡片网格，Agents = Agent 表格

Dashboard 缺少**全局态势感知**：打开后只看到 agent 列表，看不到系统整体运行状况。

### 目标

Dashboard 变成**指挥中心**（Command Center），一眼看清：
1. 系统在忙什么？（活跃 agent + 当前任务）
2. 有什么需要我关注？（blocked on human、失败、异常）
3. 整体进展如何？（ticket 统计、token 趋势）

## 重设计方案

### 页面结构

```
┌──────────────────────────────────────────────────────────────┐
│  Agent Hub                              [Dispatch All]       │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─ 🔔 Needs Attention ─────────────────────────────────┐   │
│  │  ⚠️ 3 tickets blocked on Human    [View]             │   │
│  │  🔴 1 agent stuck > 2h (dev-liam)  [View]            │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ Summary Cards ───────────────────────────────────────┐   │
│  │ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │ │ 🟢 Agents│ │ 📋Tickets│ │ 🪙 Tokens│ │ 📨 Msgs  │  │   │
│  │ │ 4 busy   │ │ 8 active │ │ 2.1M     │ │ 3 unread │  │   │
│  │ │ 12 idle  │ │ 3 new    │ │ today    │ │ today    │  │   │
│  │ │ 0 error  │ │ 2 blocked│ │ ↑12%     │ │          │  │   │
│  │ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ Agent Status ─────────┐  ┌─ Recent Activity ─────────┐  │
│  │ ● dev-alex    busy     │  │ 10:32 dev-alex → qa-lucy  │  │
│  │   #389 实现 Dashboard  │  │   reassign #389            │  │
│  │ ● dev-emma    idle     │  │ 10:28 qa-oliver            │  │
│  │ ● qa-lucy     busy     │  │   验收通过 #387            │  │
│  │   #387 QA 测试中       │  │ 10:15 product-kevin        │  │
│  │ ● qa-oliver   idle     │  │   创建 #389                │  │
│  │ ○ dev-liam    blocked  │  │ 09:50 user-sophia          │  │
│  │   #371 等待 Human      │  │   Round 33 完成            │  │
│  │ ...12 more idle        │  │ ...                        │  │
│  └─────────────────────────┘  └───────────────────────────┘  │
│                                                              │
│  ┌─ Token Usage (7 days) ────────────────────────────────┐   │
│  │  ▓▓▓░░  ▓▓▓▓░  ▓▓░░░  ▓▓▓░░  ▓▓▓▓░  ▓▓░░░  ▓▓▓░░  │   │
│  │  Mon    Tue    Wed    Thu    Fri    Sat    Sun         │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 各区域详解

#### 1. Needs Attention（顶部警示条）

**目的**：最需要 Human 关注的事项，一眼可见。

显示条件（任一满足即显示）：
- Ticket assignee = `human` 且 status = new/in-progress → "N tickets waiting for Human"
- Agent 任务 in_progress 超过 2 小时（stale） → "N agents may be stuck"
- Agent 状态 = error → "N agents in error state"

无告警时隐藏此区域。点击 [View] 跳转到对应的 Tickets/Agents 页面（带筛选参数）。

#### 2. Summary Cards（四个统计卡片）

| 卡片 | 数据 | API |
|------|------|-----|
| **Agents** | busy/idle/error 数量 | `/api/v1/agents`（现有） |
| **Tickets** | active(new+progress)/new/blocked 数量 | `/api/v1/tickets`（现有，需新增聚合端点） |
| **Tokens** | 今日总用量 + vs 昨日变化百分比 | `/api/v1/usage`（现有） |
| **Messages** | 今日未读消息数 | `/api/v1/messages`（现有） |

点击卡片跳转到对应详情页。

#### 3. Agent Status（左栏）

精简版 agent 列表，**按状态分组排序**：
1. 🔴 error（红色，最醒目）
2. 🟡 busy（黄色，显示当前任务标题）
3. 🔵 blocked（蓝色，显示阻塞原因）
4. ⚪ idle（灰色，折叠显示 "N more idle"）

busy agent 显示当前正在处理的 ticket 标题（从 workload 获取）。

#### 4. Recent Activity（右栏）

显示最近的系统事件流（时间线）：
- Ticket 状态变更（created, reassigned, completed）
- Agent dispatch 事件
- 重要消息（agent 间通知）

数据来源：需要新增 API 端点 `/api/v1/activity`，或组合现有数据。
MVP 可以先用 tickets 的 recent changes 近似。

#### 5. Token Usage 迷你图表

7 天柱状图，复用 Tokens 页面的数据但简化展示。点击跳转到 Tokens 详情页。

### 页面合并方案

| 现有页面 | 处理 |
|---------|------|
| Dashboard (`/`) | **重写**为上述设计 |
| Agents (`/agents`) | **保留**，作为 agent 详细表格视图 |
| Tokens (`/tokens`) | **保留**，Dashboard 链过去 |
| Tickets (`/tickets`) | **保留**，Dashboard 链过去 |
| Messages (`/messages`) | **保留** |

不需要删除任何页面，只重写 Dashboard。

### 新增后端需求

#### 必须：Ticket 统计聚合端点

```
GET /api/v1/tickets/stats
Response:
{
  "total": 388,
  "by_status": {
    "new": 3,
    "in_progress": 5,
    "blocked": 2,
    "completed": 370,
    "closed": 8
  },
  "human_blocked": 3,    // assignee=human 且 active
  "stale_count": 1        // in_progress > 2h
}
```

#### 可选：活动流端点（P1）

```
GET /api/v1/activity?limit=20
Response:
[
  {"time": "10:32", "agent": "dev-alex", "action": "reassign", "ticket_id": 389, "detail": "→ qa-lucy"},
  {"time": "10:28", "agent": "qa-oliver", "action": "completed", "ticket_id": 387, "detail": "验收通过"},
  ...
]
```

MVP 可以暂时不做，先用 tickets recent list 代替。

## 验收标准

1. Dashboard 包含 Needs Attention 告警区（有 human-blocked tickets 时显示）
2. Dashboard 包含 4 个 Summary Cards（Agents/Tickets/Tokens/Messages）
3. Dashboard 包含 Agent Status 列表（按状态分组，busy 显示当前任务）
4. Dashboard 包含 7 天 Token Usage 迷你图表
5. 点击各区域可跳转到对应详情页
6. 新增 `/api/v1/tickets/stats` 后端端点
7. `npm run build` 零 TSC 错误
8. 所有现有测试不受影响
9. 原 Agents 页面功能不受影响

## 非目标

- 不删除/合并现有 Agents 页面（它作为详细表格视图仍有价值）
- 不做实时 WebSocket 推送（继续用轮询）
- Activity feed 可以 P1 后续补充
