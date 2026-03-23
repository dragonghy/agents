---
name: inspect-agents
description: 检查所有 Agent 过去 24-48 小时的行为，发现问题并创建修复 ticket。用于定期审计。
allowed-tools: Bash, Read, Glob, Grep, mcp__agents__list_tickets, mcp__agents__get_ticket, mcp__agents__get_comments, mcp__agents__get_agent_status, mcp__agents__get_inbox, mcp__agents__create_ticket, mcp__agents__add_comment, mcp__agents__list_agents, mcp__agents__get_profile
---

# Agent 行为检查手册

## 概述

定期检查所有 Agent 的行为，发现问题并创建修复 ticket。这个检查应该至少每 24 小时执行一次。

## 检查步骤

### Step 1: 深度行为审计（自动化）

使用 `read_agent_log.py` 工具自动分析所有 agent 的 conversation log：

```bash
# ⚠️ 必须用 --hours 24，不要用 --hours 6
# 教训：6h 窗口会遗漏历史性系统事件（如凌晨发生的 mass MCP stuck）
python3 tools/read_agent_log.py all --hours 24 --json

# 扫描单个 agent，看详细时间线
python3 tools/read_agent_log.py qa-lucy --hours 24 --max-messages 200

# 扫描所有 agent，输出文本格式（更易读）
python3 tools/read_agent_log.py all --hours 24
```

**工具会自动检测的异常模式**：
- `mcp_call_stuck` [高危]: agent 最后一条消息是 MCP tool_use 且长时间无后续输出（被阻塞）
- `direct_sqlite_access` [高危]: agent 绕过 MCP 直接查 SQLite（如 `sqlite3 .agents-mcp.db`）
- `direct_http_api` [高危]: agent 绕过 MCP 直接 curl REST API
- `repeated_tool_calls` [中危]: 同一工具连续调用 5+ 次（可能死循环）
- `missing_inbox_check` [中危]: dispatch 唤醒后未检查 inbox
- `missing_ticket_check` [低危]: dispatch 唤醒后未检查 tickets
- `reserved_port_usage` [中危]: 使用了保留端口 8765/9090

**优先处理高危和中危异常**。低危异常仅需记录，不一定要创建 ticket。

### Step 1b: 终端全量检查（必须覆盖所有 agent）

**重要：必须检查每一个 agent 的终端输出，不能选择性跳过。**

`get_agent_status` 返回的 "idle" 状态不代表 agent 健康——一个卡在 MCP 调用上的 agent 也显示 "idle"。

```bash
# 1. 检查所有 agent 进程状态
for w in $(tmux list-windows -t agents -F "#{window_name}"); do
  pid=$(tmux list-panes -t "agents:$w" -F "#{pane_pid}" 2>/dev/null)
  children=$(pgrep -P "$pid" 2>/dev/null | head -5)
  if [ -n "$children" ]; then
    echo "$w: ALIVE"
  else
    echo "$w: NO_CHILDREN (crashed?)"
  fi
done

# 2. 对每个 agent 抓取终端最后 10 行，快速扫描异常
#    重点关注：
#    - "Running…" 后面跟着 >5 分钟的持续时间 → MCP 调用卡住
#    - "Error" / "Failed" / "timed out" → 未处理的错误
#    - "ssh -o ConnectTimeout" (running) → 残留 SSH 连接
for w in $(tmux list-windows -t agents -F "#{window_name}"); do
  echo "=== $w ==="
  tmux capture-pane -t "agents:$w" -p -S -10 2>/dev/null | tail -10
  echo ""
done

# 3. ⚠️ 终端 stuck 时长扫描（JSONL 盲区补救）
# read_agent_log.py 只读最近 200 条 JSONL 消息，活跃 agent 的近期 stuck 调用
# 可能不在这 200 条之内！必须用终端扫描来补救。
# 教训来源：user-jack browser_deploy 卡 11h+，JSONL 24h 扫描报告 0 stuck (#383)
for w in $(tmux list-windows -t agents -F "#{window_name}"); do
  stuck=$(tmux capture-pane -t "agents:$w" -p -S -10 2>/dev/null | grep -oE '(Running|Beboppin|Moseying|Sautéed|Baked|Brewed|Churned|Cogitated).*\([0-9]+h' | head -1)
  [ -n "$stuck" ] && echo "🔴 $w: $stuck"
done

# 4. 对发现异常的 agent 再抓取更多行（200 行）深入分析
# tmux capture-pane -t agents:<agent> -p -S -200

# 5. 检查 agent status via API
# get_agent_status(agent="all")
```

