---
name: dispatch
description: 唤醒空闲的 worker agent，让它检查并执行新任务。用法：/dispatch <agent> 或 /dispatch all
argument-hint: "[<agent>|all]"
allowed-tools: Bash, mcp__agents__list_tickets, mcp__agents__dispatch_agents
---

# Dispatch Agent

唤醒指定的 worker agent，让它检查新任务。

## 参数

- `$ARGUMENTS` 指定目标 agent：`product`、`dev`、`qa`，或 `all` 唤醒所有 worker。

## 执行步骤

### 1. 确定目标 agent 列表

- 如果参数是 `all`，目标为所有 dispatchable agent（通过 `python3 agent-config.py list-workers` 获取）
- 否则目标为指定的单个 agent
- 只允许 dispatchable agent（不能 dispatch 自己）
- `agent:human` 不可 dispatch（无对应 tmux window，仅作为 Human 待办提醒）

### 2. 对每个目标 agent 执行

#### 2a. 检查 agent 的 tmux window 是否存在

```bash
tmux list-windows -t agents -F '#{window_name}' 2>/dev/null | grep -qx "<agent>"
```

- 如果 window 不存在，先用 restart 脚本重启它：
  ```bash
  ./restart_all_agents.sh <agent>
  ```
  然后等待 5 秒让 agent 启动。

#### 2b. 检查 agent 是否空闲

读取 tmux pane 的最后 10 行（过滤空行，因为 Claude Code TUI 的可见区域底部有大量空行）：

```bash
output=$(tmux capture-pane -t agents:<agent> -p | grep -v '^[[:space:]]*$' | tail -10)
```

判断规则（按优先级）：

1. **工作中**：如果输出包含以下任一特征，说明 agent 正在执行任务，**跳过**：
   - `Running…` — 正在执行命令
   - `Wandering…` — 正在思考
   - `esc to interrupt` — 有可中断的操作在进行

   ```bash
   echo "$output" | grep -qE 'Running…|Wandering…|esc to interrupt'
   ```

2. **空闲**：排除工作中后，如果输出包含以 `❯` 开头的行，说明 agent 在等待输入：

   ```bash
   echo "$output" | grep -q '^❯'
   ```

   注意：`❯` 后面可能有 placeholder 文字，不影响判断。

3. **状态不明**：两者都不匹配，可能 agent 未完全启动，视为不可用，**跳过**。

#### 2c. 发送唤醒消息（仅对空闲 agent）

**重要**：必须严格按以下三步执行，**绝对不能**把文本和 Enter 放在同一条 `tmux send-keys` 命令中。

```bash
# 第 1 步：用 -l（literal）发送文本，不发 Enter
tmux send-keys -l -t agents:<agent> "你有新任务。请使用 /tasks 查看使用手册，然后查询分配给你的待办任务（status=3,4）并执行。"
# 第 2 步：等待 2 秒，让 TUI 完全接收并渲染文本
sleep 2
# 第 3 步：单独发送 Enter 键提交
tmux send-keys -t agents:<agent> Enter
```

**常见错误（禁止）**：
- `tmux send-keys -t agents:<agent> "文本" Enter` — 文本和 Enter 同时发送，TUI 来不及处理
- `sleep 1` — 等待时间太短，不可靠

### 3. 汇报结果

告诉用户每个目标 agent 的处理结果：
- 已唤醒（发送了消息）
- 已跳过（正在工作中）
- 已跳过（状态不明）
- 已重启（window 不存在，重新启动后发送了消息）
