# Admin Agent 工作手册

## 项目概览

多 Agent 协同工作流项目。详细架构设计见 `project.md`。

## 目录结构

```
ROOT_DIR/
├── project.md                  # 架构设计文档
├── restart_all_agents.sh       # Agent 管理脚本
├── auto_dispatch.sh            # 自动 dispatch 脚本
├── agents/
│   ├── admin/                  # 你（Admin Agent）
│   │   ├── system_prompt.md
│   │   ├── CLAUDE.md           # 本文件
│   │   └── .claude/skills/     # Admin 专属 skill（如 dispatch）
│   ├── product/
│   │   ├── system_prompt.md
│   │   ├── CLAUDE.md
│   │   └── .claude/skills/     # 含 leantime skill（symlink）
│   ├── dev/
│   │   ├── system_prompt.md
│   │   ├── CLAUDE.md
│   │   └── .claude/skills/
│   ├── qa/
│   │   ├── system_prompt.md
│   │   ├── CLAUDE.md
│   │   └── .claude/skills/
│   └── shared/skills/          # 共享 skill 源文件
│       └── leantime/SKILL.md
├── projects/                   # Worker agent 的工作目录
│   └── <project-name>/         # 各项目目录
│       ├── README.md
│       └── skills/             # 项目级 skill
└── services/
    ├── agents-mcp/             # Agents Essentials MCP Server（任务管理 + 调度）
    ├── leantime/               # Leantime Docker 部署
    └── leantime-mcp/           # Leantime MCP Server（旧版，已被 agents-mcp 取代）
```

## Agent 管理

所有 agent 在同一个 tmux session（`agents`）中运行，每个 agent 一个 window（tab）。

### MCP Daemon 架构

agents-mcp 使用中心 daemon + proxy 模式：

- **Daemon**: 一个持久运行的 SSE 服务（`services/agents-mcp`），负责任务管理、自动调度
- **Proxy**: 每个 Claude Code agent 通过轻量级 stdio proxy 连接 daemon
- **Auto-dispatch**: 内置于 daemon，每 30 秒自动检查空闲 agent 并分配任务

```
Claude Code → stdio proxy → SSE → daemon → Leantime API
```

### restart_all_agents.sh 使用方式

```bash
./restart_all_agents.sh              # 重启所有 agent + 确保 daemon 运行
./restart_all_agents.sh --workers    # 重启除 admin 外的所有 agent
./restart_all_agents.sh <name>       # 重启单个 agent
./restart_all_agents.sh --daemon     # 仅重启 MCP daemon
./restart_all_agents.sh --stop-daemon # 停止 MCP daemon
```

### 重启安全流程

1. 用 `tmux capture-pane -t agents:<agent> -p | tail -10` 检查目标 agent 状态
2. 确认 agent 处于 idle（`❯` 提示符，无 `Running…`/`Wandering…`/`esc to interrupt`）
3. 如果 agent 正在工作中，等待其完成或确认重启后能通过 Leantime 恢复工作
4. 执行重启

### Daemon 排障

- 日志: `.daemon.log`
- 检查状态: `lsof -i :8765 -sTCP:LISTEN`
- 手动启动: `AGENTS_CONFIG_PATH=agents.yaml uv run --directory services/agents-mcp agents-mcp --daemon`

## 技能管理

### 技能层级

| 层级 | 位置 | 适用场景 |
|------|------|---------|
| 共享 skill | `templates/shared/skills/` + symlink 到各 agent | 所有 agent 都需要的（如 leantime） |
| Agent 级 skill | `agents/<agent>/.claude/skills/` | 某个 agent 专属（如 admin 的 dispatch） |
| 项目级 skill | `projects/<project>/skills/` | 特定项目的经验和方法论 |

### 处理 skill 创建请求

当其他 Agent 提交"创建通用 skill"的 task 时：
1. 判断是 agent 级还是共享级
2. 使用 `/create-skill` 查看创建共享 skill 的流程
3. 创建后重启相关 agent

## Agent 角色速查

当前团队成员及角色请参考 `agents/shared/team-roster.md`（由 `agents.yaml` 自动生成）。

## 动态扩缩容

### 增加 Agent 实例

在 `agents.yaml` 中为需要扩容的 Agent 设置 `instances` 字段：

```yaml
agents:
  dev:
    role: 开发工程师
    instances: 2  # 创建 dev1, dev2 两个实例
```

然后执行 `./restart_all_agents.sh --workers` 即可自动：
1. `setup-agents.py` 为 dev1、dev2 生成独立工作目录和 system_prompt.md
2. 每个实例拥有独立的 tmux window、Leantime tag（agent:dev1、agent:dev2）
3. auto-dispatch 会分别检查每个实例的任务和状态

### 智能任务分配

使用 `suggest_assignee` 工具获取最佳分配建议：
```
suggest_assignee(role="开发工程师")  # 返回负载最低的 dev 实例
```

使用 `get_agent_status` 查看所有 Agent 的实时状态和负载：
```
get_agent_status(agent="all")
```
