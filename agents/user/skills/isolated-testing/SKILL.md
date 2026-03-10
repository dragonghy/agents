---
name: isolated-testing
description: 隔离测试环境操作指南。创建临时 agent 团队环境，以 "human" 身份指挥开发，测试 Agent-Hub 的用户体验。
allowed-tools: Bash, Read, Glob, Grep
---

# 隔离测试环境操作指南

## 概念

你在 **两套独立的系统** 中工作：

| | 主系统 | 隔离测试系统 |
|--|--------|------------|
| **用途** | 与团队沟通、提交反馈 | 实际测试 Agent-Hub |
| **交互方式** | Leantime MCP tools（`list_tickets`、`send_message` 等） | Bash + curl 命令 |
| **你的角色** | 普通 agent | **"human"**（指挥 agent 团队） |
| **数据** | 生产数据 | 独立数据（互不影响） |

## 完整流程

### Step 1: 创建隔离环境

```bash
python3 tests/e2e_env.py up --name <项目名> --preset full
```

例如要测试开发一个 2048 游戏：
```bash
python3 tests/e2e_env.py up --name game-2048 --preset full
```

输出会显示：
- **Environment**: 环境名称
- **Daemon URL**: 隔离 daemon 地址（如 `http://127.0.0.1:8775/sse`）
- **Project ID**: 隔离 Leantime 项目 ID
- **Work dir**: 工作目录（如 `/tmp/agents-e2e-game-2048/`）

### Step 2: 读取环境信息

```bash
cat /tmp/agents-e2e-<name>/env.json
```

记住两个关键值：
- `port`：隔离 daemon 端口
- `project_id`：隔离 Leantime 项目 ID

后续命令中用变量简化：
```bash
PORT=$(python3 -c "import json; print(json.load(open('/tmp/agents-e2e-<name>/env.json'))['port'])")
PID=$(python3 -c "import json; print(json.load(open('/tmp/agents-e2e-<name>/env.json'))['project_id'])")
```

### Step 3: 启动 Agent 团队

在隔离环境的 tmux session 中启动 agent：

```bash
ENV_NAME=<name>
WORK_DIR="/tmp/agents-e2e-${ENV_NAME}"

# 创建 tmux session
tmux new-session -d -s "e2e-${ENV_NAME}"

# 启动每个 agent
for agent in product-kevin dev-alex qa-lucy; do
  tmux new-window -t "e2e-${ENV_NAME}" -n "$agent"
  tmux send-keys -t "e2e-${ENV_NAME}:${agent}" \
    "cd ${WORK_DIR}/agents/${agent} && claude --dangerously-skip-permissions --append-system-prompt-file system_prompt.md" Enter
done

# 删除默认的空窗口
tmux kill-window -t "e2e-${ENV_NAME}:0" 2>/dev/null || true
```

等待约 30 秒让 agent 完成启动。

### Step 4: 创建任务（你是 "human"）

通过隔离 daemon 的 REST API 创建 ticket，指挥 agent 团队：

```bash
# 创建任务给 Product
curl -s -X POST http://127.0.0.1:${PORT}/api/v1/tickets/create \
  -H "Content-Type: application/json" \
  -d "{
    \"headline\": \"开发一个终端 2048 游戏\",
    \"project_id\": ${PID},
    \"assignee\": \"product-kevin\",
    \"description\": \"请设计并开发一个可以在终端运行的 2048 游戏。\\n\\n要求：\\n- 使用方向键控制\\n- 显示当前分数\\n- 游戏结束时提示\",
    \"priority\": \"high\"
  }"
```

### Step 5: 唤醒 Agent

创建 ticket 后，需要唤醒 agent 让它开始工作：

```bash
# 唤醒 product-kevin
tmux send-keys -l -t "e2e-${ENV_NAME}:product-kevin" \
  "你有新的 Leantime 任务。请查询分配给你的任务（status=3,4）并执行。"
sleep 2
tmux send-keys -t "e2e-${ENV_NAME}:product-kevin" Enter
```

### Step 6: 监控进度

```bash
# 查看某个 agent 的输出（最后 20 行）
tmux capture-pane -t "e2e-${ENV_NAME}:dev-alex" -p | tail -20

# 查看所有 ticket 状态
curl -s "http://127.0.0.1:${PORT}/api/v1/tickets?project_id=${PID}&status=all" | python3 -m json.tool

# 查看某个 ticket 的详情
curl -s "http://127.0.0.1:${PORT}/api/v1/tickets/1" | python3 -m json.tool

# 查看 ticket 的评论
curl -s "http://127.0.0.1:${PORT}/api/v1/tickets/1/comments" | python3 -m json.tool
```

### Step 7: 参与决策（扮演 human）

当 agent 需要你做决策时（如 Product 提交了方案等待审阅），你需要回应：

```bash
# 在 ticket 上添加评论（审阅反馈）
curl -s -X POST http://127.0.0.1:${PORT}/api/v1/tickets/1/comments \
  -H "Content-Type: application/json" \
  -d "{\"comment\": \"方案看起来不错，请继续推进。\"}"

# 将 agent:human 的 ticket 标记为完成（解除 DEPENDS_ON 阻塞）
curl -s -X POST http://127.0.0.1:${PORT}/api/v1/tickets/2/update \
  -H "Content-Type: application/json" \
  -d "{\"status\": 0}"
```

### Step 8: 收集测试结果

测试过程中记录：
- **顺利的地方**：哪些体验是好的
- **卡住的地方**：在哪一步遇到了困难，错误信息是什么
- **困惑的地方**：哪些概念或操作让你费解
- **耗时过长的地方**：哪些步骤花的时间比预期长

### Step 9: 销毁环境

测试完成后，先停止 tmux session 中的 agent，再销毁环境：

```bash
# 停止隔离 tmux session
tmux kill-session -t "e2e-${ENV_NAME}" 2>/dev/null || true

# 销毁隔离环境（停 daemon、删 Leantime 项目、清理目录）
python3 tests/e2e_env.py down --name <name>
```

### Step 10: 提交反馈到主系统

回到主系统，将发现的问题提交给 Product：

```
# 使用你的 MCP tools（不是 curl）
create_ticket(
  headline="用户测试反馈: <项目名> - <问题摘要>",
  assignee="<suggest_assignee(role='product') 返回的 ID>",
  description="<按 CLAUDE.md 中的反馈模板填写>"
)
```

## 查看活跃环境

```bash
python3 tests/e2e_env.py list
```

显示所有活跃的测试环境及其状态。

## 注意事项

1. **每次测试用不同的环境名称**，避免冲突。
2. **测试完成后务必销毁环境**，释放端口和资源。
3. **隔离环境中的 agent 不会自动 dispatch**（daemon 启动时带 `--no-dispatch`），你需要手动唤醒它们。
4. 如果环境创建失败，检查是否有残留的旧环境（`e2e_env.py list`）并清理。
5. 端口范围 8770-8799，最多同时运行 30 个测试环境。
