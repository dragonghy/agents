# Agent-Hub

A multi-agent software development framework powered by [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Autonomous **Product**, **Dev**, and **QA** agents collaborate through structured workflows — planning features, writing code, and verifying quality — coordinated by a central MCP daemon and backed by [Leantime](https://leantime.io) project management.

## Key Features

- **Role-based agents** — Product Manager, Developer, QA Engineer, each with specialized system prompts and skills
- **Milestone-driven development** — Product decomposes requirements into milestones, Dev implements, QA verifies
- **Automatic dispatch** — Daemon monitors idle agents and assigns pending work automatically
- **Ticket lifecycle** — Tickets flow Dev → QA → Product via `reassign_ticket`, maintaining full context
- **P2P messaging** — Agents communicate directly for quick coordination
- **Web dashboard** — Real-time monitoring of agent status, tickets, and logs
- **Isolated testing** — Spin up temporary agent teams for end-to-end testing without affecting production

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    agents-mcp daemon                     │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌────────┐ │
│  │ Dispatch  │  │  Ticket   │  │ Messaging│  │ Web UI │ │
│  │  Loop     │  │  Manager  │  │  Store   │  │  SPA   │ │
│  └──────────┘  └───────────┘  └──────────┘  └────────┘ │
│       MCP (SSE)      │      REST API      │  WebSocket  │
└───────────┬──────────┼────────────────────┼─────────────┘
            │          │                    │
   ┌────────┴────┐  ┌──┴───────┐     ┌─────┴──────┐
   │ Claude Code │  │ Leantime │     │  Browser   │
   │   Agents    │  │  (PM DB) │     │ Dashboard  │
   │             │  │          │     │            │
   │ product-*   │  │ Tickets  │     │ Agent view │
   │ dev-*       │  │ Comments │     │ Ticket list│
   │ qa-*        │  │ Projects │     │ Terminal   │
   └─────────────┘  └──────────┘     └────────────┘
```

Each agent runs as an independent Claude Code instance inside a **tmux** window, connected to the central daemon via MCP proxy.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker & Docker Compose
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) with an Anthropic API key
- Node.js 18+ (optional, for Web UI)

### Setup

```bash
# 1. Clone
git clone https://github.com/anthropics/agent-hub.git
cd agent-hub

# 2. Configure environment
cp .env.example .env
# Edit .env — fill in your Leantime API key and other credentials

# 3. Start Leantime (project management backend)
source .env
docker compose -f services/leantime/docker-compose.yml up -d

# 4. Generate agent workspaces
python3 setup-agents.py

# 5. Start the daemon and all agents
./restart_all_agents.sh
```

After startup, attach to the tmux session to observe agents:

```bash
tmux attach -t agents
# Switch tabs: Ctrl-b n / Ctrl-b p
# Detach: Ctrl-b d
```

The Web UI is available at `http://localhost:8765` when the daemon is running.

For detailed setup instructions, see [docs/getting-started.md](docs/getting-started.md).

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Full installation and configuration guide |
| [Architecture](docs/architecture.md) | System design, components, and communication flow |
| [Contributing](CONTRIBUTING.md) | How to contribute to Agent-Hub |

## Project Structure

```
agent-hub/
├── agents.yaml              # Central configuration (agents, daemon, Leantime)
├── .env                      # Credentials and local paths (gitignored)
├── .env.example              # Template for .env
├── setup-agents.py           # Generate agent workspaces from agents.yaml
├── restart_all_agents.sh     # Start/restart daemon and agents
├── .claude/agents/           # Agent definitions (YAML frontmatter + system prompts)
├── templates/                # Agent template resources (tracked in git)
│   ├── product/              #   Product Manager (CLAUDE.md + skills/)
│   ├── dev/                  #   Developer (CLAUDE.md)
│   ├── qa/                   #   QA Engineer (CLAUDE.md)
│   ├── admin/                #   Admin (CLAUDE.md + skills/)
│   └── shared/               #   Shared skills (leantime, daily-journal, etc.)
├── agents/                   # Generated workspaces (gitignored, created by setup-agents.py)
├── services/
│   ├── agents-mcp/           # Central MCP daemon (Python/FastMCP)
│   │   ├── src/agents_mcp/   #   Server, dispatcher, Leantime client
│   │   └── web/              #   React dashboard (Vite + Tailwind)
│   └── leantime/             # Leantime Docker setup + plugins
├── projects/                 # Project-specific docs and skills
└── tests/                    # E2E test environment tools
```

## How It Works

1. **Product** receives a feature request, breaks it into milestones and tickets
2. **Dev** picks up development tickets, implements and tests the code
3. Dev completes work and reassigns the ticket to **QA** via `reassign_ticket`
4. **QA** runs verification tests and either approves or sends back for fixes
5. The **daemon** automatically dispatches idle agents when new tickets arrive

Agents communicate through Leantime ticket comments for formal handoffs and P2P messages for quick coordination. The daemon runs a dispatch loop every 30 seconds, checking for pending work and idle agents.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

**Exception:** Leantime plugins in `services/leantime/plugins/` are subject to [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html) as they run within the Leantime application. See [services/leantime/plugins/LICENSE-NOTE.md](services/leantime/plugins/LICENSE-NOTE.md).
