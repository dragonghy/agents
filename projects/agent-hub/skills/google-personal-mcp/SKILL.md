---
name: google-personal-mcp
description: 配置和使用 Google Workspace 个人 MCP（Gmail / Calendar / Drive）。仅供 personal agent 使用，不要挂在工作 agent 上。
---

# Google Personal MCP Setup Guide

## 概述

`google_personal` MCP 给未来的 **personal agent** 提供 Gmail / Calendar / Drive 接入。基于社区项目 [`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp)（PyPI 包名 `workspace-mcp`，FastMCP backend）。

**关键约束 — 仅 personal agent**：这个 MCP 包含 Human 的私人邮箱/日历/文件。**不要**把它加进 admin / ops / dev-alex / qa-lucy / 任何工作 agent 的 MCP 列表，无论是 `mcp_servers:` 顶层 dict 还是 `extra_mcp_servers:` 块。它只属于 personal agent。

## Architecture

```
Personal Agent (Claude Code session)
  → stdio MCP: workspace-mcp --single-user --permissions ...
    → loads cached refresh token from ~/.google_workspace_mcp/credentials/
    → calls Google APIs (Gmail / Calendar / Drive)
```

OAuth 流程是**一次性**的。Refresh token 缓存到本地后，每次启动 MCP 都会自动 reuse。

## One-Time Setup

### Step 1 — Human creates OAuth Client（Google Cloud Console）

1. 打开 https://console.cloud.google.com/
2. 创建一个 project（或 reuse existing），命名建议 `personal-agent-mcp`
3. **APIs & Services → Library**：enable
   - Gmail API
   - Google Calendar API
   - Google Drive API
4. **APIs & Services → OAuth consent screen**：
   - User type: **External**（personal Gmail 不用 Workspace org）
   - Add yourself as test user
   - Scopes: 跳过（让 MCP 在 token exchange 时声明）
5. **APIs & Services → Credentials → Create Credentials → OAuth client ID**：
   - Application type: **Desktop app**
   - Name: `personal-agent-mcp`
   - 拿到 **Client ID** + **Client Secret**
6. **存到 1Password Personal vault**（**不要存 Agents vault**）：
   - Item title: `Google OAuth — Personal MCP`
   - Fields: `client_id`, `client_secret`
7. 把这两个值发给 admin（admin 转给 dev-alex）

### Step 2 — dev-alex provisions OAuth token

在 `/private/tmp/wt-494-google-personal` worktree 里：

```bash
export GOOGLE_OAUTH_CLIENT_ID="<from 1Password>"
export GOOGLE_OAUTH_CLIENT_SECRET="<from 1Password>"
export OAUTHLIB_INSECURE_TRANSPORT=1   # localhost callback 需要

# 启动 MCP（stdio 模式，但我们只是为了触发 OAuth flow）
uvx workspace-mcp --single-user --permissions gmail:full drive:readonly calendar:full
```

第一次调用任何工具会触发 OAuth：
1. MCP 返回 auth URL
2. dev-alex 把 URL 发给 admin → admin 转 Human
3. Human 浏览器打开 → Google consent → Google redirect 到 `http://localhost:8000/...` callback
4. 内置的 minimal HTTP server 自动捕获 code 完成 token exchange
5. Refresh token 写入 `~/.google_workspace_mcp/credentials/<gmail>.json`，权限 `0o600`

### Step 3 — 备份 refresh token 到 1Password Personal vault

```bash
cat ~/.google_workspace_mcp/credentials/<gmail>.json
# 复制内容到 1Password Personal vault
# Item title: "Google MCP — Refresh Token (Personal)"
# Note field 粘贴整个 JSON
```

灾难恢复时（删了本地 token / 换机器）从 1Password 还原即可，不用重新 OAuth。

### Step 4 — 验证 MCP 可用

```bash
# Quick smoke test：让 MCP 列出最近 5 封邮件
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | \
  uvx workspace-mcp --single-user --permissions gmail:full drive:readonly calendar:full --transport stdio
```

应看到 tools list 包含：
- `search_gmail_messages`, `get_gmail_message_content`, `send_gmail_message`, `manage_gmail_label`
- `list_calendars`, `get_events`, `manage_event`
- `search_drive_files`, `get_drive_file_content`

## Wiring into Personal Agent (#497 — NOT this ticket)

当 ticket #497 注册 personal agent 时，在 `agents.yaml` 里这样加：

```yaml
agents:
  personal:                          # 或 "personal-<name>"
    project: agents
    work_stream: personal
    template: assistant              # 或新建 personal template
    role: 个人助理
    description: Human 的个人事务（私人邮件/日历/Drive/iMessage/微信）
    dispatchable: true
    add_dirs:
      - .
    extra_mcp_servers:
      google_personal:
        command: uvx
        args:
          - workspace-mcp
          - --single-user
          - --permissions
          - gmail:full
          - drive:readonly
          - calendar:full
        env:
          GOOGLE_OAUTH_CLIENT_ID: ${GOOGLE_PERSONAL_OAUTH_CLIENT_ID}
          GOOGLE_OAUTH_CLIENT_SECRET: ${GOOGLE_PERSONAL_OAUTH_CLIENT_SECRET}
          OAUTHLIB_INSECURE_TRANSPORT: "1"
```

**关键点**：
- 配置放在 `agents.personal.extra_mcp_servers`，**不放** `mcp_servers:` 顶层 dict — 这是确保工作 agent 拿不到的唯一办法（见 `setup-agents.py:63`，顶层 dict 会被所有 v1 agent auto-load）
- 环境变量从 `.env` 读，`.env` 不进 git
- v2 agent_types 也别加（如果未来 personal 走 v2 path）

## Permission Levels Cheat Sheet

| Service | Level | Scope |
|---------|-------|-------|
| `gmail:readonly` | List + read | `gmail.readonly` |
| `gmail:organize` | + label management | `gmail.modify` |
| `gmail:drafts` | + draft create/edit | `gmail.compose` |
| `gmail:send` | + send | `gmail.send` |
| `gmail:full` | All of above (cumulative) | `gmail.modify` + `gmail.send` |
| `drive:readonly` | List + read files (incl. Docs/Sheets) | `drive.readonly` |
| `drive:full` | + create/edit/delete | `drive` |
| `calendar:readonly` | Read events | `calendar.readonly` |
| `calendar:full` | + create/modify/delete | `calendar` |

我们目前用 `gmail:full + drive:readonly + calendar:full`。Drive write 留给未来 (Human 当前没要求)。

## Token Refresh / Rotation

Refresh token 默认长期有效（除非 Human 在 https://myaccount.google.com/permissions 主动 revoke）。如果 token 失效：

1. 删除 `~/.google_workspace_mcp/credentials/*.json`
2. 重跑 Step 2 的 OAuth flow（需 Human 重新点 consent）
3. 备份新 token 到 1Password

## Pitfalls

1. **`OAUTHLIB_INSECURE_TRANSPORT=1` 是必需的** — Google 要求 OAuth callback 必须 HTTPS，但本地 stdio MCP 用 `http://localhost:8000`。这个环境变量告诉 oauthlib 接受 http。仅本地有效，无安全影响。
2. **Test User 列表** — OAuth Consent Screen 在 testing 阶段必须把 Human 的 Gmail 加进 test users，否则 consent 时会报 "Access blocked"。如果未来要分享给别人就要 publish app（要 Google 审核）。
3. **不要把 client_secret 进 git** — 即使是 personal credential，永远只走 `.env` + 1Password。
4. **Drive native format reads** — `get_drive_file_content` 对 Google Docs/Sheets 会自动 export 成 plaintext/CSV。如果未来要保留格式（拉 markdown 给 LLM），需要 export as `text/markdown` (Docs 支持) 或自己处理。
5. **Single-user mode 不支持多账号** — 只能给一个 Gmail 接入。如果 Human 有多个 personal email 都要接，需要 (a) 用 multi-user OAuth 2.1 模式（streamable-http transport，更复杂），或 (b) 跑多个 MCP 实例分别命名。

## References

- Upstream: https://github.com/taylorwilsdon/google_workspace_mcp
- PyPI: https://pypi.org/project/workspace-mcp/
- Ticket #494 (this setup): MCP install + OAuth provision
- Ticket #497 (next): personal agent registration + isolation verify
- Sibling: `microsoft-mcp` (`agents.yaml` `mcp_servers.microsoft`) — same pattern, but global因为 microsoft 也用于 work assistant 类似场景
