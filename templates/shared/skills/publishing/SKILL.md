---
name: publishing
description: 项目发布和部署指南。Web 应用部署到 Vercel，CLI 项目提供安装说明。所有测试项目代码提交到 test-projects 仓库。
allowed-tools: Bash, Read, Write, Glob, Grep
---

# 项目发布指南

## 1. test-projects 仓库

测试项目统一保存在 `$TEST_PROJECTS_REPO`（Git remote URL，在 `.env` 中配置）。

本地路径通过环境变量 `$WORKSPACE_DIR/test-projects` 获取。

### 仓库结构

```
test-projects/
├── README.md              # 项目索引（每次发布必须更新）
├── snake-game/
│   ├── README.md          # 项目文档
│   └── ...
├── portfolio-site/
│   ├── README.md
│   └── ...
```

### 项目 README 要求

每个项目的 `README.md` **必须**包含：

1. **项目名称和简介**（一句话描述）
2. **技术栈**
3. **本地运行方式**（完整的命令，从 clone 到启动）
4. **公开访问方式**：
   - Web 项目：Vercel 部署 URL
   - CLI 项目：`git clone` + 运行指令
5. **截图**（如果有 UI）

### 根 README 索引

根目录 `README.md` 维护所有项目的索引表。**每发布一个新项目必须更新**：

```markdown
| 项目 | 描述 | 类型 | 链接 |
|------|------|------|------|
| snake-game | 终端贪吃蛇游戏 | CLI | [README](./snake-game/) |
| portfolio | 个人作品集网站 | Web | [Live](https://xxx.vercel.app) |
```

## 2. 部署方式

### Web 应用 → Vercel

适用于：React, Next.js, Vue, 静态网站, 任何前端项目。

```bash
cd $WORKSPACE_DIR/test-projects/<project-name>

# 部署到 Vercel（首次会自动创建项目）
npx vercel --prod --yes --token $VERCEL_TOKEN
```

部署后将返回的 URL 写入项目 README 的"公开访问"部分。

**注意**：
- `$VERCEL_TOKEN` 已在 `.env` 中配置，Bash 中可直接使用
- `--yes` 跳过交互式确认
- 如需自定义配置（构建命令、输出目录等），在项目中创建 `vercel.json`

### CLI / 终端应用

无需云部署。在项目 README 中提供安装和运行说明：

```markdown
## 安装与运行

git clone $TEST_PROJECTS_REPO
cd test-projects/<project-name>
python3 main.py   # 或 npm install && node index.js
```

### Mobile 应用 → Expo

```bash
cd $WORKSPACE_DIR/test-projects/<project-name>
npx expo publish
```

在 README 中提供 Expo Go 扫码链接。

## 3. Git 工作流

### 提交项目代码

```bash
cd $WORKSPACE_DIR/test-projects

# 确保在 main 分支
git checkout main && git pull

# 添加项目文件
git add <project-name>/

# 提交
git commit -m "feat: add <project-name> - <简短描述>"

# 推送
git push origin main
```

如果多人可能同时操作，使用分支：

```bash
git checkout -b project/<project-name>
# ... 开发 ...
git push origin project/<project-name>
# 合并回 main
git checkout main && git merge project/<project-name> && git push origin main
```

### 完成 checklist

发布新项目前确认：
- [ ] 项目代码已 push 到 test-projects 的 main 分支
- [ ] 项目 README.md 包含完整文档和公开访问方式
- [ ] 根 README.md 索引已更新
- [ ] Web 项目已部署到 Vercel 且 URL 可访问
- [ ] CLI 项目的安装运行指令可正常执行

## 4. 两种项目模式

### Mode A: test-projects 子文件夹（默认）

Sophia 的测试项目默认使用此模式。在 test-projects 仓库中创建子文件夹开发。

### Mode B: 独立 repo

当 Human 指定一个已有的 repository 时使用。Dev agent 直接在该 repo 中开发，部署流程相同。
