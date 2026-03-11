---
name: create-skill
description: 如何创建一个所有 Agent 共享的 Skill。包含文件结构、symlink、重启的完整步骤。
allowed-tools: Bash, Write, Edit, Read, Glob
---

# 创建共享 Skill 操作手册

## 文件结构

共享 Skill 放在 `templates/shared/skills/`。Agent 专属 Skill 放在 `templates/<name>/skills/`。
`setup-agents.py` 会自动将它们 symlink 到 `.claude/skills/`（运行时目录），无需手动创建 symlink。

```
templates/
├── shared/skills/<skill-name>/SKILL.md   ← 共享 skill 源文件
├── admin/skills/<skill-name>/SKILL.md    ← agent 专属 skill 源文件

agents/admin/.claude/skills/<skill-name>/ ← 自动生成的 symlink（gitignored）
```

## 步骤

### 1. 创建共享 Skill

```bash
mkdir -p templates/shared/skills/<skill-name>
```

在 `templates/shared/skills/<skill-name>/SKILL.md` 中编写 Skill 内容。

文件必须以 YAML frontmatter 开头：

```yaml
---
name: <skill-name>
description: 一句话描述，用户输入 /<skill-name> 时会看到这段描述。
allowed-tools: tool1, tool2, tool3
---
```

### 2. 创建 Agent 专属 Skill

```bash
mkdir -p templates/<agent>/skills/<skill-name>
```

在 `templates/<agent>/skills/<skill-name>/SKILL.md` 中编写 Skill 内容。

### 3. 重启 Agent

重启时 `setup-agents.py` 会自动创建 symlink：

```bash
./restart_all_agents.sh --workers   # 重启 product / dev / qa
./restart_all_agents.sh admin       # 如需 admin 也生效，单独重启
```

### 4. 验证

在目标 Agent 中输入 `/<skill-name>`，确认 Skill 可被识别和调用。

## 注意事项

- Skill 名称（目录名）即为调用命令，如目录名为 `leantime`，则用 `/leantime` 调用。
- 修改源文件后，symlink 自动生效，但仍需重启 Agent 才能加载变更。
- **不要手动在 `.claude/skills/` 中创建文件**，它是自动生成的。
