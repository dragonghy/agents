---
name: tasks
description: 任务管理使用手册。查看任务管理、Agent 间任务分发、评论沟通的规范。
allowed-tools: mcp__agents__list_tickets, mcp__agents__get_ticket, mcp__agents__create_ticket, mcp__agents__update_ticket, mcp__agents__add_comment, mcp__agents__get_comments, mcp__agents__get_status_labels, mcp__agents__upsert_subtask, mcp__agents__get_all_subtasks, mcp__agents__list_agents, mcp__agents__get_agent_status, mcp__agents__suggest_assignee, mcp__agents__send_message, mcp__agents__get_inbox, mcp__agents__get_conversation, mcp__agents__mark_messages_read, mcp__agents__update_profile, mcp__agents__get_profile, mcp__agents__reassign_ticket
---

# 任务管理使用手册

## 项目信息

- **项目名称**: agents
- **project_id**: 3
- **user_id**: 1（所有 Agent 共用同一个账号）

## 状态定义

| 状态码 | 名称   | 含义                               | Agent 需要行动？ |
|--------|--------|------------------------------------|-----------------|
| 3      | 新增   | 新创建的任务，等待领取             | 是              |
| 4      | 进行中 | 已领取，正在执行                   | 是（继续执行）  |
| 1      | 已锁定 | 被阻塞，等待外部操作（Human 审批等）| 否，等待解锁    |
| 0      | 已完成 | 任务完成                           | 否              |
| -1     | 已归档 | 归档，不在看板显示                 | 否              |

**禁止使用状态 2（待批准）。** 需要阻塞等待时，请按下方"阻塞等待"流程操作。

## Agent 标识约定

使用 ticket 的 `tags` 字段标识目标 Agent，格式为 `agent:<name>`（如 `agent:dev`）。

当前团队成员请参考 `agents/shared/team-roster.md`（由 `agents.yaml` 自动生成）。

创建或查询任务时，通过 tags 判断任务属于哪个 Agent。

## 核心工作流

### 1. 查询待办任务

**推荐使用 `assignee` 参数过滤**，只查询分配给自己的活跃任务：

```
list_tickets(project_id=3, status="3,4", assignee="<你的ID>")
```

例如 Dev Agent 应该这样查询：
```
list_tickets(project_id=3, status="3,4", assignee="dev")
```

参数说明：
- `assignee`：按 agent 名称过滤（如 `"dev"`），自动转换为 `agent:dev` tag 进行匹配。**推荐使用此参数**而非 `tags`。
- `status`：逗号分隔的状态码，`"3,4"` 表示只返回新增和进行中的任务。**默认值为 `"1,3,4"`**（Blocked+New+InProgress），不传也不会拉到已完成的任务。传 `"all"` 可查看所有状态（含已完成、已归档）。
- `tags`：过滤 tags 字段包含该字符串的 ticket。如果同时设置了 `assignee`，则 `assignee` 优先。
- `dateFrom`：只返回此日期（YYYY-MM-DD）及之后创建的 ticket。用于缩小查询范围，减少 token 消耗。

**重要：`list_tickets` 只返回摘要字段**（id, headline, status, tags, priority, date, assignee 等）。如需查看 ticket 的完整 description，请使用 `get_ticket(ticket_id=<id>)`。

**`get_ticket` 返回详情字段**（摘要 + description, acceptanceCriteria, storypoints 等），已自动裁剪无关字段。

**`get_comments` 返回精简字段**（id, text, userId, date, moduleId），已自动裁剪无关字段。

### 2. 领取任务

拿到新任务后，**必须**执行以下步骤：

1. 将状态改为进行中：
   ```
   update_ticket(ticket_id=<id>, project_id=3, status=4)
   ```

2. **查看 ticket 的评论历史**，了解完整上下文：
   ```
   get_comments(module="ticket", module_id=<id>)
   ```

**为什么必须查看评论？** Ticket 在多个 agent 和 Human 之间流转时，重要的反馈、修改意见、补充说明都记录在评论中。如果不查看评论就开始工作，可能会遗漏关键信息（如 Human 的审阅意见、QA 的 bug 报告、Product 的需求变更等）。

### 3. 完成任务

任务做完后，直接标记为已完成：

