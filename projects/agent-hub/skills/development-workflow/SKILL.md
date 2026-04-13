---
name: development-workflow
description: Agent-Hub 开发流程。使用 git worktree 安全开发，避免影响运行中的 agent。
---

# Agent-Hub 开发流程

## 核心规则

**所有代码变更必须在 git worktree 中进行，禁止直接修改 main 分支的工作目录。**

原因：所有 active agent 都运行在 main 分支的工作目录中（`$AGENTS_ROOT/`）。如果直接在这里修改代码，会导致：
- 正在运行的 agent 读到不一致的文件
- MCP daemon 可能崩溃
- Agent 的 skill、prompt、配置被意外覆盖

## 开发流程

### Step 1: 创建 Worktree

在 repo 根目录的**父级目录**创建 worktree，避免嵌套在 repo 内部：

```bash
cd $AGENTS_ROOT
git worktree add ../agents-dev-<feature> -b feature/<feature-name>
```

示例：
```bash
git worktree add ../agents-dev-mcp-refactor -b feature/mcp-refactor
```

这会在 `$AGENTS_ROOT-dev-mcp-refactor/` 创建一个独立的工作目录，切换到 `feature/mcp-refactor` 分支。

### Step 2: 在 Worktree 中开发

```bash
cd $AGENTS_ROOT-dev-<feature>
# 正常开发、编辑代码、运行测试
```

Worktree 中拥有完整的 repo 副本，可以自由修改任何文件。

### Step 3: 在隔离环境中测试

使用 `system-testing` skill 的隔离环境验证变更：

```bash
cd $AGENTS_ROOT-dev-<feature>

# 创建隔离测试环境（使用 worktree 中的代码）
python3 tests/e2e_env.py up --name test-<feature> --preset minimal

# 运行测试...

# 销毁测试环境
python3 tests/e2e_env.py down --name test-<feature>
```

详细测试流程参考 `/system-testing` skill。

### Step 4: 立即提交并合并（强制规范）

**验收通过后必须立即 commit/merge，不允许改完代码不 commit 就结束任务。**

```bash
cd $AGENTS_ROOT-dev-<feature>

# 提交变更（必须在交付给 QA 之前完成）
git add <files>
git commit -m "feat: <description>"

# 立即合并回 main（不要拖延）
cd $AGENTS_ROOT
git merge feature/<feature-name>

# 或通过 PR（适合需要 review 的大型变更）
git push origin feature/<feature-name>
# 然后在 GitHub 创建 PR 并尽快合并
```

**关键规则**：
- 主分支开发：验收后立即 `git commit`
- Worktree 开发：验收后立即 `commit` + `merge` 回 main
- ticket 备注中必须包含 commit hash
- 未 commit 的代码 = 未交付，QA 不应接受没有 commit hash 的交付

### Step 5: 更新生产环境

在**生产目录**（`$AGENTS_ROOT/`）拉取最新代码并安全重启：

```bash
cd $AGENTS_ROOT

# 拉取最新 main
git pull origin main

# 安全重启（参考 system-testing skill Part B）
# 根据变更范围选择重启方式：
./restart_all_agents.sh --workers     # 只改了 prompt/skill
./restart_all_agents.sh --daemon && ./restart_all_agents.sh --workers  # 改了 MCP server
./restart_all_agents.sh              # 改了 agents.yaml 结构
```

重启后 v2 daemon 的 auto-dispatch 循环会自动为在途 ticket 拉起新的 session，无需手动 dispatch。

### Step 6: 清理 Worktree

```bash
cd $AGENTS_ROOT
git worktree remove ../agents-dev-<feature>
git branch -d feature/<feature-name>  # 可选：删除已合并的分支
```

## 开发中遇到平台问题（自主 Triage）

开发 agent-hub 时，你可能会发现平台本身的 bug、缺失功能、或可以优化的地方。**你有能力和权限自主判断如何处理，不需要事事上报。**

### 判断标准

| 情况 | 处理方式 |
|------|---------|
| 顺手能修的小问题（文档错误、脚本 bug、配置遗漏） | 直接在 worktree 中修复，作为当前工作的一部分提交 |
| 你能修但需要单独跟踪的改进 | 自己创建 ticket，分配给自己或合适的 agent |
| 发现属于别人职责范围的问题 | 创建 ticket 分配给对应 agent（dev 的问题给 dev，产品问题给 product） |
| 涉及全局架构变更或你拿不准的决策 | 发消息给 admin，说明问题和你的建议，让 admin 评估 |

### 创建 ticket 的原则

- **能自己判断的就自己判断**：你了解系统，知道问题该谁修
- **ticket 描述要清楚**：问题是什么、影响什么、建议怎么修
- **优先级要合理**：阻塞当前工作的标 high，改进建议标 low/medium

### 什么时候找 Admin

只有以下情况需要发消息给 admin：
- 涉及 agent 配置、system prompt、skill 结构等**全局变更**
- 需要**重启 agent 或 daemon** 才能生效的修复
- 你不确定这个改动是否安全，需要有人 review

## 禁止事项

| 禁止 | 原因 |
|------|------|
| 在 `$AGENTS_ROOT/` 直接编辑代码 | 影响运行中的 agent |
| 在 worktree 中启动生产 daemon | 端口冲突 |
| 未测试就 merge 到 main | 可能导致生产环境崩溃 |
| Merge 后不重启 agent | Agent 仍在使用旧代码 |

## 多人并行开发

每个 dev agent 可以有自己的 worktree：

```bash
# dev-alex 的 worktree
git worktree add ../agents-dev-alex-task123 -b feature/task123

# dev-emma 的 worktree
git worktree add ../agents-dev-emma-task456 -b feature/task456
```

注意：
- 不同 worktree 使用不同的分支名，避免冲突
- 合并顺序：先到先合，后到的需要 rebase
- 隔离测试环境使用不同的 `--name`，避免端口冲突

## 快速参考

```bash
# 创建 worktree
git worktree add ../agents-dev-<feature> -b feature/<name>

# 开发完成后合并
cd ../agents-dev-<feature>
git add . && git commit -m "feat: ..."
cd $AGENTS_ROOT
git merge feature/<name>
git pull  # 如果在生产目录

# 安全重启
./restart_all_agents.sh --workers

# 清理
git worktree remove ../agents-dev-<feature>
```