**必须检查的终端特征**：
- `✳ Beboppin'…/Running…/Moseying…` 后跟 `(Xh Ym)` 且时间 > 30 分钟 → **MCP 调用卡住，需要重启**
- `MCP proxy: Still disconnected` → agent 无法通过 MCP 通信
- 后台进程指示器（如 "2 bashes · ↓ to view"）→ 残留进程

**⚠️ 必须交叉验证 tmux_status 与终端实际状态**：

`get_agent_status` 返回的 `tmux_status` **两个方向都不可信**：
- `tmux_status: idle` 不代表健康——卡住的 agent 也显示 idle
- `tmux_status: busy` 不代表在工作——cancelled thinking task 残留 "esc to interrupt" 会导致误判为 busy

**必须用终端 ❯ prompt 做最终判断**：
- 有 ❯ prompt → agent 实际空闲（无论 tmux_status 报告什么）
- 无 ❯ prompt + "esc to interrupt" → agent 实际在处理（或卡住）

**orphaned agent 检测规则**：如果一个 agent 终端有 ❯ prompt 但 `get_agent_status` 返回 `is_idle: false`，这个 agent 是 **orphaned**——dispatcher 认为它在忙所以不会给它派新任务，但它实际空闲。**必须重启修复**。

教训来源：user-jack 因 cancelled thinking task (`✳ ... ◼`) 被误判为 busy，20+ 小时未被 dispatch（#341）。

### Step 2: 读取日志

```bash
# 读取每个 agent 的最新日志
cat agents/<agent>/journal/$(date +%Y-%m-%d).md
# 如果今天没有日志，读昨天的
cat agents/<agent>/journal/$(date -v-1d +%Y-%m-%d).md
```

### Step 3: 检查项目

查看每个 agent 过去 24 小时处理的 ticket：
```
list_tickets(assignee="<agent>", status="all", dateFrom="<yesterday>")
```

## 检查清单

### 问题类别 1: 轻度死循环 / 冗余操作

**症状**：
- 终端显示重复的操作（同样的 MCP 调用出现多次）
- 日志显示多次尝试同一操作但无进展
- Agent 在两个状态之间来回切换（如 reassign → receive → reassign）

**检查方法**：
- 在终端输出中搜索重复模式
- 查看 ticket 评论历史，看是否有来回 reassign
- 检查 context 消耗速度是否异常（正常一个任务消耗 10-30%，异常可能 50%+）

**处理**：
- 如果 agent 当前在循环中 → 立即重启该 agent
- 创建 ticket 描述循环场景，分配给相关 Dev 修复根因

### 问题类别 2: 资源冲突

**症状**：
- 终端显示 git merge conflict、abort、或 port conflict
- 多个 agent 同时修改同一文件
- 后台进程占用端口（残留的 http.server、npm run dev 等）

**检查方法**：
```bash
# 检查 git 状态
git status
# 检查端口占用
lsof -i :3000 -i :5173 -i :8080 -i :8765 -i :9090

# 检查残留的 agent_hub 进程
pgrep -f "python.*agent_hub" | wc -l
```

**处理**：
- 清理残留进程
- 解决 merge conflict
- 如果是系统性问题（如 worktree 机制有缺陷），创建 ticket

### 问题类别 3: 未沉淀的经验

**症状**：
- 日志显示花了大量时间研究/调试某个问题
- 终端显示多轮 WebSearch / 文件搜索 / 试错
- 最终解决了但没有创建 skill 或更新文档

**检查方法**：
- 阅读日志中"遇到的问题"和"经验总结"部分
- 看这些经验是否已被记录为 skill（检查 `templates/*/skills/` 和 `projects/*/skills/`）

