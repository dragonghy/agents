# Onboarding 流程测试指南

## 环境准备

### 方式一：Docker（推荐，2 分钟）

```bash
# 1. 进入项目目录
cd /Users/huayang/code/agents

# 2. 清除旧数据（确保看到 Onboarding 首次体验）
docker compose down -v

# 3. 构建并启动
docker compose up --build -d

# 4. 打开浏览器
open http://localhost:3000
```

> 如果 3000 端口被占用：`WEB_PORT=3001 docker compose up --build -d`

### 方式二：本地启动 daemon

```bash
# 1. 进入项目目录
cd /Users/huayang/code/agents

# 2. 如果已有 agents.yaml 且想测试首次体验，先备份并删除
cp agents.yaml agents.yaml.bak
# 创建一个空的 agents.yaml（不含 agents 配置）触发 onboarding
echo "workspace_dir: ~/workspace" > agents.yaml

# 3. 构建前端
cd services/agents-mcp/web && npm install && npm run build && cd ../../..

# 4. 启动 daemon
uv run --directory services/agents-mcp agents-mcp --daemon --port 8765

# 5. 打开浏览器
open http://localhost:8765
```

### 恢复原始配置

测试完成后恢复：
```bash
# Docker 方式
docker compose down -v

# 本地方式
cp agents.yaml.bak agents.yaml
```

---

## 测试用例

### TC-1: 首次访问自动重定向到 Onboarding

**步骤：**
1. 确保 agents.yaml 为空或不存在（Docker: `docker compose down -v` 后重启）
2. 打开浏览器访问 `http://localhost:3000`

**预期结果：**
- 自动跳转到 Onboarding 页面
- 看到 "Welcome to Agent-Hub" 标题
- 顶部有 3 步进度条（Step 1 高亮）
- 页面底部有 "Next" 按钮

---

### TC-2: Step 1 — Workspace 路径设置

**步骤：**
1. 在 Onboarding 页面，看到 Workspace 路径输入框
2. 默认值应为 `~/workspace`
3. 修改为自定义路径（如 `~/my-projects`）
4. 点击 "Next"

**预期结果：**
- 输入框可编辑
- 点击 Next 后进入 Step 2
- 进度条 Step 2 高亮

---

### TC-3: Step 2 — 团队模板选择

**步骤：**
1. 在 Step 2，看到团队模板选项
2. 分别点击每个模板查看 Agent 列表

**预期模板：**

| 模板 | Agent 数量 | 包含角色 |
|------|-----------|---------|
| Solo | 3 | admin, dev, qa |
| Standard | 5 | admin, product, dev, dev, qa |
| Full | 7+ | admin, product, dev, dev, qa, qa, user |

**验证点：**
- 每个模板可点击选中
- 选中后显示 Agent 列表（名称 + 角色 + 图标）
- Agent 名称格式正确（如 `dev-alex`, `qa-lucy`）
- 点击不同模板可以切换

---

### TC-4: Step 2 — 自定义 Agent

**步骤：**
1. 选择任意模板后，尝试添加新 Agent
2. 尝试删除已有 Agent
3. 尝试输入无效名称

**验证点：**
- 可以添加新 Agent（选择角色 + 输入名称）
- 可以删除非必需的 Agent
- 无效名称（如大写字母、特殊字符）显示错误提示
- 至少需要 1 个 Agent 才能继续

---

### TC-5: Step 2 — 名称验证

**步骤：**
1. 在自定义 Agent 名称时，分别尝试：
   - 合法名称：`dev-alex`, `qa-1`, `my-agent` → 应通过
   - 大写字母：`Dev-Alex`, `MyAgent` → 应报错
   - 特殊字符：`dev@alex`, `qa!1` → 应报错
   - 空名称 → Next 按钮应禁用
   - 重复名称 → 应报错

**预期结果：**
- 错误信息："Lowercase letters, numbers, hyphens only" 或类似提示
- Next 按钮在有验证错误时禁用

---

### TC-6: Step 3 — 确认并创建

**步骤：**
1. 完成 Step 1 和 Step 2 后，进入 Step 3
2. 查看配置摘要

**预期结果：**
- 显示 Workspace 路径
- 显示选中的 Agent 团队列表（名称 + 角色）
- 显示 Agent 总数
- 有 "What happens next?" 说明
- 有 "Back" 和 "Complete Setup" 按钮

---

### TC-7: Setup 执行成功

**步骤：**
1. 在 Step 3 点击 "Complete Setup"
2. 等待执行完成

**预期结果：**
- 显示 "Setup Complete!" 成功页面
- 有绿色勾选图标
- 显示 next steps（如 "Go to Dashboard"）
- 后端已生成 `agents.yaml` 文件（Docker 内在 `/config/agents.yaml`）

