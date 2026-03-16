# 产品规划：支持多项目线并行开发

## 1. 背景与目标

### 现状

当前 Agent-Hub 系统的所有资源围绕一个项目运转：

- **Leantime**：单一 project（`project_id=3`），所有 ticket 混在一起
- **agents.yaml**：一个全局 `leantime.project_id`，`add_dirs` 硬编码在每个 agent 上
- **Skills**：`projects/*/skills/` 下的所有 skill 放在 agents repo 中，被 symlink 到所有 agent
- **Dispatch**：查询单一 project 的 ticket，无项目亲和性

### 目标

让系统能同时运行多个独立项目线，每个项目有自己的 Leantime 空间、skill、工作目录，而 agent 作为共享资源池在项目间灵活分配。**项目的配置和管理由 Admin 统一负责。**

## 2. Project Mapping

### 2.1 项目注册表（`agents.yaml` 新增 `projects` 节）

Admin 在 `agents.yaml` 中维护全局项目注册表：

```yaml
projects:
  agent-hub:
    leantime_project_id: 3
    root_dir: .                              # 相对于 ROOT_DIR
    description: "多 Agent 协同工作流平台"
  vm-mcp:
    leantime_project_id: <新建>
    root_dir: ${VM_MCP_DIR}
    description: "虚拟机管理 MCP Server"
```

每个项目的关键属性：
| 属性 | 说明 |
|------|------|
| `leantime_project_id` | 该项目在 Leantime 中的 project ID |
| `root_dir` | 项目代码根目录（绝对路径或相对于 ROOT_DIR） |
| `description` | 项目简述 |

**管理者**：Admin。新增项目、修改配置、删除项目都由 Admin 在 agents.yaml 中操作。

### 2.2 Agent-项目分配

Admin 在每个 agent 定义中指定其参与的项目：

```yaml
agents:
  product-kevin:
    template: product
    projects: [agent-hub, vm-mcp]    # 跨项目产品管理
  dev-alex:
    template: dev
    projects: [agent-hub]            # Agent-Hub 专属开发
  dev-emma:
    template: dev
    projects: [vm-mcp]              # VM MCP 专属开发
  qa-lucy:
    template: qa
    projects: [agent-hub, vm-mcp]    # 跨项目 QA
  qa-oliver:
    template: qa
    projects: [vm-mcp]              # VM MCP 专属 QA
```

**分配策略**：

| 策略 | 适用场景 | 示例 |
|------|----------|------|
| 专属（单项目）| agent 专注一个项目，减少上下文切换 | dev-alex 只做 Agent-Hub |
| 共享（多项目）| 角色稀缺或需要跨项目协调 | product-kevin 管理所有项目 |

**规则**：
- `projects` 省略时 → 参与所有项目（向后兼容）
- Agent 的 `--add-dir` = 所有已分配项目的 `root_dir` + 显式 `add_dirs`（`add_dirs` 仍支持，用于非项目的额外目录）

## 3. Admin 管理项目的流程

### 3.1 Admin 的项目管理职责

Admin 是项目配置的唯一管理者，负责：
- 注册新项目（添加到 `agents.yaml` 的 `projects` 节）
- 创建对应的 Leantime Project
- 分配 agent 到项目（修改 agent 的 `projects` 字段）
- 项目配置变更后执行 `setup-agents.py` + 安全重启

### 3.2 Agent 请求项目 Access 的流程

当 agent 需要参与一个新项目时：

```
Agent → Admin: "我需要 vm-mcp 项目的 Access"（通过 send_message 或 ticket）
Admin: 审核请求 → 修改 agents.yaml → 运行 setup-agents.py → 重启该 agent
Agent: 重启后自动获得项目的 add_dir、skill、Leantime project 访问权限
```

**这个流程需要写入每个 agent 的 System Prompt**，让所有 agent 都知道：
- 如何查看自己当前有权限的项目（system prompt 中注入的项目列表）
- 如何请求新项目的 access（找 Admin）

### 3.3 System Prompt 中注入的项目信息

`setup-agents.py` 在生成 agent 实例 prompt 时，自动注入：

```markdown
## 你的项目权限

| 项目 | project_id | 代码目录 |
|------|-----------|----------|
| agent-hub | 3 | $AGENTS_ROOT/ |
| vm-mcp | 4 | $VM_MCP_DIR/ |

如需访问未列出的项目，请联系 Admin 申请权限。
```

## 4. 项目 Skills — 利用 Claude Code 自动发现

### 4.1 设计原则

**Skills 跟随项目走，放在项目 repo 的 `.claude/skills/` 下，利用 Claude Code 的自动发现机制。**

Claude Code 会自动从以下位置读取 skills：
1. Agent 的 working directory 下的 `.claude/skills/`
2. 每个 `--add-dir` 目录下的 `.claude/skills/`

因此，当项目的 `root_dir` 通过 `--add-dir` 加入 agent 时，该项目 repo 下 `.claude/skills/` 中的 skills 会被**自动发现**，无需额外的 symlink 或配置。

### 4.2 Skills 存放位置

| Skill 类型 | 存放位置 | 发现方式 |
|------------|---------|----------|
| 全局共享（如 leantime） | `agents/shared/skills/` | `setup-agents.py` symlink 到 agent 的 `.claude/skills/` |
| 角色模板（如 review-qa） | `agents/<template>/skills/` | `setup-agents.py` symlink 到 agent 的 `.claude/skills/` |
| 项目级（如 vmware-setup） | `<project_root>/.claude/skills/` | Claude Code 通过 `--add-dir` 自动发现 |

