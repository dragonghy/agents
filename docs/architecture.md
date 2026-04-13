# Architecture

## Overview

Agent-Hub is a multi-agent development framework where autonomous AI agents collaborate on software projects. The system follows a hub-and-spoke architecture with a central daemon coordinating agent activities.

```
┌────────────────────────────────────────────────────────────────┐
│                         agents-mcp daemon                       │
│                                                                │
│  ┌─────────────┐  ┌──────────────────────┐  ┌───────────────┐ │
│  │  Dispatcher  │  │  SQLiteTaskClient    │  │  AgentStore   │ │
│  │  - dispatch  │  │   - ticket CRUD      │  │  - profiles   │ │
│  │    loop      │  │   - comments         │  │  - messages   │ │
│  │  - staleness │  │   - staleness check  │  │  - SQLite     │ │
│  │  - journals  │  │   - SQLite storage   │  │               │ │
│  └──────┬──────┘  └──────────────────────┘  └───────────────┘ │
│         │                                                      │
│  ┌──────┴───────────────────────────────────────────────────┐  │
│  │                    FastMCP Server                         │  │
│  │  MCP Tools: list_tickets, create_ticket, reassign_ticket, │  │
│  │  send_message, get_inbox, get_profile, update_profile     │  │
│  └──────┬───────────────────────────────────────────────────┘  │
│         │ SSE                                                   │
│  ┌──────┴──────┐  ┌──────────────┐  ┌────────────────────────┐│
│  │  MCP Proxy  │  │  REST API    │  │  Web UI (Static SPA)   ││
│  │  Endpoint   │  │  /api/v1/*   │  │  React + Tailwind      ││
│  │  /sse       │  │              │  │  WebSocket live updates ││
│  └──────┬──────┘  └──────┬───────┘  └────────────┬───────────┘│
└─────────┼────────────────┼───────────────────────┼────────────┘
          │                │                       │
    ┌─────┴─────┐    ┌────┴─────┐           ┌─────┴─────┐
    │  Claude   │    │  curl /  │           │  Browser  │
    │  Code     │    │  scripts │           │           │
    │  Agents   │    │          │           │           │
    └───────────┘    └──────────┘           └───────────┘
```

## Components

### agents-mcp Daemon

