# Agent-Hub 开源发布方案研究

## 1. 竞品分析

### 直接竞品（Claude Code 多 Agent 编排）

| 项目 | Stars | License | 特点 | 与我们的差异 |
|------|-------|---------|------|-------------|
| [claude-squad](https://github.com/smtg-ai/claude-squad) | 6.3k | AGPL-3.0 | tmux 管理多个 Claude Code 会话 | 并行独立 agent，无角色分工、无项目管理 |
| [ccswarm](https://github.com/nwiizo/ccswarm) | ~120 | MIT | Git worktree 隔离 + 消息系统 | Rust 写，无 Leantime 集成，无 Dev/QA/Product 流程 |
| [ruflo](https://github.com/ruvnet/ruflo) | ~20k | MIT | 60+ 专用 agent swarm | 营销重于实现，无真实工作流 |
| [Auto-Claude](https://github.com/AndyMik90/Auto-Claude) | - | MIT | 自主多会话编码 | 简单自动化，无团队协作 |

### 我们的独特价值

**没有竞品实现了完整的软件工程团队工作流。** 大多数项目是"并行跑 N 个 Claude 会话"，而我们实现了：
- 角色分工（Product/Dev/QA）+ 系统提示词定义职责
- 项目管理集成（Leantime ticket 生命周期：Product→Dev→QA→Product）
- MCP daemon 中心化协调（消息、dispatch、profile、智能任务分配）
- Git worktree 隔离开发
- Milestone 驱动的交付流程

## 2. 发布方式选项

### 方案 A：GitHub 公开仓库（推荐）

**适合**：最大化影响力和社区贡献。

操作清单：
1. 清理敏感数据（API key、密码、个人路径、邮箱）
2. 添加 LICENSE 文件
3. 清理 git 历史（用 `git-filter-repo` 移除凭据）
4. 编写 README + 快速上手指南
5. 在现有 GitHub 仓库切换为 public

### 方案 B：PyPI 发布 agents-mcp

**适合**：让 agents-mcp daemon 成为可安装的独立工具。

```bash
pip install agents-mcp
agents-mcp --daemon --port 8765
```

当前 `pyproject.toml` 已配置好入口点，补充 README 和版本号即可发布。

### 方案 C：Docker Compose 全栈部署

**适合**：一键体验完整系统。

提供 `docker-compose.yml`：
- Leantime（现有官方镜像）
- agents-mcp daemon
- 预配置示例 agent

用户只需 `docker compose up` 即可体验。

### 推荐组合：A + B + C

三种方式并行，覆盖不同用户需求：
- 想了解架构/贡献代码 → GitHub 仓库
- 想在自己项目中用 daemon → `pip install agents-mcp`
- 想快速体验 → `docker compose up`

## 3. License 选择

### 关键考量

| 因素 | 分析 |
|------|------|
| Leantime 是 AGPL | 我们通过 HTTP/JSON-RPC API 交互（独立进程），不触发 AGPL 传染。但 `services/leantime/plugins/` 中的插件运行在 Leantime 内部，受 AGPL 约束 |
| Claude Code 是专有软件 | 类似依赖 git/docker，列为外部运行时依赖即可，不影响我们的 license |
| leantime-mcp 子树 | 已有 MIT license，保持不变 |

### 推荐

| 组件 | License | 理由 |
|------|---------|------|
| 主项目（agents-mcp, 模板, 工具链） | **Apache 2.0** | 专利保护，多人协作标准，Google ADK / AWS Agent Orchestrator 同类选择 |
| Leantime 插件 | **AGPL-3.0** | 运行在 AGPL 进程内，需遵守 |
| 文档 | **CC-BY-4.0** | 开放文档标准 |

如果更偏向简洁，**MIT** 也完全可以（CrewAI、ccswarm 均用 MIT）。

## 4. 发布前必须处理的事项

### 紧急（安全）

| 问题 | 位置 | 处理方式 |
|------|------|---------|
| Leantime API key 硬编码 | `agents.yaml` line 7 | 改为环境变量 `$LEANTIME_API_KEY` |
| MySQL 密码 | `services/leantime/.env` | 改为 `.env.example` 带占位符 |
| Docker 默认密码 | `docker-compose.yml` | 移除默认值，强制用 `.env` |
| Git 历史含凭据 | 多个 commit | 用 `git-filter-repo` 清理或新建仓库 |

### 重要（可移植性）

| 问题 | 位置 | 处理方式 |
|------|------|---------|
| 绝对路径 `/Users/huayang/code/` | `agents.yaml`, 多个文档 | 改为相对路径或 `$HOME` 变量 |
| 个人邮箱 | `agents.yaml` line 8 | 模板化 |
| 硬编码 project_id | SKILL.md, 文档 | 已部分解决（多项目支持），继续完善 |

### 需要新增的文件

| 文件 | 内容 |
|------|------|
| `LICENSE` | Apache 2.0 全文 |
| `README.md`（重写） | 项目介绍 + 架构图 + 快速上手 + 安装 |
| `CONTRIBUTING.md` | 贡献指南、PR 流程 |
| `AGENTS.md` | AI agent 在此仓库工作的说明（新标准） |
| `docs/getting-started.md` | 详细安装和配置指南 |
| `docs/architecture.md` | 系统架构文档 |
| `.env.example` | 环境变量模板 |

### 国际化考虑

当前文档和系统提示词全部中文。发布前需决定：
- **方案 1**：保持中文，README 加英文摘要（面向中文社区）
- **方案 2**：核心文档翻译为英文（面向全球社区）
- **方案 3**：双语（工作量最大，但覆盖最广）

## 5. 发布节奏建议

### Phase 1：准备（1-2 周）
- 凭据清理 + `.env.example`
- 添加 LICENSE
- 重写 README（英文 + 中文）
- 添加 `docs/getting-started.md`

### Phase 2：发布（1 周）
- Git 历史清理或新建仓库
- GitHub 仓库公开
- PyPI 发布 `agents-mcp`
- 写一篇介绍文章（可选）

### Phase 3：社区建设（持续）
- GitHub Issues 模板
- Discussion 开启
- 响应社区 PR/Issue
- 持续改进文档

## 6. 仓库大小优化

当前 152 MB，主要是 Python venv 和 lockfile。清理后约 5-10 MB：
- 确保 `.venv/` 在 `.gitignore`
- `uv.lock` 保留（可复现构建）
- 移除 `.agents-mcp.db*`（运行时生成）