```
update_ticket(ticket_id=<id>, project_id=3, status=0)
```

### 4. 任务交接（reassign_ticket）

当任务在 Agent 间流转时（Dev→QA→Product），使用 `reassign_ticket` 交接，不创建新 ticket：

```
reassign_ticket(
  ticket_id=<id>,
  from_agent="<你的ID>",
  to_agent="<目标 agent ID>",
  comment="交接说明"
)
```

- 自动将 ticket 的 assignee 改为目标 agent，status 改为 3（新增）
- 可选附带 handoff comment，记录交接上下文
- 配合 `add_comment` 使用：先在 ticket 上写详细备注，再调用 `reassign_ticket` 交接
- **同一个 ticket 贯穿整个生命周期**，只有不同 scope 的工作才需要创建新 ticket

### 5. 阻塞等待与 Human 审阅（DEPENDS_ON）

当 ticket 需要等待外部操作（Human 审阅、Human 完成独立工作、其他 ticket 完成等），统一使用 `DEPENDS_ON` 模式。`auto_dispatch.sh` 会自动检测依赖是否全部完成，并将被阻塞的 ticket 从已锁定(1)改为新增(3)。

**Agent 间审阅**（如 QA→Product 验收）不需要 DEPENDS_ON，直接使用 `reassign_ticket` 交接（见第 4 节）。

#### DEPENDS_ON 格式规范

在 ticket 的 description 中添加一行：
```
DEPENDS_ON: #<id1>, #<id2>
```
- 放在 description 的**最后一行**，方便解析
- 多个依赖用逗号分隔
- 当所有依赖 ticket 的 status 变为 0（已完成）或 -1（已归档）时，auto_dispatch 自动解锁

#### 场景 A：需要 Human 审阅/审批

当你完成方案或文档，需要 Human 审阅时：

1. 创建一个 `agent:human` ticket：
   ```
   create_ticket(
     headline="请 Human 审阅: <具体事项>",
     project_id=3,
     user_id=1,
     assignee="human",
     description="请 Human 审阅以下内容：\n\n<说明审阅什么、文档在哪里>"
   )
   ```
   假设新 ticket ID 为 #H。

2. 将自己的 ticket 标记为已锁定，并在 description 中加入依赖：
   ```
   update_ticket(ticket_id=<id>, project_id=3, status=1,
     description="<原有描述>\n\nDEPENDS_ON: #H")
   ```

3. Human 审阅后将 #H 标记为已完成（通过）或在 #H 上加 comment 说明修改意见后完成 → auto_dispatch 自动解锁你的 ticket → 你查看 #H 的评论获取反馈。

#### 场景 B：需要 Human 完成独立工作

当 Human 需要做一件独立的事情（如搭建环境、购买服务等）：

1. 创建一个 `agent:human` ticket：
   ```
   create_ticket(
     headline="需要 Human: <具体事项>",
     project_id=3,
     user_id=1,
     assignee="human",
     description="请 Human 完成以下操作：\n\n<具体说明>"
   )
   ```
   假设新 ticket ID 为 #H。

2. 将自己的 ticket 标记为已锁定，并在 description 中加入依赖：
   ```
   update_ticket(ticket_id=<id>, project_id=3, status=1,
     description="<原有描述>\n\nDEPENDS_ON: #H")
   ```

3. Human 完成后将 #H 标记为已完成 → auto_dispatch 自动解锁你的 ticket → 你继续工作。

**注意**：`agent:human` ticket 不会被 auto_dispatch 唤醒（无对应 tmux window），它只作为 Human 的待办提醒。

### 6. 分发任务给其他 Agent

创建 ticket 并指定目标 Agent：

```
create_ticket(
  headline="任务标题",
  project_id=3,
  user_id=1,
  assignee="dev",
  description="详细描述",
  priority="high"
)
```

`assignee` 参数会自动转换为 `agent:dev` tag。也可以直接用 `tags="agent:dev"`，效果相同。

优先级可选值：`low`、`medium`、`high`、`urgent`

### 7. 子任务管理

查看子任务：
```
get_all_subtasks(ticket_id=<parent_id>)
```

创建子任务：
```
upsert_subtask(
  parent_ticket=<parent_id>,
  headline="子任务标题",
  status="3",
  tags="agent:dev"
)
```