**处理**：
- 创建 ticket 要求相关 agent 将经验写成 skill
- 或直接自己写 skill（如果是通用知识）

### 问题类别 4: 未上报的 Bug

**症状**：
- 终端显示错误/异常但 agent 自己 workaround 了
- 日志提到"遇到 XXX 问题，通过 YYY 绕过"但没有创建 ticket
- 重复出现的问题（在多个 agent 或多天中出现）

**检查方法**：
- 搜索终端输出中的 "Error"、"Failed"、"workaround"、"绕过"
- 对比 ticket 列表，看是否有遗漏的 bug report

**处理**：
- 代 agent 创建 bug ticket
- 如果是已知问题，检查是否有人在修

### 问题类别 5: 跨团队路由错误

**症状**：
- Agent 在处理不属于自己团队/项目的 ticket
- 例如：Trading 项目的 PM 在做 Agent-Hub 的验收
- `suggest_assignee` 返回了错误团队的 agent

**检查方法**：
- 看每个 agent 处理的 ticket 是否与其 assigned 项目匹配
- 特别关注 Product Manager 和 QA，他们最容易被错误路由

**团队项目对照表**（需要根据实际团队更新）：
| 团队 | Product | Dev | QA | User | 项目 |
|------|---------|-----|-----|------|------|
| Agent-Hub | product-kevin | dev-alex, dev-emma | qa-lucy, qa-oliver | user-sophia | Agent-Hub / VM MCP |
| Founder | product-mia | dev-liam | qa-chloe | user-james | SEOPilot / SEOPilot Lite |
| Trading | product-sarah | — | — | — | Trading Platform |
| VM MCP | product-lisa | dev-emma | qa-oliver | user-jack | VM MCP |

**处理**：
- 检查 prompt 中的 routing 指令是否正确
- 更新 `suggest_assignee` 调用方式

### 问题类别 6: MCP 调用卡住

**症状**：
- 终端显示 `· Running…` 或 `· Moseying…` 后跟超过 5 分钟的持续时间
- `read_agent_log.py` 报告 `mcp_call_stuck` 异常
- Agent 的 JSONL log 最后一条消息是 `tool_use`，之后长时间没有新消息
- `get_agent_status` 可能仍然显示 "idle"（误导性！）

**检查方法**：
- Step 1 的 `read_agent_log.py` 自动检测
- Step 1b 的终端全量检查中查看 "Running…" 持续时间
- **不要信任 "idle" 状态**——卡住的 agent 也显示 idle

**历史案例**：
- user-jack: `browser_deploy` 卡住 2h+（#289）
- dev-alex: `update_profile` 卡住 11h+（#338）
- 2026-03-16: **10/16 agent 同一天出现 mcp_call_stuck**，卡住工具各不相同（send_message, update_profile, get_inbox, list_tickets, Bash, TaskCreate），持续 13h~24h，全部自行恢复
- 根因: MCP proxy 或 daemon 端无超时保护

**处理**：
- 立即通知 admin 重启该 agent
- 记录卡住的工具名和持续时间
- 如果是反复出现的问题，创建 ticket 要求增加超时机制

### 问题类别 7: Orphaned Agent（tmux_status 误判导致无法接收 dispatch）

**症状**：
- Agent 终端显示 ❯ prompt（实际空闲），但 `get_agent_status` 返回 `is_idle: false, tmux_status: busy`
- Agent 长时间（数小时甚至数天）未被 dispatch 新任务
- 通常由 **cancelled thinking task** 导致：`✳ ... (thinking)` 后跟 `◼`，"esc to interrupt" 残留在 status bar

**检查方法**：
- Step 1b 终端检查中，对每个 agent 同时看：
  1. 是否有 ❯ prompt（终端实际状态）
  2. `get_agent_status` 的 `is_idle` 值
- 如果 **有 ❯ 但 is_idle=false** → orphaned agent

**历史案例**：
- user-jack: self-restart 后 thinking task cancelled，tmux_status=busy 误判，20+ 小时未被 dispatch（#341）

