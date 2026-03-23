---
name: system-testing
description: Agent-Hub 系统测试与安全更新流程。包含隔离环境测试和生产系统安全重启恢复。
---

# Agent-Hub 系统测试与安全更新

## Part A — 隔离环境测试

在独立环境中测试系统变更，不影响生产 agent。每个测试环境拥有：
- 独立的 daemon（不同端口）
- 独立的任务数据库（自动创建/销毁）
- 独立的工作目录（`/tmp/agents-e2e-<name>/`）

### 工具

- `tests/e2e_env.py` — 环境管理器
- `tests/e2e-env.sh` — 便捷 wrapper（等价于 `python3 tests/e2e_env.py`）

### 预设（Presets）

| 预设 | 内容 | 用途 |
|------|------|------|
| `minimal` | 单个 tester agent | 快速验证单个功能 |
| `full` | product-kevin + dev-alex + qa-lucy | 完整工作流测试 |

预设文件位于 `tests/presets/`，可自行添加新预设。

### 完整流程

#### 1. 创建测试环境

```bash
# 使用 minimal 预设（默认）
python3 tests/e2e_env.py up --name mytest

# 使用 full 预设
python3 tests/e2e_env.py up --name mytest --preset full

# 指定端口（默认自动分配 8770-8799）
python3 tests/e2e_env.py up --name mytest --port 8775
```

输出包含：
- `Environment`: 环境名称
- `Daemon URL`: SSE 端点（如 `http://127.0.0.1:8775/sse`）
- `Project ID`: 项目 ID
- `Work dir`: 工作目录路径
- `Config`: 生成的 agents.yaml 路径

#### 2. 查看环境状态

```bash
python3 tests/e2e_env.py list
```

#### 3. 测试 MCP Tools

测试环境的 daemon 运行在独立端口，可以直接调用 REST API：

```bash
# 读取 env.json 获取 daemon 信息
cat /tmp/agents-e2e-mytest/env.json

# 通过 daemon 的 REST API 调用
# 例如：列出 tickets
curl -s "http://127.0.0.1:<port>/api/v1/tickets?project_id=<test_project_id>&status=all" | python3 -m json.tool

# 例如：创建 ticket
curl -s -X POST http://127.0.0.1:<port>/api/v1/tickets/create \
  -H "Content-Type: application/json" \
  -d '{"headline": "Test ticket", "project_id": <test_project_id>}'
```

**注意**：测试环境的数据是独立的，不会污染生产数据。

#### 4. 在测试环境中启动 Agent

如需手动启动 Claude Code agent 连接测试 daemon：

```bash
# 进入测试环境的 agent 工作目录
cd /tmp/agents-e2e-mytest/agents/<agent-name>

# 启动 Claude Code（会自动读取 .mcp.json 连接测试 daemon）
claude --dangerously-skip-permissions --append-system-prompt-file system_prompt.md
```

#### 5. 销毁测试环境

```bash
python3 tests/e2e_env.py down --name mytest
```

自动执行：停止 daemon 进程 → 清理工作目录。

### 元数据

每个环境的元数据保存在 `/tmp/agents-e2e-<name>/env.json`，包含：
- `name`, `preset`, `port`, `daemon_pid`
- `project_id`, `project_name`
- `daemon_url`, `work_dir`, `config_path`
- `task_db_path`

---

## Part B — 系统更新与安全重启

当系统代码发生变更（system prompt、skill、MCP server、脚本等），需要安全地更新生产环境。

### 核心原则

- **不要丢失 agent 的在途工作**：重启前记录每个 agent 的状态，重启后恢复
- **Session 保持**：`restart_all_agents.sh` 使用 `--resume` 恢复 Claude Code session
- **In-progress ticket 恢复**：重启后 dispatch 让 agent 检查并继续在途工作

### 安全重启流程

#### Step 1: Pre-restart — 记录在途工作

```
# 通过 MCP 检查所有 agent 状态
get_agent_status(agent="all")

# 记录哪些 agent 有 in-progress ticket
list_tickets(project_id=3, status="4")
```

**记录内容**：
- 哪些 agent 有 in-progress (status=4) 的 ticket
- 每个 agent 的 tmux 状态（idle 还是 busy）

#### Step 2: Pre-restart — 确认安全重启时机

```bash
# 检查每个 agent 是否处于 idle
tmux capture-pane -t agents:<agent-name> -p | tail -10
```

- 看到 `>` 提示符 = idle，可以安全重启
- 看到 `Running…` / `Wandering…` / `esc to interrupt` = busy，等待完成或确认 ticket 状态能让 agent 恢复

**最佳时机**：所有 worker agent 都 idle 时重启。如果某个 agent 正在工作但有 in-progress ticket，也可以重启——agent resume 后会通过 ticket 恢复上下文。

#### Step 3: 执行重启

根据变更范围选择重启方式：

| 变更内容 | 重启命令 |
|---------|---------|
| MCP server 代码（agents-mcp） | `./restart_all_agents.sh --daemon` 然后 `./restart_all_agents.sh --workers` |
| System prompt / Skill / CLAUDE.md | `./restart_all_agents.sh --workers` |
| 单个 agent 的配置 | `./restart_all_agents.sh <agent-name>` |
| agents.yaml 结构变更 | `./restart_all_agents.sh`（全部重启） |

**重要**：如果修改了 daemon 代码，必须先重启 daemon 再重启 workers，否则 workers 连接的还是旧 daemon。

#### Step 4: Post-restart — 恢复在途工作

重启后，agent 的 Claude Code session 通过 `--resume` 恢复，但 agent 可能不知道自己之前正在做什么。需要主动 dispatch 让它们检查：

```
# 方式 1：通过 MCP 统一 dispatch 所有 agent
dispatch_agents(agent="all")

# 方式 2：只 dispatch 有在途工作的 agent
dispatch_agents(agent="dev-alex")
dispatch_agents(agent="qa-lucy")
```

Dispatch 会向 agent 发送提示，让它检查 in-progress ticket 并继续执行。

#### Step 5: Post-restart — 验证恢复

```
# 确认所有 agent 都在运行
get_agent_status(agent="all")

# 确认在途 ticket 仍然被正确处理
list_tickets(project_id=3, status="4")
```

### 快速参考

```bash
# 只改了 prompt/skill → 重启 workers
./restart_all_agents.sh --workers

# 改了 MCP server → 先 daemon 后 workers
./restart_all_agents.sh --daemon && ./restart_all_agents.sh --workers

# 改了 agents.yaml → 全部重启
./restart_all_agents.sh

# 重启后恢复工作
# （通过 MCP）dispatch_agents(agent="all")
```
