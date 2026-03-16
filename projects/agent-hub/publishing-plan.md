# Agent-Hub 开源发布执行计划

## 背景

基于 `publishing-research.md` 的研究结论，Human 已批准开源发布方案。本文档是具体执行计划。

**关键安全原则（来自 Human）**：清理凭证时，必须**先把凭证安全保存到本地 .env 文件**，确认系统能正常运行后，**再**从代码库和 Git 历史中清理。绝不能因清理导致本地系统跑不起来。

## 凭证审计结果

Git 历史中暴露的凭证（需要轮换）：

| # | 类型 | 文件 | 需轮换 |
|---|------|------|--------|
| 1 | Leantime API Key (`lt_...`) | `agents.yaml` | 是 |
| 2 | Leantime API Key（同上，历史拷贝） | `auto_dispatch.sh`（已删除但在 Git 历史中） | 是 |
| 3 | MySQL Root 密码 | `docker-compose.yml` 默认值 | 是 |
| 4 | MySQL User 密码 | `docker-compose.yml` 默认值 | 是 |
| 5 | Leantime Session Secret | `docker-compose.yml` 默认值 | 是 |
| 6 | 个人邮箱 (PII) | `agents.yaml` | 需清理 |

未发现：Anthropic API key、AWS 凭证、GitHub token、SSH 私钥。

## Milestone 1：凭证外部化（安全第一）

**目标**：将所有硬编码凭证迁移到 .env 文件，代码改为读取环境变量。本地系统必须继续正常工作。

### 执行顺序（严格按此顺序）

#### Step 1: 创建根目录 .env 文件（保存当前凭证）

在仓库根目录创建 `.env`，写入当前所有凭证：

```bash
# Leantime
LEANTIME_URL=http://localhost:9090
LEANTIME_API_KEY=<当前 agents.yaml 中的值>
LEANTIME_USER_EMAIL=<当前邮箱>

# MySQL (Leantime)
MYSQL_ROOT_PASSWORD=<当前 docker-compose.yml 中的默认值>
MYSQL_PASSWORD=<当前 docker-compose.yml 中的默认值>
LEAN_SESSION_PASSWORD=<当前 docker-compose.yml 中的默认值>
```

确认 `.env` 在 `.gitignore` 中（根目录级别）。

#### Step 2: 创建 .env.example（占位符模板）

```bash
# Leantime
LEANTIME_URL=http://localhost:9090
LEANTIME_API_KEY=your_leantime_api_key_here
LEANTIME_USER_EMAIL=your_email@example.com

# MySQL (Leantime)
MYSQL_ROOT_PASSWORD=change_me_to_strong_password
MYSQL_PASSWORD=change_me_to_strong_password
LEAN_SESSION_PASSWORD=change_me_to_random_string
```

#### Step 3: 修改 agents.yaml

```yaml
leantime:
  url: ${LEANTIME_URL:-http://localhost:9090}
  api_key: ${LEANTIME_API_KEY}
  user_email: ${LEANTIME_USER_EMAIL}
```

**注意**：需要同步修改 `setup-agents.py`（或 `agent-config.py` 等读取 agents.yaml 的代码），确保它能解析环境变量引用。

#### Step 4: 修改 docker-compose.yml

移除所有默认密码 fallback：

```yaml
# 之前: ${MYSQL_ROOT_PASSWORD:-<old_default_password>}
# 之后: ${MYSQL_ROOT_PASSWORD}
```

同时更新 `services/leantime/docker-compose.yml` 引用根目录 .env 或自身的 .env。

#### Step 5: 处理绝对路径

`agents.yaml` 中的绝对路径（如外部项目目录）：
- 如果 vm-mcp 是可选依赖，改为条件加载或环境变量
- 如果是必要依赖，改为相对路径或 `${HOME}` 变量

#### Step 6: 验证

- 重启 Leantime Docker 容器，确认连接正常
- 重启 agents-mcp daemon，确认 MCP 连接正常
- 手动 dispatch 一个 agent，确认端到端工作

### 验收标准

1. 根目录 `.env` 存在，包含所有当前凭证，且在 `.gitignore` 中
2. `.env.example` 存在，只有占位符值
3. `agents.yaml` 中无明文凭证（API key、邮箱）
4. `docker-compose.yml` 中无默认密码 fallback
5. Leantime + daemon + agent dispatch 全链路正常工作
6. `git diff` 中不包含任何真实凭证值

## Milestone 2：文档与 License

**目标**：添加开源发布所需的全部文档。

### 需要创建的文件

| 文件 | 内容 |
|------|------|
| `LICENSE` | Apache 2.0 全文 |
| `README.md`（重写） | 英文为主，项目介绍 + 架构概览 + 快速上手 + 截图/GIF |
| `CONTRIBUTING.md` | 贡献指南、PR 流程、代码规范 |
| `docs/getting-started.md` | 详细安装配置指南（前置条件、.env 配置、启动步骤） |
| `docs/architecture.md` | 系统架构文档（daemon、MCP、Leantime 集成、agent 模板） |

### README 结构

1. **Hero Section**：一句话介绍 + 关键特性列表
2. **Architecture Diagram**：ASCII 或 Mermaid 图
3. **Quick Start**：5 步启动（clone → .env → docker → daemon → agent）
4. **Features**：角色分工、Milestone 驱动、自动 dispatch、Web UI
5. **Documentation Links**：指向 docs/ 目录
6. **License**

### Leantime 插件 License

`services/leantime/plugins/` 下的插件需单独标注 AGPL-3.0（因为运行在 Leantime AGPL 进程内）。

### 验收标准

1. `LICENSE` 文件存在（Apache 2.0）
2. `README.md` 包含项目介绍、架构、快速上手指南
3. `CONTRIBUTING.md` 存在
4. `docs/getting-started.md` 提供完整的从零开始安装指南
5. `docs/architecture.md` 解释系统架构
6. Leantime 插件目录有 AGPL-3.0 说明

## Milestone 3：Git 历史清理与发布

**目标**：清理 Git 历史中的凭证，优化仓库大小，准备公开。

### 执行步骤

1. **凭证轮换**（在清理前完成）
   - 在 Leantime 后台生成新 API key
   - 更新本地 `.env` 中的新 key
   - 更新 MySQL 密码
   - 验证系统正常工作

2. **Git 历史清理**
   - 使用 `git-filter-repo` 移除所有历史中的凭证
   - 或者：创建一个新的 clean 仓库（squash 历史）
   - 两种方案由 Dev 评估后决定

3. **.gitignore 完善**
   - `.env`（根目录和各子目录）
   - `.agents-mcp.db*`（运行时数据库）
   - `.venv/`
   - `__pycache__/`
   - 其他运行时产物

4. **仓库大小优化**
   - 目标：< 10 MB
   - 移除不必要的大文件

5. **最终安全扫描**
   - 全量搜索：API key、password、secret、token、email 模式
   - 确认零暴露

6. **发布**
   - GitHub 仓库设为 Public
   - 可选：PyPI 发布 `agents-mcp`

### 验收标准

1. `git log -p --all` 中搜索不到任何真实凭证
2. 旧凭证已轮换，新凭证仅在本地 .env 中
3. 仓库大小 < 10 MB
4. `.gitignore` 覆盖所有运行时产物
5. 最终安全扫描零发现
6. 仓库可被 Public 访问（或准备好切换）

## 执行计划

- M1 → M2 → M3 顺序执行（有依赖关系）
- M1 最关键：安全 + 不能破坏本地环境
- M2 可以部分并行（文档编写不依赖 M1 完成）
- M3 必须在 M1 完成后进行（需要先外部化凭证，才能清理历史）
