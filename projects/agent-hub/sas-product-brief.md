# Agent Hub Cloud — 产品设计简报

> Status: 方向已确认，设计深化中
> Ticket: #320
> Author: product-kevin
> Date: 2026-03-16
> Updated: 2026-03-16 (Human 反馈 #339 已整合)

## Human 决策记录（#339）

以下决策已由 Human 确认：

| 问题 | 决策 |
|------|------|
| 方向 | 确认推进 SaaS 方向，与开源完善并行 |
| 品牌 | **Agent Hub Cloud**（不是 "One Person Company"，适用于 1-5 人小团队） |
| 架构 | **多实例方案**（每个公司 = 独立 Agent Hub 实例） |
| 认证 | 用户自带 Claude 订阅，通过 OAuth Token 注入（详见认证方案） |
| 计费 | MVP 阶段不做计费，只统计 token 用量 |
| 域名/SSL | 先做本地开发，部署和域名配置后续处理 |
| 优先级 | Docker Agent v2 → Agent Hub 改进 → SaaS 设计 → SaaS 实现 |
| 技术栈 | 由产品设计决定 |

## 产品愿景

将 Agent Hub 从开源自部署工具转型为 hosted SaaS 平台。用户注册即获得一个完整的多 Agent 工作环境，无需自己部署基础设施。

**类比**：Agent Hub 之于 AI Agent 开发 = Shopify 之于电商。用户不需要懂基础设施，只需要定义 Agent 团队和项目目标。

## 用户场景

### 目标用户
- **独立开发者 / Solo Founder**：一个人希望用 AI Agent 团队完成产品开发
- **小型团队（2-5 人）**：想要 AI 辅助开发但不想维护基础设施
- **企业探索者**：想试用多 Agent 协作开发模式的企业技术评估人员

### 核心用户旅程
```
注册 → 创建"公司" → 选择 Agent 团队模板 → 提供 Claude 认证 → Agent 自动启动
→ Web UI 监控进度 → 创建项目/任务 → Agent 自动开发 → 查看代码产出
```

### 关键价值主张
1. **零运维**：不需要管 tmux、daemon、Docker — 一切由平台管理
2. **即时启动**：注册后 5 分钟内 Agent 团队就能开始工作
3. **可视化管理**：通过 Web UI 观察 Agent 活动、审阅代码、管理任务

## 技术架构：多实例（已确认）

每个公司一个独立的 Agent Hub 实例（容器组）。

```
公司 Alice → alice.agenthub.cloud → Container Group A（daemon + agents + SQLite）
公司 Bob   → bob.agenthub.cloud   → Container Group B（daemon + agents + SQLite）
```

**优点**：
- 数据天然隔离，安全风险低
- 复用现有 Docker Compose 架构（#315 已完成）
- 每个实例可独立扩缩容

**远期扩展**：支持多用户共享一个公司实例（v2+）

## Claude Code 认证方案（调研完成）

### 调研结果

Claude Code 支持以下容器内认证方式：

| 方式 | 环境变量 | 适用场景 | 限制 |
|------|---------|---------|------|
| **OAuth Token** | `CLAUDE_CODE_OAUTH_TOKEN` | Pro/Max 订阅用户 | 需要先在本地运行 `claude setup-token` |
| **API Key** | `ANTHROPIC_API_KEY` | Console 用户（API 计费） | 按 API 用量计费，无订阅优惠 |
| **Cloud Provider** | `AWS_*` / `GOOGLE_*` | Bedrock/Vertex/Foundry 用户 | 需要云平台账号 |
| **apiKeyHelper** | `apiKeyHelper` 配置 | 动态获取密钥 | 需要自定义脚本 |

### MVP 推荐：OAuth Token 注入

**用户流程**：
1. 用户购买 Claude Pro/Max 订阅
2. 在本地终端运行 `claude setup-token`
3. 浏览器自动打开，完成 OAuth 登录
4. 获得一个有效期 1 年的 `sk-*` 长期 token
5. 在 Agent Hub Cloud 设置页面粘贴该 token
6. 平台将 token 作为 `CLAUDE_CODE_OAUTH_TOKEN` 注入用户的容器实例

**优势**：
- 用户自带订阅，平台不承担 AI 成本
- Token 有效期 1 年，不需要频繁重新认证
- 利用 Claude Pro/Max 的订阅优惠价格（比纯 API 便宜）
- 安全：token 存储在平台的加密存储中

**备选方案（同时支持）**：
- 用户提供 `ANTHROPIC_API_KEY`（API 计费用户）
- 用户提供 Bedrock/Vertex 凭据（企业用户）

### 技术注意事项

- OAuth 登录需要浏览器 + localhost 回调端口。在容器中直接 `claude login` 会失败（端口不可达）
- `CLAUDE_CODE_OAUTH_TOKEN` 设为环境变量后，Claude Code 静默使用它，跳过交互式登录
- Token 不应写入 Dockerfile 或 image layer，应通过 Docker secrets / env var 注入

参考：
- [Claude Code Authentication Docs](https://code.claude.com/docs/en/authentication)
- [Docker Sandboxes Guide](https://docs.docker.com/ai/sandboxes/agents/claude-code/)
- [Headless Auth Issue #7100](https://github.com/anthropics/claude-code/issues/7100)

## MVP 范围定义

### MVP 包含（Phase 1 — 本地开发阶段）
- [ ] 用户注册/登录（Email + Password）
- [ ] 创建"公司"（一个 Agent Hub 实例）
- [ ] Web Onboarding（复用 #316）
- [ ] Claude 认证配置（OAuth Token / API Key 输入界面）
- [ ] 实例自动部署（基于 Docker Compose）
- [ ] Token 用量统计（复用现有 Token Usage 功能）
- [ ] 实例生命周期管理（创建、暂停、恢复）

### Phase 2 — 上线阶段
- [ ] 二级域名访问（alice.agenthub.cloud）
- [ ] 域名路由 + SSL（通配符证书）
- [ ] 基础计费（按使用量或固定月费）

### 暂不包含（v2+）
- 团队协作（多用户共享一个实例）
- 自定义 Agent 模板
- GitHub/GitLab 集成
- CI/CD 集成
- 高级计费（按 token 用量阶梯）
- 企业 SSO

## 关键依赖与前置条件

### 技术前置（按优先级）
1. **#318 Docker Agent v2**（最高优先级）：Agent 必须在容器内运行
   - Agent base image: Claude Code CLI + tmux + git + Node.js + Python
   - 认证：通过 `CLAUDE_CODE_OAUTH_TOKEN` 环境变量注入
   - Workspace：Volume mount 或容器内完整工作空间
   - Docker Compose 集成：`docker compose --profile agents up`
2. **Agent Hub 平台改进**：现有 Web UI 和 daemon 的功能完善
3. **管理面开发**：注册/登录/实例管理（新组件）

### 风险
| 风险 | 影响 | 缓解 |
|------|------|------|
| OAuth token 1 年后过期 | 用户需要手动更新 | 到期前邮件提醒 + 简化重新生成流程 |
| 单实例资源消耗大 | 成本高 | 实例可暂停/休眠 |
| Agent 容器安全 | 恶意代码执行 | 沙箱化 + 资源限制 + 网络隔离 |
| Claude Code 版本更新 | 可能破坏认证 | 容器内动态安装最新版 |

## 技术栈设计（待定）

管理面（注册/登录/实例管理/认证配置）的技术栈选择：

### 推荐方案：扩展现有架构

复用 Agent Hub 的现有技术栈，降低学习成本和维护复杂度：

- **后端**：Python + Starlette（与 agents-mcp daemon 一致）
- **前端**：React + TypeScript + Tailwind（与现有 Web UI 一致）
- **数据库**：SQLite → PostgreSQL（多实例管理需要关系型 DB）
- **认证**：自建 Email + Password（JWT token）
- **部署**：Docker Compose（管理面本身也容器化）

### 备选方案：独立管理面

如果管理面需要更高可靠性和可扩展性：

- **后端**：Next.js API Routes（前后端一体）
- **数据库**：PostgreSQL（Supabase 或自建）
- **认证**：Supabase Auth 或 Auth.js
- **部署**：Vercel（管理面）+ 自有服务器（实例管理）

## 里程碑规划

| 阶段 | 内容 | 前置 | 估算 |
|------|------|------|------|
| **M1** | Docker Agent v2 — Agent 在容器内运行 | — | 1-2 周 |
| **M2** | Agent Hub 改进 — 平台功能完善 | M1 | 持续 |
| **M3** | 管理面 — 注册/登录 + 实例 CRUD + 认证配置 | M1 | 2-3 周 |
| **M4** | 自动部署 — 实例创建/销毁/暂停 | M1, M3 | 2-3 周 |
| **M5** | 域名路由 — 二级域名 + SSL | M4 | 1 周 |
| **M6** | 计费集成 — Stripe + 使用量追踪 | M3 | 1-2 周 |
| **M7** | 上线 — Beta 测试 + 公开发布 | All | 2 周 |

**当前焦点**：M3 管理面设计（详见 `management-plane-prd.md`）

**已完成**：M1 Docker Agent v2 ✅（ticket #318，dev-alex 实现，单容器 tmux 方案）