**处理**：
- **必须重启**该 agent 以清除残留 task 状态
- 重启后确认 tmux_status 恢复为 idle

### 问题类别 8: Broken Session (tool use concurrency 错误)

**症状**：
- 终端反复显示 `API Error: 400 due to tool use concurrency issues. Run /rewind to recover the conversation.`
- Dispatcher 每次唤醒 agent 都触发同样的错误，形成死循环
- Agent 的 `❯` prompt 存在但无法正常响应任何指令

**检查方法**：
```bash
# 在 Step 1b 终端检查中，查找 concurrency 错误
for w in $(tmux list-windows -t agents -F "#{window_name}"); do
  broken=$(tmux capture-pane -t "agents:$w" -p -S -15 2>/dev/null | grep -c "tool use concurrency" || true)
  [ "$broken" -gt 0 ] && echo "🔴 $w: BROKEN SESSION (concurrency error x${broken})"
done
```

**历史案例**：
- 2026-03-20: product-lisa 和 product-mia 同时陷入 concurrency 错误死循环，dispatcher 反复唤醒但每次都失败

**处理**：
- 使用项目根目录的 `repair-agent.sh` 脚本自动修复：
  ```bash
  ./repair-agent.sh <agent-name>
  ```
- 脚本流程：
  1. 从旧 session 的 JSONL 日志提取最后 15 条有意义的消息
  2. 读取最近的 journal 日志
  3. Graceful 退出旧 session（/exit → 等待 → force kill）
  4. 启动新 session（不使用 --resume，避免继承损坏的 context）
  5. 发送 restoration prompt，要求 agent 先读旧 JSONL + journal 恢复上下文
  6. 自动更新 `.agent-sessions` 中的 session ID
- **注意**：Inspector 自己没有权限执行 repair-agent.sh（只读操作原则）。发现 broken session 后，**通知 admin 执行修复**，并在报告中标注。
- 如果有多个 agent 同时出现，说明可能是 daemon/MCP proxy 的系统性问题，需要额外创建 ticket 调查根因。

### 问题类别 9: Context 相关（仅记录，通常不需要处理）

**重要认知**：
- Claude Code 有 **auto-compact** 机制，context 满了会自动压缩，这是正常行为，不是问题。
- **重启不会减少 context**——重启后 session resume，context 不变。
- Context 低（哪怕 <5%）不代表 agent 有问题，只要它还在正常工作就无需干预。

**唯一需要关注的情况**：
- Agent context 低 **且** 同时表现出工作异常（如遗忘上下文、重复做已完成的事）
- 这种情况说明 auto-compact 丢失了关键信息，可以考虑让 agent 写完当前任务后重启（新 session 从头开始）

**不要做**：
- ❌ 不要因为 context 百分比低就报告为问题
- ❌ 不要因为 context 低就重启 agent
- ❌ 不要创建 context 相关的 ticket

**巡检报告中的处理**：
- Context 百分比仅作为参考信息记录在健康状态总览表中
- 只在 agent 同时有功能异常时才作为问题上报

## 输出格式

检查完成后，输出以下格式的报告：

```markdown
# Agent 行为检查报告 YYYY-MM-DD

## 健康状态总览

| Agent | 进程 | Context | 状态 | 问题 |
|-------|------|---------|------|------|
| product-kevin | ALIVE | 8% | idle | ✅ 正常 |
| dev-alex | ALIVE | 45% | busy | ✅ 正常 |
| ... | ... | ... | ... | ... |

## 发现的问题

### 问题 1: [描述]
- **类别**: [死循环/资源冲突/未沉淀经验/未上报bug/路由错误]
- **涉及 Agent**: [agent ID]
- **详情**: [具体描述]
- **处理**: [已创建 ticket #XXX / 已重启 / 已修复]

### 问题 2: ...

## 建议

- [系统性改进建议]
```

## 执行后操作

1. 将报告保存到 `agents/admin/journal/YYYY-MM-DD-inspection.md`
2. 对发现的问题创建对应 ticket
3. 需要重启的 agent 执行重启
4. 系统性问题创建改进 ticket 分配给相关团队
