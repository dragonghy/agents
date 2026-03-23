# Agent Hub Cloud SaaS — 整体进展报告

> 日期: 2026-03-20
> 作者: product-lisa
> Ticket: #384

## 1. 整体设计

### 产品定位

Agent Hub Cloud 是一个 hosted SaaS 平台，将开源 Agent Hub（多 Agent 协作开发工具）转型为托管云服务。目标用户为 1-5 人小团队和独立开发者，注册即可获得完整的 AI Agent 工作环境，无需自己部署基础设施。

**类比**：Agent Hub 之于 AI Agent 开发 = Shopify 之于电商。

### 架构

采用**多实例隔离架构**：每个公司获得一个独立的 Docker Compose 实例。

```
用户注册 → 创建公司 → 独立 Docker Compose 实例
├── Company Alice → alice.agenthub.cloud (port 10000+)
├── Company Bob   → bob.agenthub.cloud   (port 10001+)
└── Company Carol → carol.agenthub.cloud (port 10002+)
```

### 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python (Starlette) + SQLite (MVP) |
| 前端 | React + TypeScript + Tailwind |
| 基础设施 | Docker Compose, Nginx 反向代理 |
| 认证 | JWT + bcrypt |
| 加密 | Fernet (数据库中的 auth tokens) |
| 计费 | Stripe 框架 + Token 用量追踪 |
| Agent 运行时 | Claude Code CLI in tmux sessions |

### 核心服务

1. **Management Plane** (`services/management-plane/`) — 用户管理、公司 CRUD、实例生命周期、计费
2. **Nginx Reverse Proxy** (`services/nginx-proxy/`) — 子域名路由、SSL、热重载
3. **Agent MCP Daemon** (`services/agents-mcp/`) — 任务管理、Agent 调度、消息系统
4. **Agent Runtime** (`docker/agent/`) — Claude Code CLI 容器化运行

---

## 2. 已实现的功能（M1-M7 全部完成）

### M1: Docker Agent v2 ✅ (ticket #318, dev-alex)

- 完整容器化 Agent 运行时
- Claude Code CLI 通过 `CLAUDE_CODE_OAUTH_TOKEN` 环境变量认证
- 单容器 + tmux 多会话方案
- 支持 OAuth Token、API Key、Bedrock、Vertex 认证方式

### M3: Management Plane ✅ (ticket #354, dev-emma)

**用户管理**：
- 注册（Email + Password）、JWT 登录/登出、用户 Profile

**公司/实例管理**：
- 创建公司 + 团队模板选择（Solo/Standard/Full/Custom）
- 公司所有权校验、软删除、自动生成 URL slug

**Web UI 页面**：
- Landing Page（带定价预览）
- Login / Register
- Dashboard（公司列表 + 状态 + Token 使用量）
- Create Company 向导（3-4 步）
- Company Settings（团队配置、认证配置、使用量）
- Token Usage & Billing 页面（带图表）

**数据库 Schema**：
```sql
users (id, email, password_hash, name, created_at)
companies (id, user_id, name, slug, status, template, auth_type, auth_token, config, port)
instance_events (id, company_id, event_type, details, created_at)
token_usage (id, company_id, date, input_tokens, output_tokens, model)
```

### M4: Instance Manager ✅ (ticket #358, dev-emma)

- 真实 Docker Compose 集成
- 动态端口分配 (10000-10999)
- 实例生命周期：creating → running → stopped/paused/error
- 团队模板预设：
  - **Solo**: product + dev + qa (3 agents)
  - **Standard**: product + 2 devs + qa + user (5 agents)
  - **Full**: admin + product + 3 devs + 2 QAs + user (9 agents)
- 自动生成 `docker-compose.yml` 和 `.env`
- 健康检查（60 秒轮询 `/api/v1/health`）
- 连续 3 次失败自动重启

### M5: Domain Routing & SSL ✅ (ticket #359, dev-alex)

- Nginx 反向代理 + 每实例 server block
- 子域名路由：`<slug>.<MGMT_DOMAIN>`
- 通配符 SSL 证书（开发自签名，生产 ACME）
- 实例创建/删除时热重载配置
- 支持自定义域名

### M6: Billing Integration ✅ (ticket #361, dev-emma)

- Token 使用量追踪（每日/每模型的 input + output tokens）
- Usage Summary API（日期过滤 + 分日 + 分模型统计）
- Stripe 三档定价框架：
  - **Free Beta**: 免费（预览期）
  - **Starter**: $29/月（1 个公司）
  - **Pro**: $99/月（5 个公司）
- 注册时自动创建 Stripe Customer

### M7: Production Readiness ✅ (ticket #363, dev-emma)