## 评论沟通

### 发送评论

```
add_comment(module="ticket", module_id=<ticket_id>, comment="评论内容")
```

### 读取评论

```
get_comments(module="ticket", module_id=<ticket_id>)
```

**注意**：`add_comment` 已修复（会自动传递 entity 对象），但仍建议用 `get_comments` 确认评论是否成功写入。

## 消息系统

Agent 间的直接沟通，用于快速问题和状态更新（不需要创建 ticket）。

**重要：发送消息后，daemon 会在下一个 dispatch 周期（约 30 秒内）自动唤醒收件人 agent。** 因此 `send_message` 是异步通知其他 agent 的有效方式——发送后无需额外操作，daemon 会负责唤醒对方。

### 发送消息

```
send_message(from_agent="<你的ID>", to_agent="<目标agent>", message="内容")
```

发送后，daemon 会在下一次 dispatch 周期检测到收件人有未读消息，并自动唤醒该 agent 处理。

### 查看收件箱

```
get_inbox(agent_id="<你的ID>", unread_only=true)
```

返回未读消息列表、总数和未读数。支持分页（`limit`、`offset`）。

### 收到消息后的处理流程

当你被唤醒并告知有未读消息时：
1. 调用 `get_inbox` 查看未读消息
2. 处理消息内容（可能需要查看相关 ticket、执行操作等）
3. 调用 `mark_messages_read` 标记已读
4. 如需回复，使用 `send_message` 发送回复

### 查看与某人的对话历史

```
get_conversation(agent_id="<你的ID>", with_agent="<对方ID>", limit=20, offset=0)
```

### 标记已读

```
mark_messages_read(agent_id="<你的ID>", message_ids="1,2,3")
```

**消息 vs Ticket**：消息适合快速沟通（确认需求、问问题、通知状态）。正式工作交付和跟踪仍通过 ticket。

## Agent Profile

定期更新你的 profile，帮助系统进行智能任务分配：

### 更新 Profile

```
update_profile(
  agent_id="<你的ID>",
  identity="我是 QA 工程师，负责 E2E 测试",
  current_context="正在测试 Browser M7 功能",
  active_skills='["tasks", "vmware-setup"]',
  expertise='["E2E testing", "VMware", "Browser automation"]'
)
```

只传需要更新的字段即可，其他字段保持不变。

### 查看 Profile

```
get_profile(agent_id="<agent ID>")    # 单个
get_profile(agent_id="all")           # 所有 agent
```

**更新时机**：领取新任务时、完成任务后、首次启动时。

## Agent 协调

### 查看 Agent 状态

查看所有 Agent 的 tmux 状态和工作负载：
```
get_agent_status(agent="all")
```

查看单个 Agent：
```
get_agent_status(agent="dev")
```

返回每个 Agent 的 tmux 状态（idle/busy/no_window）和当前工作负载（in_progress/new/blocked 任务数）。

### 智能任务分配

当需要分配任务给某个角色，但有多个同角色 Agent 时，使用 `suggest_assignee` 获取推荐：
```
suggest_assignee(role="开发工程师")
suggest_assignee(role="qa", task_context="Browser automation testing")
```

返回推荐的 Agent 名称，按工作负载、可用性和专长评分排序。评分考虑：
- 进行中任务数量（权重最高）
- 待领取任务数量
- tmux 状态（busy/idle/无窗口）
- 专长匹配（通过 `task_context` 与 agent profile 中的 `expertise` 匹配）

## 注意事项

1. **所有操作都使用 project_id=3**，这是 agents 项目的固定 ID。
2. **user_id 固定为 1**，所有 Agent 共用一个账号。
3. 创建 ticket 时必须设置 `assignee`（或 `tags`）以标识目标 Agent，否则其他 Agent 无法识别任务归属。推荐使用 `assignee` 参数。
4. 修改 ticket 状态时，`status` 参数是 **整数类型**。
5. **禁止使用 status=2**。所有等待场景（Human 审阅、外部依赖）统一用 DEPENDS_ON 模式（见第 5 节）。
6. **完成当前任务后，必须再次查询是否有新的待办任务**，有则继续执行。
7. **不要手动将 status=1 的 ticket 改回 status=4**，让 auto_dispatch 根据依赖关系自动解锁。
