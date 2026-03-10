# Architecture

## Overview

Agent-Hub is a multi-agent development framework where autonomous AI agents collaborate on software projects. The system follows a hub-and-spoke architecture with a central daemon coordinating agent activities.

```
                          ┌──────────────┐
                          │   Leantime   │
                          │  (Tickets,   │
                          │  Comments,   │
                          │  Projects)   │
                          └──────┬───────┘
                                 │ JSON-RPC
                                 │
┌────────────────────────────────┼────────────────────────────────┐
│                         agents-mcp daemon                       │
│                                │                                │
│  ┌─────────────┐  ┌───────────┴──────────┐  ┌───────────────┐ │
│  │  Dispatcher  │  │   LeantimeClient     │  │  AgentStore   │ │
│  │  - dispatch  │  │   - ticket CRUD      │  │  - profiles   │ │
│  │    loop      │  │   - comments         │  │  - messages   │ │
│  │  - staleness │  │   - staleness check  │  │  - SQLite     │ │
│  │  - journals  │  │                      │  │               │ │
│  └──────┬──────┘  └──────────────────────┘  └───────────────┘ │
│         │                                                      │
│  ┌──────┴───────────────────────────────────────────────────┐  │
│  │                    FastMCP Server                         │  │
│  │  MCP Tools: list_tickets, create_ticket, reassign_ticket, │  │
│  │  send_message, get_inbox, dispatch_agents, update_profile │  │
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
- `leantime_client.py` — Leantime JSON-RPC API wrapper
- `store.py` — SQLite-backed agent profiles and P2P messages
- `web/api.py` — Starlette REST API router

### MCP Proxy

Each agent runs `agents-mcp-proxy`, a lightweight process that connects to the daemon's SSE endpoint. This allows agents to call MCP tools without each spawning a full server.

```
Agent (Claude Code) → agents-mcp-proxy → daemon SSE endpoint → FastMCP tools
```

### Leantime Integration

[Leantime](https://leantime.io) serves as the project management database. Agent-Hub interacts with it via JSON-RPC API.

**Data stored in Leantime:**
- Tickets (tasks assigned to agents)
- Comments (handoff notes, QA reports, reviews)
- Projects (logical grouping of work)

**Data stored locally (SQLite):**
- Agent profiles (identity, current context, expertise)
- P2P messages between agents
- Session metadata

### Agent Templates

Agent behavior is defined by templates in `agents/`:

```
agents/
├── product/          # Product Manager template
│   ├── system_prompt.md    # Role definition, workflow rules
│   ├── CLAUDE.md           # Project-level instructions
│   └── skills/             # Role-specific skills
├── dev/              # Developer template
├── qa/               # QA Engineer template
├── user/             # User Experience Tester template
└── shared/           # Resources shared by all agents
    └── skills/       # Cross-role skills (leantime, daily-journal, etc.)
```

When agents share a template (e.g., `dev-alex` and `dev-emma` both use `dev/`), `setup-agents.py` generates instance-specific workspaces with the agent's unique ID substituted into the system prompt.

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
- `leantime` — Connection details for the Leantime backend
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
├── agents/                      # Agent templates
│   ├── product/                 #   Product Manager
│   ├── dev/                     #   Developer
│   ├── qa/                      #   QA Engineer
│   ├── user/                    #   User Experience Tester
│   ├── shared/skills/           #   Shared skills
│   ├── product-kevin/           #   (generated) Instance workspace
│   ├── dev-alex/                #   (generated) Instance workspace
│   └── ...
│
├── services/
│   ├── agents-mcp/              # MCP daemon
│   │   ├── src/agents_mcp/      #   Python source
│   │   │   ├── server.py        #     MCP tools + config
│   │   │   ├── dispatcher.py    #     Auto-dispatch loop
│   │   │   ├── leantime_client.py #   Leantime API wrapper
│   │   │   ├── store.py         #     SQLite profiles/messages
│   │   │   └── web/             #     REST API + static files
│   │   └── web/                 #   React dashboard source
│   └── leantime/                # Leantime Docker setup
│       ├── docker-compose.yml
│       └── plugins/             #   Custom Leantime plugins (AGPL-3.0)
│
├── projects/                    # Per-project docs and skills
│   └── agent-hub/               #   This project's docs
│
└── tests/                       # E2E test tooling
    ├── e2e_env.py               #   Isolated env manager
    └── presets/                  #   Test environment presets
```
