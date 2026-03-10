# Agent-Hub

多 Agent 协同工作流平台。多个 Claude Code CLI agent 通过 Leantime + MCP 协作完成软件工程任务。

## 架构

```
┌──────────────┐
│   Leantime   │  项目管理后端（ticket、评论、项目）
└──────┬───────┘
       │ JSON-RPC API
┌──────┴───────┐
│  MCP Daemon  │  中心 SSE 服务（任务管理、消息、调度）
│  (port 8765) │  30 秒自动 dispatch 空闲 agent
└──┬───┬───┬───┘
   │   │   │   stdio proxy
┌──┴┐┌─┴─┐┌┴──┐
│ P ││ D ││ Q │  Claude Code CLI agent（各自 tmux window）
└───┘└───┘└───┘
```

- **Agent 运行时**：每个 agent 是一个 Claude Code CLI 实例，运行在 tmux 的独立 window 中
- **MCP Daemon**：agents-mcp SSE 服务，agent 通过 stdio proxy 连接
- **Leantime**：项目管理后端，ticket 在 Dev→QA→Product 间通过 reassign_ticket 流转
- **Auto-dispatch**：内置于 daemon，消息优先，然后检查 Leantime 任务

## 开发流程

**所有代码变更必须在 git worktree 中进行。** 详见 `/development-workflow` skill。

简要流程：
1. `git worktree add ../agents-dev-<feature> -b feature/<name>` 创建 worktree
2. 在 worktree 中开发、测试（使用 `/system-testing` skill 的隔离环境）
3. 合并回 main → 生产环境 pull + 安全重启

## 项目级 Skills

| Skill | 说明 |
|-------|------|
| `development-workflow` | Git worktree 开发流程，安全修改 agent-hub 代码 |
| `system-testing` | 隔离环境测试 + 系统安全更新与重启恢复 |

## 目录结构

```
ROOT_DIR/
├── agents.yaml                 # Agent 配置（角色、MCP、daemon）
├── setup-agents.py             # 工作区生成（.mcp.json、skill、roster）
├── restart_all_agents.sh       # Agent 管理（启动、重启、daemon）
├── agent-config.py             # Session 管理和配置查询
├── agents/
│   ├── shared/skills/          # 共享 skill 源文件
│   ├── admin/                  # Admin agent（非 dispatchable）
│   ├── product/                # Product 模板
│   ├── dev/                    # Dev 模板
│   ├── qa/                     # QA 模板
│   ├── product-kevin/          # Product 实例（自动生成）
│   ├── dev-alex/               # Dev 实例（自动生成）
│   ├── dev-emma/               # Dev 实例（自动生成）
│   ├── qa-lucy/                # QA 实例（自动生成）
│   └── qa-oliver/              # QA 实例（自动生成）
├── projects/
│   └── agent-hub/
│       ├── README.md           # 本文件
│       └── skills/             # 项目级 skill
├── services/
│   ├── agents-mcp/             # MCP Daemon 源码
│   └── leantime/               # Leantime Docker 部署
└── tests/
    ├── e2e_env.py              # 隔离测试环境管理器
    └── presets/                # 测试预设（minimal, full）
```

## 关键文件

| 文件 | 说明 |
|------|------|
| `agents.yaml` | Agent 定义、MCP 配置、daemon 端口、name_pool |
| `setup-agents.py` | 生成 .mcp.json、skill symlink、team-roster、实例 prompt |
| `restart_all_agents.sh` | 启动/重启 agent 和 daemon |
| `agent-config.py` | 查询 session ID、agent 列表、add_dirs |
| `services/agents-mcp/` | MCP Daemon（任务管理、消息、profile、dispatch） |
| `tests/e2e_env.py` | 隔离环境（独立 daemon、Leantime project、tmux session） |