**不需要 `skills_dir` 配置**，也不需要为项目 skills 做 symlink。

### 4.3 示例

```
Agent dev-alex (projects: [agent-hub]):
  skills 来源：
    1. agents/dev-alex/.claude/skills/    → 共享 + 模板 skills（setup-agents.py 管理）
    2. $AGENTS_ROOT/.claude/skills/  → agent-hub 项目 skills（--add-dir 自动发现）

Agent dev-emma (projects: [vm-mcp]):
  skills 来源：
    1. agents/dev-emma/.claude/skills/    → 共享 + 模板 skills（setup-agents.py 管理）
    2. $VM_MCP_DIR/.claude/skills/  → vm-mcp 项目 skills（--add-dir 自动发现）
```

### 4.4 迁移

现有 Agent-Hub 项目 skills 需要从 `projects/agent-hub/skills/` 迁移到 `$AGENTS_ROOT/.claude/skills/`。`setup-agents.py` 中现有的项目 skill symlink 逻辑可以移除。

## 5. Leantime 多项目管理

**项目隔离**：每个项目一个 Leantime Project，ticket 归属清晰。

| Leantime Project | project_id | 用途 |
|------------------|------------|------|
| Agent-Hub | 3（已有） | Agent-Hub 系统开发 |
| VM MCP | 待创建 | VM MCP Server 开发 |

**Ticket 路由**：
- 创建 ticket 时必须指定正确的 `project_id`
- `suggest_assignee()` 考虑 agent 的项目分配：只推荐已分配该项目的 agent

**跨项目依赖**：
- `DEPENDS_ON` 仍然按 ticket ID 全局匹配（Leantime ticket ID 全局唯一）
- 跨项目依赖天然支持，无需额外处理

## 6. Dispatch 多项目感知

**现状**：daemon 用单一 `project_id` 查询所有 ticket。

**改为**：
1. 加载 `agents.yaml` 中的 `projects` 映射
2. 对每个 agent，只查询其已分配项目的 Leantime project ID
3. 合并查询结果后按正常逻辑 dispatch

```python
for agent in agents:
    project_ids = [projects[p]["leantime_project_id"] for p in agent["projects"]]
    pending = []
    for pid in project_ids:
        pending += query_tickets(project_id=pid, tag=f"agent:{agent.name}", status=[3, 4])
    if pending and is_idle(agent):
        dispatch(agent)
```

## 7. 需要修改的文件

| 文件 | 改动 | 复杂度 |
|------|------|--------|
| `agents.yaml` | 新增 `projects` 节，agent 添加 `projects` 字段 | 低 |
| `setup-agents.py` | `add_dirs` 从 projects 推导，项目列表注入 prompt，移除项目 skill symlink 逻辑 | 中 |
| `agent-config.py` | 新增 `list-projects`、`get-project-dirs` 命令 | 低 |
| `services/agents-mcp/` | dispatch 查询多个 project_id，DEPENDS_ON 跨项目检查 | 中 |
| `auto_dispatch.sh` | 同上（fallback 脚本） | 低 |
| Agent system_prompt 模板 | 去除硬编码 project_id，添加"如何请求项目 Access"说明 | 低 |
| `agents/shared/skills/leantime/SKILL.md` | `project_id=3` 硬编码改为引用注入的项目列表 | 低 |

## 8. 目录结构

```
agents repo (ROOT_DIR = $AGENTS_ROOT/):
├── agents.yaml                    # 全局配置（含 projects 注册表）
├── .claude/skills/                # Agent-Hub 项目 skill（通过 --add-dir 自动发现）
│   ├── development-workflow/
│   └── system-testing/
├── agents/
│   ├── shared/skills/             # 全局共享 skill（setup-agents.py symlink）
│   └── <template>/skills/         # 角色模板 skill（setup-agents.py symlink）
├── projects/
│   └── agent-hub/
│       └── README.md              # Agent-Hub PRD

vm-mcp repo ($VM_MCP_DIR/):
├── .claude/skills/                # VM MCP 项目 skill（通过 --add-dir 自动发现）
│   └── vmware-setup/
├── src/                           # VM MCP 源码
└── ...
```

## 9. 实施计划

### Phase 1: 配置层（低风险，不影响运行中的 agent）
1. Admin 在 `agents.yaml` 中添加 `projects` 节
2. Admin 给每个 agent 添加 `projects` 字段
3. 保留 `add_dirs` 作为兼容

### Phase 2: 工具链适配
4. 修改 `setup-agents.py`：从 projects 推导 `add_dirs`，移除项目 skill symlink 逻辑
5. 修改 `setup-agents.py`：在生成的 prompt 中注入项目列表 + "请求 Access" 流程
6. 修改 `agent-config.py`：新增 project 相关命令
7. 修改 Leantime SKILL.md 和 system_prompt 模板：去除 project_id 硬编码

### Phase 3: Dispatch 适配
8. 修改 agents-mcp daemon：多 project_id 查询
9. 修改 `auto_dispatch.sh`（fallback）

### Phase 4: Leantime 建设 + 迁移 + 验证
10. Admin 创建 VM MCP Leantime 项目
11. 迁移 Agent-Hub skills：`projects/agent-hub/skills/` → `$AGENTS_ROOT/.claude/skills/`
12. 迁移 VM MCP skills 到 `$VM_MCP_DIR/.claude/skills/`
13. 端到端验证：创建 VM MCP ticket → dispatch 到正确 agent → agent 在正确目录工作并获得项目 skills

每个 Phase 独立可测试，合并后安全重启即可生效。
