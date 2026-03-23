---
name: daily-journal
description: 每日工作日志。被定时唤醒写日志时使用此 skill，了解日志格式和写作流程。
allowed-tools: mcp__agents__list_tickets, mcp__agents__get_ticket, mcp__agents__get_comments, mcp__agents__get_inbox, Write, Read, Glob
---

# 每日工作日志

你被定时唤醒来总结过去 24 小时的工作。按照以下流程写日志。

## 步骤

### 1. 查询任务活动

```
list_tickets(assignee="<你的ID>", status="all", dateFrom="<昨天日期 YYYY-MM-DD>")
```

对每个返回的 ticket，查看详情和评论了解你做了什么：
```
get_ticket(ticket_id=<id>)
get_comments(module="ticket", module_id=<id>)
```

### 2. 查看消息记录

```
get_inbox(agent_id="<你的ID>")
```

### 3. 写日志

按下方格式写日志，保存到：

```
agents/<你的ID>/journal/<今天日期 YYYY-MM-DD>.md
```

例如：`agents/dev-alex/journal/2026-03-09.md`

**注意**：使用 Write 工具写文件，路径是相对于 repo 根目录的绝对路径。

### 4. 完成

日志写完后，检查是否有待处理的任务（status=3,4），有则继续执行。

## 日志格式

```markdown
# 工作日志 YYYY-MM-DD

## 处理的 Ticket
- [#<id>] <headline> → <状态变化或当前状态>
- [#<id>] <headline> → <状态变化或当前状态>

## 收发的消息
- 收到 <agent>: "<摘要>"
- 发送给 <agent>: "<摘要>"

## 关键决策
- <决策内容及原因>

## 遇到的问题
- <问题描述和处理方式>

## 经验总结
- <学到了什么，发现了什么规律，有什么可以改进的>

## 明日展望
- <接下来要做什么，有什么预期的挑战>
```

### 各节说明

| 节 | 重要性 | 说明 |
|----|--------|------|
| 处理的 Ticket | 必填 | 从任务查询结果中提取，不要凭记忆 |
| 收发的消息 | 有则写 | 从 inbox 中提取关键消息 |
| 关键决策 | 有则写 | 记录为什么这么做，帮助未来回溯 |
| 遇到的问题 | 有则写 | 记录问题和解决/绕过方式 |
| 经验总结 | **推荐** | **最有价值的部分**——记录你学到的东西 |
| 明日展望 | 推荐 | 帮助你下次被唤醒时快速恢复上下文 |

### 无活动日

如果过去 24 小时没有任何活动（无 ticket、无消息），仍然写日志：

```markdown
# 工作日志 YYYY-MM-DD

今日无任务活动。

## 明日展望
- <如果有待处理的工作，写在这里>
```

## 不同角色的侧重点

| 角色 | 日志侧重 |
|------|---------|
| Product | 需求决策、验收判断、Milestone 进度 |
| Dev | 技术方案、代码实现、遇到的技术难题 |
| QA | 测试覆盖、发现的 bug、测试环境问题 |
| Admin | 系统配置变更、agent 管理操作、故障处理 |
| User | 测试体验、发现的产品问题、改进建议 |
