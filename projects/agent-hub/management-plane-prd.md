# Agent Hub Cloud — Management Plane PRD

> Status: 设计稿
> Parent: #320 SaaS 产品设计
> Author: product-kevin
> Date: 2026-03-17

## 概述

Management Plane 是 Agent Hub Cloud 的控制层，负责用户管理、实例生命周期和认证配置。它是一个独立的 Web 应用，管理多个 Agent Hub 实例。

## 架构

```
                     ┌────────────────────────────────┐
                     │    Management Plane             │
                     │    (control.agenthub.cloud)     │
                     │                                 │
                     │  ┌──────────┐  ┌─────────────┐ │
                     │  │ Auth     │  │ Instance    │ │
                     │  │ Service  │  │ Manager     │ │
                     │  └──────────┘  └─────────────┘ │
                     │  ┌──────────┐  ┌─────────────┐ │
                     │  │ Web UI   │  │ SQLite/PG   │ │
                     │  │ (React)  │  │ Database    │ │
                     │  └──────────┘  └─────────────┘ │
                     └───────┬──────────────┬─────────┘
                             │              │
               ┌─────────────┤              ├─────────────┐
               │             │              │             │
        ┌──────▼──────┐ ┌───▼────────┐ ┌───▼────────┐   ...
        │ Instance A  │ │ Instance B │ │ Instance C │
        │ (alice)     │ │ (bob)      │ │ (carol)    │
        │             │ │            │ │            │
        │ daemon      │ │ daemon     │ │ daemon     │
        │ agents      │ │ agents     │ │ agents     │
        └─────────────┘ └────────────┘ └────────────┘
```

每个 Instance = 一个独立的 Docker Compose 部署（daemon + agents 容器）

## 用户旅程

### 首次使用

```
1. 访问 agenthub.cloud → 看到 Landing Page
2. 点击 "Get Started" → 注册页面
3. 输入 Email + Password → 创建账号
4. 登录后进入 Dashboard → 空状态，提示创建第一个 Company
5. 点击 "Create Company" → 输入公司名称
6. 进入 Setup 页面 → 三步配置：
   a. Agent 团队选择（Solo / Standard / Full / Custom）
   b. Claude Code 认证配置（粘贴 OAuth token 或 API key）
   c. 确认并创建
7. 系统自动部署 Agent Hub 实例（显示进度条）
8. 部署完成 → 跳转到该实例的 Web UI（Dashboard、Tickets 等）
```

### 日常使用

```
1. 登录 Management Plane
2. Dashboard 显示所有 Company 实例及状态
3. 点击某个 Company → 进入该实例的 Agent Hub Web UI
4. 或从 Dashboard 执行快速操作（暂停/恢复/配置）
```

### 管理操作

```
Company Settings:
- 修改 Agent 团队配置（增减 agent）
- 更新 Claude Code token
- 查看 token 用量统计
- 暂停/恢复实例
- 删除实例
```

## 数据模型