**验证 agents.yaml 生成：**
```bash
# Docker 方式
docker exec agents-daemon-1 cat /config/agents.yaml

# 本地方式
cat agents.yaml
```

应包含：
- `workspace_dir` 设置
- `agents:` 部分包含你选择的所有 Agent
- 每个 Agent 有 `template`, `role`, `description`, `dispatchable` 字段

---

### TC-8: Setup 完成后跳转 Dashboard

**步骤：**
1. 在成功页面点击 "Go to Dashboard"

**预期结果：**
- 跳转到 Dashboard 页面
- 左侧导航栏显示完整菜单（Dashboard, Agents, Tokens, ...）
- Dashboard 显示刚创建的 Agent 卡片
- 每个 Agent 显示名称、角色、状态

---

### TC-9: 再次访问不再显示 Onboarding

**步骤：**
1. Setup 完成后，刷新浏览器
2. 或关闭浏览器后重新打开 `http://localhost:3000`

**预期结果：**
- 直接进入 Dashboard，不再显示 Onboarding
- OnboardingGuard 检测到 agents.yaml 已配置，跳过 Onboarding

---

### TC-10: API 直接测试

不通过 UI，直接用 curl 测试后端 API：

```bash
# 替换为你的端口（Docker: 3000, 本地: 8765）
PORT=3000

# 1. 检查 Onboarding 状态
curl -s http://localhost:$PORT/api/v1/onboarding/status | python3 -m json.tool
# 预期：{"completed": false}（首次）或 {"completed": true}（已配置）

# 2. 获取团队模板
curl -s http://localhost:$PORT/api/v1/onboarding/templates | python3 -m json.tool
# 预期：返回 templates 数组（solo/standard/full）+ roles 对象 + available_roles 数组

# 3. 提交 Setup（创建 agents.yaml）
curl -s -X POST http://localhost:$PORT/api/v1/onboarding/setup \
  -H 'Content-Type: application/json' \
  -d '{
    "workspace_dir": "~/workspace",
    "agents": [
      {"name": "admin", "role": "admin"},
      {"name": "dev-alex", "role": "dev", "template": "dev"},
      {"name": "qa-lucy", "role": "qa", "template": "qa"}
    ]
  }' | python3 -m json.tool
# 预期：{"status": "ok", "config_path": "...", "agents_count": 3, "next_steps": [...]}

# 4. 验证名称校验（应返回 400）
curl -s -X POST http://localhost:$PORT/api/v1/onboarding/setup \
  -H 'Content-Type: application/json' \
  -d '{
    "workspace_dir": "~/workspace",
    "agents": [
      {"name": "BadName", "role": "dev"}
    ]
  }' | python3 -m json.tool
# 预期：{"error": "Invalid agent name: 'BadName'. Use lowercase letters, numbers, and hyphens."}

# 5. 验证空 agents 校验（应返回 400）
curl -s -X POST http://localhost:$PORT/api/v1/onboarding/setup \
  -H 'Content-Type: application/json' \
  -d '{
    "workspace_dir": "~/workspace",
    "agents": []
  }' | python3 -m json.tool
# 预期：{"error": "At least one agent must be configured"}

# 6. 再次检查状态（应为 completed）
curl -s http://localhost:$PORT/api/v1/onboarding/status | python3 -m json.tool
# 预期：{"completed": true}
```

---

### TC-11: Docker Agent Mode（完整系统）

需要 Claude Code 认证 token 才能测试 agent 实际运行。

**步骤：**
```bash
# 1. 配置认证
echo 'CLAUDE_CODE_OAUTH_TOKEN=你的token' >> .env

# 2. 启动完整系统
docker compose --profile agents up --build -d

# 3. 查看 agent 状态
docker exec -it agents-agents-1 tmux attach -t agents
# Ctrl-b n 切换窗口查看各 agent

# 4. 在 Web UI 创建测试任务
curl -s -X POST http://localhost:3000/api/v1/tickets/create \
  -H 'Content-Type: application/json' \
  -d '{"headline": "Test task", "description": "Say hello", "assignee": "dev-alex"}'
```

**预期结果：**
- agents 容器正常启动
- tmux 中显示各 agent 窗口
- 30 秒内 dev-alex 收到任务并开始执行

---

## 已知限制

1. **Tailwind Dark Mode**：Onboarding 页面有 `dark:` 样式，但使用 Tailwind `class` 策略，需要 HTML root 有 `dark` class 才生效。浏览器的 `prefers-color-scheme: dark` 不会自动触发。
2. **POST /setup 可覆写**：已有 agents.yaml 时再次调用 setup 会覆盖配置，无备份提示。
3. **TSC 类型检查**：如果从源码构建前端，确保 `Onboarding.tsx` 有 `import { type JSX } from 'react'`（已修复）。
