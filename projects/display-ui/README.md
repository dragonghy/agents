# Display UI

Agent-Hub 的浏览器端管理面板。让 Human 通过 Web 界面监控所有 agent 状态、浏览消息和 ticket、执行操作、提交反馈。

## 产品目标

当前所有 agent 可见性被锁在 tmux 里。Human 必须 `tmux attach` 才能查看 agent 活动，手动切换窗口检查不同 agent，且无法方便地浏览消息和 ticket。

Display UI 提供一个浏览器端的统一仪表盘，让 Human：
1. **一眼掌控全局**：所有 agent 状态、工作负载、当前上下文
2. **浏览所有数据**：消息对话、ticket 列表与详情、agent 终端输出
3. **执行管理操作**：发消息、创建/更新 ticket、手动 dispatch agent
4. **快速提交反馈**：直接提交改进意见，自动创建 ticket 供 agent 处理

## 架构概要

**扩展现有 agents-mcp daemon**（端口 8765），而非创建新服务。

```
Browser (React SPA)
  ├── GET /           → 静态前端文件
  ├── /api/v1/*       → REST API（agent、消息、ticket、反馈）
  ├── /ws             → WebSocket（实时推送）
  └── /sse            → MCP SSE（agent 连接，不变）
         ↓
  agents-mcp daemon（单进程、单端口）
  ├── LeantimeClient  → Leantime JSON-RPC（ticket/comment）
  ├── AgentStore      → SQLite（消息/profile）
  └── tmux subprocess → agent 状态 & 终端输出
```

Daemon 已持有所有数据源，新增 REST/WebSocket 路由零额外基础设施。

## tmux 兼容性

Web UI 与 tmux **并行运行**（不替代）：
- 终端视图是**只读**的（通过 `tmux capture-pane` 捕获输出）
- Dispatch 使用与 daemon 相同的 `tmux send-keys` 机制
- Human 仍可 `tmux attach` 直接交互
- 无冲突：Web UI 读取 tmux 状态，不写入（除 dispatch 外）

## 技术栈

| 层 | 选择 |
|----|------|
| 后端 | Starlette 路由挂载到现有 daemon ASGI 应用 |
| 前端 | React 18 + TypeScript + Vite |
| 样式 | Tailwind CSS |
| 实时 | WebSocket |
| 测试 | Playwright |

## 功能清单

### P0（核心功能）

1. **Dashboard**：agent 状态卡片（idle/busy/offline）、工作负载、快速 dispatch
2. **Agent 详情**：profile、当前上下文、实时终端视图（tmux 输出，3 秒刷新）
3. **消息浏览**：对话列表、聊天式显示、发送新消息
4. **Ticket 浏览**：可过滤列表（状态、assignee、项目）、详情页（描述、评论、子任务）
5. **Ticket 操作**：创建、更新状态、添加评论、reassign
6. **反馈提交**：表单（标题、描述、目标 agent、优先级）→ 自动创建 Leantime ticket

### P1（增强体验）

7. **WebSocket 实时推送**：agent 状态变化、新消息、ticket 更新，无需轮询
8. **Playwright E2E 测试**：覆盖所有页面的自动化测试
9. **加载状态 & 错误处理**：骨架屏、错误提示、WebSocket 自动重连

### P2（锦上添花）

10. **暗色/亮色主题**
11. **终端 ANSI 颜色支持**
12. **键盘快捷键**

## REST API

**Agent**: `GET /api/v1/agents` | `GET /api/v1/agents/{id}` | `GET /api/v1/agents/{id}/terminal` | `POST /api/v1/agents/{id}/dispatch`

**消息**: `GET /api/v1/messages` | `GET /api/v1/messages/inbox/{id}` | `GET /api/v1/messages/conversation/{a}/{b}` | `POST /api/v1/messages`

**Ticket**: `GET /api/v1/tickets` | `GET /api/v1/tickets/{id}` | `POST /api/v1/tickets` | `PATCH /api/v1/tickets/{id}` | `GET /api/v1/tickets/{id}/comments` | `POST /api/v1/tickets/{id}/comments` | `POST /api/v1/tickets/{id}/reassign`

**反馈**: `POST /api/v1/feedback`

**系统**: `GET /api/v1/health` | `WS /ws`

## 前端页面

| 页面 | 路由 | 核心功能 |
|------|------|---------|
| Dashboard | `/` | Agent 状态卡片、工作负载数字、最近消息、Dispatch All 按钮 |
| Agents | `/agents` | Agent 列表 + 详情面板，含实时终端视图 |
| Messages | `/messages` | 对话线程列表（左） + 聊天视图（右） + 发送消息 |
| Tickets | `/tickets` | 可过滤表格 + 详情页（描述/评论/子任务） |
| Feedback | `/feedback` | 反馈提交表单 → 自动创建 ticket |

## 项目目录结构

```
services/agents-mcp/
├── src/agents_mcp/web/          # 后端：REST API + WebSocket
│   ├── api.py                   # REST 路由
│   ├── ws.py                    # WebSocket 处理
│   ├── events.py                # 事件总线
│   └── static/                  # 前端构建输出（Vite build 目标）
└── web/                         # 前端：React SPA 源码
    ├── package.json
    ├── vite.config.ts
    ├── src/
    │   ├── pages/
    │   ├── components/
    │   ├── api/
    │   ├── hooks/
    │   └── types/
    └── tests/                   # Playwright E2E 测试
```

## Product Milestones

### M1: Backend API + Frontend Shell
- REST 端点：agents、tickets（只读）、health
- React + Vite 项目搭建 + Tailwind
- Dashboard 页面（agent 状态卡片，轮询刷新）
- Daemon 静态文件服务
- **验收**：`http://localhost:8765/` 显示所有 agent 及状态；MCP `/sse` 不受影响

### M2: Data Views
- REST 端点：messages、ticket comments/subtasks、agent terminal
- Messages 页面（对话列表 + 聊天视图）
- Tickets 页面（可过滤列表 + 详情页）
- Agent 详情含实时终端视图
- **验收**：所有系统数据均可从 Web UI 浏览

### M3: Operations + WebSocket + Feedback
- REST 端点：发送消息、创建/更新 ticket、dispatch、feedback
- WebSocket 事件总线（实时推送）
- 交互式 UI：发消息、创建 ticket、dispatch 按钮
- Feedback 页面
- **验收**：Human 可完全通过浏览器管理 agent；实时更新无需轮询

### M4: Playwright E2E Tests
- 测试基础设施（隔离 daemon + Leantime 项目）
- 覆盖所有页面的 E2E 测试
- Headless 兼容（测试模式下 mock tmux）
- **验收**：所有测试在 headless Chromium 中通过

### M5: Polish + Production
- 加载状态、错误处理、WebSocket 自动重连
- 暗色/亮色模式、响应式设计
- 终端 ANSI 颜色支持
- **验收**：生产级 UX，所有 Playwright 测试通过