### users 表
```sql
CREATE TABLE users (
    id          TEXT PRIMARY KEY,  -- UUID
    email       TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,      -- bcrypt hash
    name        TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### companies 表
```sql
CREATE TABLE companies (
    id          TEXT PRIMARY KEY,  -- UUID
    user_id     TEXT NOT NULL REFERENCES users(id),
    name        TEXT NOT NULL,     -- 显示名称
    slug        TEXT UNIQUE NOT NULL, -- URL 友好标识 (alice, bob)
    status      TEXT NOT NULL DEFAULT 'creating',
    -- status: creating | running | stopped | paused | error | deleted
    template    TEXT NOT NULL DEFAULT 'standard',
    -- template: solo | standard | full | custom
    config      TEXT,              -- JSON: agents.yaml 内容
    auth_type   TEXT,              -- oauth_token | api_key | bedrock | vertex
    auth_token  TEXT,              -- 加密存储的认证凭据
    port        INTEGER,           -- 分配的端口号
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### instance_events 表（审计日志）
```sql
CREATE TABLE instance_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  TEXT NOT NULL REFERENCES companies(id),
    event_type  TEXT NOT NULL,
    -- event_type: created | started | stopped | paused | resumed | error | deleted
    details     TEXT,              -- JSON: 事件详情
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## API 设计

### Auth API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | 注册新用户 |
| POST | `/api/auth/login` | 登录，返回 JWT |
| POST | `/api/auth/logout` | 注销 |
| GET | `/api/auth/me` | 获取当前用户信息 |

### Company API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/companies` | 列出用户的所有 Company |
| POST | `/api/companies` | 创建新 Company |
| GET | `/api/companies/:id` | 获取 Company 详情 |
| PATCH | `/api/companies/:id` | 更新 Company 配置 |
| DELETE | `/api/companies/:id` | 删除 Company |
| POST | `/api/companies/:id/start` | 启动实例 |
| POST | `/api/companies/:id/stop` | 停止实例 |
| POST | `/api/companies/:id/pause` | 暂停实例 |
| POST | `/api/companies/:id/resume` | 恢复实例 |
| GET | `/api/companies/:id/status` | 获取实例运行状态 |
| GET | `/api/companies/:id/logs` | 获取实例日志 |

### Auth Config API

| Method | Path | Description |
|--------|------|-------------|
| PUT | `/api/companies/:id/auth` | 更新 Claude Code 认证配置 |
| GET | `/api/companies/:id/auth/status` | 检查认证状态（token 有效性） |

## 页面设计

### 1. Landing Page (`/`)
- Hero section: "Your AI Development Team in the Cloud"
- 核心卖点：零运维、即时启动、可视化管理
- CTA: "Get Started Free"
- 简单的 pricing 预告（MVP 阶段免费）

### 2. Register Page (`/register`)
- Email + Password + Confirm Password
- "Already have an account? Log in"

### 3. Login Page (`/login`)
- Email + Password
- "Don't have an account? Register"

### 4. Dashboard (`/dashboard`)
```
┌──────────────────────────────────────────────────────┐
│  Agent Hub Cloud                    user@example.com │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Your Companies                    [+ Create New]    │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │  🟢 Alice's Startup                             │ │
│  │  Standard (5 agents) · Running · 3.2M tokens    │ │
│  │  [Open] [Settings] [Stop]                       │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │  ⚫ Side Project                                │ │
│  │  Solo (3 agents) · Stopped · 0 tokens           │ │
│  │  [Start] [Settings] [Delete]                    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  Empty State (no companies):                         │
│  "Create your first AI development team"             │
│  [+ Create Company]                                  │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### 5. Create Company (`/companies/new`)
3 步向导（复用 #316 Onboarding 设计模式）：

**Step 1: Company Info**
- Company name（显示名称）
- Slug（URL 标识，自动从名称生成，可编辑）

**Step 2: Team Configuration**
- 模板选择（Solo / Standard / Full / Custom）
- Agent 列表预览（可增减）

**Step 3: Claude Code Authentication**
- 选择认证方式：OAuth Token / API Key
- 粘贴凭据
- 即时验证（调用 Claude Code 检查 token 有效性）
- 帮助链接："How to get a token?"

**Step 4: Confirm & Create**
- 配置摘要
- [Create Company] 按钮
- 创建后显示进度：Preparing → Building → Starting → Ready

### 6. Company Settings (`/companies/:id/settings`)
- General: 名称、slug
- Team: Agent 配置（增减 agent）
- Authentication: 更新 token/key
- Token Usage: 用量统计图表
- Danger Zone: 暂停、删除

## 实例管理（Instance Manager）

### 创建实例

```python
async def create_instance(company: Company):
    """创建一个新的 Agent Hub 实例"""

    # 1. 分配端口
    port = allocate_port()  # 从可用端口池分配

    # 2. 生成 agents.yaml
    config = generate_agents_yaml(
        template=company.template,
        daemon_port=port
    )

    # 3. 创建工作目录
    instance_dir = f"/instances/{company.slug}"
    os.makedirs(instance_dir)
    write_yaml(f"{instance_dir}/agents.yaml", config)
    write_env(f"{instance_dir}/.env", {
        "CLAUDE_CODE_OAUTH_TOKEN": decrypt(company.auth_token),
        "WEB_PORT": port
    })

    # 4. 复制 Docker 相关文件
    copy_docker_files(instance_dir)

    # 5. 启动 Docker Compose
    subprocess.run([
        "docker", "compose",
        "--project-directory", instance_dir,
        "--profile", "agents",
        "up", "--build", "-d"
    ])

    # 6. 等待健康检查
    await wait_for_health(f"http://localhost:{port}/api/v1/health")

    # 7. 更新状态
    company.status = "running"
    company.port = port
```

### 生命周期操作

| 操作 | Docker 命令 | 状态变更 |
|------|------------|---------|
| Start | `docker compose up -d` | stopped → running |
| Stop | `docker compose down` | running → stopped |
| Pause | `docker compose pause` | running → paused |
| Resume | `docker compose unpause` | paused → running |
| Delete | `docker compose down -v && rm -rf dir` | * → deleted |

### 健康检查

每 60 秒轮询每个运行中实例的 `/api/v1/health`：
- 正常 → status = running
- 超时 → status = error，记录事件日志
- 连续 3 次失败 → 尝试自动重启

### 端口管理

MVP 阶段使用动态端口分配：
- 管理面占用固定端口（如 3000）
- 每个实例的 daemon 分配一个唯一端口（从 10000 开始递增）
- 端口信息记录在 companies 表中

## 技术栈决策

### 推荐：扩展现有架构

| 组件 | 技术 | 理由 |
|------|------|------|
| 后端 | Python + Starlette | 与 daemon 同栈，团队熟悉 |
| 前端 | React + TypeScript + Tailwind | 与现有 Web UI 同栈 |
| 数据库 | SQLite（MVP） | 足够简单，无需额外依赖 |
| 认证 | JWT + bcrypt | 自建，简单可控 |
| 部署 | Docker Compose | 管理面本身也容器化 |

**为什么不用 PostgreSQL（MVP）**：
- 管理面只存储用户和实例元数据，数据量小
- SQLite 无需额外服务，降低部署复杂度
- 单服务器 MVP 不需要远程数据库
- 未来扩展时可迁移到 PostgreSQL

**为什么不用 Next.js**：
- 引入新技术栈增加学习成本
- 团队已经有 Python + React 的经验
- MVP 不需要 SSR/SSG 等 Next.js 特性

## 目录结构

```
services/
└── management-plane/
    ├── Dockerfile
    ├── pyproject.toml
    ├── src/
    │   └── management/
    │       ├── __init__.py
    │       ├── app.py           # Starlette 主应用
    │       ├── auth.py          # JWT 认证
    │       ├── models.py        # 数据模型
    │       ├── db.py            # SQLite 数据库
    │       ├── routes/
    │       │   ├── auth.py      # /api/auth/*
    │       │   ├── companies.py # /api/companies/*
    │       │   └── instances.py # /api/companies/:id/start|stop|...
    │       └── instance_manager.py  # Docker Compose 操作
    ├── web/                     # React 前端
    │   ├── package.json
    │   ├── src/
    │   │   ├── pages/
    │   │   │   ├── Landing.tsx
    │   │   │   ├── Login.tsx
    │   │   │   ├── Register.tsx
    │   │   │   ├── Dashboard.tsx
    │   │   │   ├── CreateCompany.tsx
    │   │   │   └── CompanySettings.tsx
    │   │   ├── components/
    │   │   └── App.tsx
    │   └── vite.config.ts
    └── tests/
```

## 验收标准

### P0（Must Have）
1. 用户可以注册/登录
2. 登录后看到 Dashboard（Company 列表）
3. 可以创建 Company（选择团队模板 + 配置 Claude Code 认证）
4. 创建后自动部署 Agent Hub 实例
5. 可以打开实例的 Web UI
6. 可以停止/启动实例

### P1（Should Have）
7. 可以暂停/恢复实例
8. 可以更新 Claude Code 认证
9. 实例健康检查和自动重启
10. 基本的 token 用量展示

### P2（Nice to Have）
11. Landing Page
12. 实例日志查看
13. Company 删除（带确认）
14. 认证 token 有效性即时验证

## 与现有系统的关系

| 现有组件 | Management Plane 中的角色 |
|---------|------------------------|
| `agents.yaml` | 每个实例一份，由管理面生成 |
| `setup-agents.py` | 在实例容器内运行，生成 agent workspace |
| `docker-compose.yml` | 作为模板，每个实例基于此创建 |
| `docker/agent/` | Agent container image，所有实例共享 |
| Web UI (React) | 每个实例有自己的 Web UI，管理面是额外的入口 |
| daemon | 每个实例有独立的 daemon |

## 开放问题

1. **实例隔离**：MVP 阶段所有实例在同一台服务器上。需要 Docker 资源限制（CPU、内存、磁盘）防止一个实例影响其他实例。
2. **数据备份**：实例的 SQLite 数据如何备份？
3. **实例更新**：Agent Hub 代码更新时，如何升级已运行的实例？
4. **安全边界**：实例容器可以访问互联网吗？需要网络隔离吗？
5. **MVP 规模**：一台服务器能支撑多少个并发实例？（取决于 Claude Code token 限制）