The central process that coordinates everything. Built with [FastMCP](https://github.com/jlowin/fastmcp) and [Starlette](https://www.starlette.io/).

**Responsibilities:**
- Expose MCP tools to agents (via SSE)
- Provide REST API for external access
- Run the auto-dispatch loop
- Serve the Web UI
- Store agent profiles and messages (SQLite)

**Key modules:**
- `server.py` — FastMCP tool definitions, config loading
- `dispatcher.py` — Dispatch loop, staleness detection, journal scheduling
- `sqlite_task_client.py` — SQLite-backed task management client
- `store.py` — SQLite-backed agent profiles and P2P messages
- `web/api.py` — Starlette REST API router

### MCP Proxy

Each agent runs `agents-mcp-proxy`, a lightweight process that connects to the daemon's SSE endpoint. This allows agents to call MCP tools without each spawning a full server.

```
Agent (Claude Code) → agents-mcp-proxy → daemon SSE endpoint → FastMCP tools
```

### Task Management

All task data is stored locally in SQLite (`.agents-tasks.db`):
- Tickets (tasks assigned to agents)
- Comments (handoff notes, QA reports, reviews)
- Projects (logical grouping of work)

**Additional data in SQLite (`.agents-mcp.db`):**
- Agent profiles (identity, current context, expertise)
- P2P messages between agents
- Session metadata

### Agent Templates

Agent behavior is defined using Claude Code's native agent definition format. Template definitions live in `.claude/agents/` (system prompts) and `templates/` (workspace resources):

```
.claude/agents/
├── product.md        # Product Manager agent definition (YAML frontmatter + system prompt)
├── dev.md            # Developer agent definition
├── qa.md             # QA Engineer agent definition
├── user.md           # User Experience Tester agent definition
└── admin.md          # Admin agent definition

templates/
├── product/          # Product Manager template resources
│   ├── CLAUDE.md           # Project-level instructions
│   └── skills/             # Role-specific skills
├── dev/              # Developer template resources
│   └── CLAUDE.md
├── qa/               # QA Engineer template resources
│   └── CLAUDE.md
├── user/             # User Experience Tester template resources
│   ├── CLAUDE.md
│   └── skills/
├── admin/            # Admin template resources
│   ├── CLAUDE.md
│   └── skills/
└── shared/           # Resources shared by all agents
    └── skills/       # Cross-role skills (tasks, daily-journal, etc.)
```

Each agent definition file uses YAML frontmatter for configuration (name, description, model) and Markdown body for the system prompt. When agents share a template (e.g., `dev-alex` and `dev-emma` both use `dev/`), `setup-agents.py` generates instance-specific agent definitions at `.claude/agents/<instance>.md` with the agent's unique ID substituted into the prompt.

The `agents/` directory is entirely generated by `setup-agents.py` at runtime and is gitignored.

## Communication Flow

### Ticket Lifecycle

```
Product creates ticket → assigns to Dev
                              │
                         Dev works on it
                              │
                    Dev calls reassign_ticket → QA
                              │
                         QA verifies
                              │
                ┌─────────────┴─────────────┐
                │                           │
          QA approves                  QA rejects
                │                           │
     reassign → Product            reassign → Dev
                │                     (with bug report)
          Product closes
```

A single ticket flows through its entire lifecycle without creating duplicates. The `reassign_ticket` tool changes the assignee and optionally adds a handoff comment.

### Auto-Dispatch

The daemon runs a dispatch loop (default: every 30 seconds):

1. **Check messages first** — If an agent has unread P2P messages, dispatch with "check messages" prompt
2. **Check tasks** — If an agent has pending tickets (status 3 or 4), dispatch with "check tasks" prompt
3. **Staleness detection** — If an idle agent has in_progress tickets older than 30 minutes, dispatch with a targeted reminder listing the specific ticket IDs
4. **Skip busy agents** — Only dispatches to agents whose tmux window shows an idle prompt

Dispatch sends a message to the agent's tmux window, triggering Claude Code to process it.

### P2P Messaging

Agents can send direct messages for quick coordination:

```python
send_message(from_agent="dev-alex", to_agent="qa-lucy", message="Question about test scope")
```

Messages are stored in SQLite and delivered on the next dispatch cycle.

## Configuration

### agents.yaml

The central configuration file. Supports `${ENV_VAR}` and `${ENV_VAR:-default}` syntax for credential externalization.

Key sections:
- `project_id` — Default project ID for task management
- `daemon` — Host and port for the MCP daemon
- `mcp_servers` — MCP server definitions for agent proxy connections
- `agents` — Agent definitions with roles, templates, and dispatch settings
- `daily_journal` — Scheduled journal writing configuration
- `staleness` — Staleness detection threshold

### .env

All credentials and local paths are stored in `.env` (gitignored). See `.env.example` for the full list of variables.

## Directory Structure

```
agent-hub/
├── agents.yaml                  # Central config
├── .env / .env.example          # Credentials
├── config_utils.py              # Env var resolution for YAML
├── setup-agents.py              # Workspace generator
├── agent-config.py              # CLI helper for shell scripts
├── restart_all_agents.sh        # System startup script
│
├── .claude/agents/              # Native agent definitions (YAML frontmatter + prompt)
│   ├── product.md               #   Product Manager (template, tracked)
│   ├── dev.md                   #   Developer (template, tracked)
│   ├── qa.md                    #   QA Engineer (template, tracked)
│   ├── user.md                  #   User Experience Tester (template, tracked)
│   ├── admin.md                 #   Admin (template, tracked)
│   ├── dev-alex.md              #   (generated) Instance definition
│   └── ...                      #   (generated) Other instances
│
├── templates/                   # Template sources (tracked in git)
│   ├── product/                 #   Product Manager (CLAUDE.md, skills)
│   ├── dev/                     #   Developer (CLAUDE.md)
│   ├── qa/                      #   QA Engineer (CLAUDE.md)
│   ├── user/                    #   User Experience Tester (CLAUDE.md, skills)
│   ├── admin/                   #   Admin (CLAUDE.md, skills)
│   └── shared/skills/           #   Shared skills (tasks, daily-journal, etc.)
│
├── agents/                      # (generated, gitignored) Runtime agent workspaces
│   ├── product-kevin/           #   Instance workspace
│   ├── dev-alex/                #   Instance workspace
│   └── ...
│
├── services/
│   ├── agents-mcp/              # MCP daemon
│   │   ├── src/agents_mcp/      #   Python source
│   │   │   ├── server.py        #     MCP tools + config
│   │   │   ├── dispatcher.py    #     Auto-dispatch loop
│   │   │   ├── sqlite_task_client.py #   SQLite task management
│   │   │   ├── store.py         #     SQLite profiles/messages
│   │   │   └── web/             #     REST API + static files
│   │   └── web/                 #   React dashboard source
│   └── (legacy leantime/ removed — task management now uses built-in SQLite)
│
├── projects/                    # Per-project docs and skills
│   └── agent-hub/               #   This project's docs
│
└── tests/                       # E2E test tooling
    ├── e2e_env.py               #   Isolated env manager
    └── presets/                  #   Test environment presets
```