- **部署脚本** `scripts/deploy.sh`：依赖检查、环境验证、前端构建、Docker Compose 启动
- **备份脚本** `scripts/backup.sh`：SQLite 备份 + 实例配置归档
- **安全加固**：Fernet 加密、Rate Limiting (10 req/min)、JWT 环境变量注入、CORS 限制、Token 过期校验
- **健康检查端点** `GET /api/health`
- **Landing Page** + 响应式导航栏

---

## 3. 欠缺的部分

### 🔴 Critical（阻塞上线）

| 项 | 说明 |
|---|------|
| **基础设施部署** (#362) | 没有生产服务器。需要：服务器采购、Docker/Compose 安装、域名 DNS、SSL 证书 |
| **MOCK_MODE 关闭** | 开发环境 MOCK_MODE=true，生产需要真实 Docker daemon 连接 |
| **SQLite → PostgreSQL** | SQLite 不适合多租户生产环境 |

### 🟡 High（v1 上线需要）

| 项 | 说明 |
|---|------|
| **支付激活** | Stripe 框架已就绪，需配置 production keys 和实际收款 |
| **监控 & 可观测** | 无实例健康仪表板、错误告警、资源监控 |
| **数据备份** | 备份脚本已有，需自动化调度和灾备流程 |
| **实例资源限制** | CPU、内存、磁盘配额未设置 |

### 🟢 Medium（v1.1+）

| 项 | 说明 |
|---|------|
| **多用户团队协作** | 当前 1 用户 = 1 公司，未来需要团队邀请和 RBAC |
| **自定义 Agent 模板** | 目前只有预设模板 |
| **GitHub/GitLab 集成** | 无代码仓库集成 |
| **高级计费** | 按用量阶梯定价、折扣等 |
| **API 文档 & Webhook** | 无 REST API 文档和事件通知 |

---

## 4. 接下来的考虑

### 上线路径（推荐）

```
Step 1: 搭建 staging 服务器 (MOCK_MODE=true，验证认证流)
Step 2: 启用真实 Docker 实例 (MOCK_MODE=false，验证实例创建)
Step 3: PostgreSQL 迁移（持久化）
Step 4: Stripe production keys（开始收款）
Step 5: 监控和日志
Step 6: Closed Beta（邀请制测试）
Step 7: Public Launch
```

### 优先级排列

1. **#362 基础设施搭建**（最高优先级，所有其他工作的前置）
2. **真实实例部署测试**（关闭 MOCK_MODE，验证端到端流程）
3. **支付激活**（Stripe 配置 + 收款流程）
4. **数据安全**（PostgreSQL + 自动备份）
5. **监控**（实例健康 + 告警）

### 关键风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| OAuth token 1 年后过期 | 用户需手动更新 | 到期提醒 + 简化重生成 |
| 单实例资源消耗大 | 成本高 | 暂停/休眠机制 |
| Agent 容器安全 | 恶意代码执行 | 沙箱 + 资源限制 + 网络隔离 |

---

## 5. 关键文件索引

| 文件 | 用途 |
|------|------|
| `services/management-plane/src/management/app.py` | 主应用、路由、健康检查 |
| `services/management-plane/src/management/models.py` | 用户、公司、Token 数据操作 |
| `services/management-plane/src/management/instance_manager.py` | Docker Compose 实例生命周期 |
| `services/management-plane/src/management/billing.py` | Stripe 集成、定价模型 |
| `services/management-plane/src/management/security.py` | JWT、加密、Rate Limiting |
| `services/management-plane/src/management/nginx_config.py` | Nginx 配置生成 |
| `services/management-plane/web/src/pages/` | React UI 页面 |
| `docker-compose.cloud.yml` | 本地开发 stack |
| `services/management-plane/docker-compose.prod.yml` | 生产 stack |
| `docker/agent/Dockerfile` | Agent 运行时容器 |
| `projects/agent-hub/sas-product-brief.md` | 产品愿景和架构决策 |

---

## 6. 提交历史

| Commit | 日期 | 里程碑 | 内容 |
|--------|------|--------|------|
| `930bcc0` | 3/17 | M7 | 部署脚本、安全加固、计费修复 |
| `8edb020` | 3/16 | M6 | Token 使用量追踪 + Stripe 框架 |
| `6b6d35d` | 3/13 | M5 | Nginx 代理 + 子域名路由 + SSL |
| `b9fbc32` | 3/10 | M4 | Docker Compose 实例管理 |
| 较早 | 3/8 | M3 | 管理面（认证、UI、公司 CRUD） |
| 较早 | 3/2 | M1 | Docker Agent v2 + Claude Code CLI |

---

## 总结

Agent Hub Cloud 是一个**完整的 SaaS MVP**，7 个里程碑全部完成。平台架构合理（多实例隔离、职责分离、安全优先），核心功能齐全。**主要阻塞是基础设施部署（#362），不是功能缺口。** 有了生产服务器后，平台即可开始 Beta 测试和逐步上线。模块化设计支持未来扩展（团队协作、高级计费、代码仓库集成），无需架构重构。
