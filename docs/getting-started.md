# Getting Started

This guide walks you through setting up Agent Hub from scratch. There are three ways to run it:

- **[Docker Quick Start](#docker-quick-start)** — Get the Web UI running in 2 minutes. Great for exploring the dashboard.
- **[Docker Agent Mode](#docker-agent-mode)** — Run the full system (daemon + agents) entirely in Docker. No local tool installation needed.
- **[Full Setup](#full-setup)** — Run on bare metal with maximum control. Best for development and customization.

---

## Docker Quick Start

The fastest way to see Agent Hub in action. This starts the daemon and Web UI in a single container.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose v2

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/dragonghy/agents.git
cd agents

# 2. Start the daemon
docker compose up --build -d

# 3. Open the Web UI
open http://localhost:3000
```

That's it. The Web UI shows the agent dashboard, ticket list, messages, and token usage analytics.

**Customization:**

```bash
# Use a different port
WEB_PORT=8080 docker compose up -d

# Stop
docker compose down

# Stop and remove data (SQLite databases)
docker compose down -v
```

Data (SQLite databases) is persisted in a Docker named volume, so `docker compose down && docker compose up` retains all data.

> **Note:** This starts the daemon and Web UI only. To run Claude Code agents in Docker, see [Docker Agent Mode](#docker-agent-mode). For a bare-metal setup, see [Full Setup](#full-setup).

---

## Docker Agent Mode

Run the complete system — daemon, Web UI, and Claude Code agents — entirely in Docker containers. Agents run in tmux sessions inside a single container, connected to the daemon via Docker networking.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose v2
- A Claude Code authentication token (see below)

### Authentication

Claude Code agents need authentication to communicate with the Claude API. Choose one method:

**OAuth Token (recommended)** — requires [Claude Pro or Max](https://claude.ai/upgrade):

```bash
# Run this on your local machine (not in Docker)
claude setup-token
# Copy the generated token
```

**API Key** — from [console.anthropic.com](https://console.anthropic.com):

```bash
# Use your Anthropic API key directly
ANTHROPIC_API_KEY=sk-ant-api03-...
```

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/dragonghy/agents.git
cd agents

# 2. Configure authentication
cp .env.example .env
# Edit .env and set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY

# 3. Start daemon + agents
docker compose --profile agents up --build -d

# 4. Open the Web UI
open http://localhost:3000
```

### Interacting with Agents

Agents run inside tmux sessions in the container. To observe them:

```bash
# Attach to the tmux session
docker exec -it agents-agents-1 tmux attach -t agents

# Navigation inside tmux:
# Ctrl-b n    Next agent window
# Ctrl-b p    Previous agent window
# Ctrl-b d    Detach (agents keep running)
```

Create a task for an agent:

```bash
curl -s -X POST http://localhost:3000/api/v1/tickets/create \
  -H 'Content-Type: application/json' \
  -d '{"headline": "Test task", "description": "Say hello", "assignee": "dev-alex"}'
```

The daemon dispatches the task to the agent within 30 seconds.

### Customization

```bash
# Use a different port
WEB_PORT=8080 docker compose --profile agents up -d

# Stop everything
docker compose --profile agents down

# Stop and remove data
docker compose --profile agents down -v
```

**Customize your agent team** by editing `agents.yaml` before starting. Remove agents you don't need, add new ones, or change roles. See [Configuration Reference](#configuration-reference) for details.

---

## Full Setup

The full setup runs Claude Code agents in tmux windows, coordinated by the central daemon. Agents autonomously pick up tasks, write code, run tests, and hand off work to each other.

### Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | 3.11+ | Daemon, configuration scripts |
| [uv](https://docs.astral.sh/uv/) | Latest | Python package management |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | Latest | Agent runtime |
| Anthropic API key | — | Powers the Claude agents |
| tmux | Latest | Agent session management |
| Node.js | 18+ | Web UI build (optional) |
| Git | Latest | Source control |

### Step 1: Clone and Configure

```bash
git clone https://github.com/dragonghy/agents.git
cd agents
```

Create your environment file:

```bash
cp .env.example .env
```

Edit `.env` if needed:

```bash
# Docker: Web UI port (default: 3000)
# WEB_PORT=3000

# Workspace: root directory for external project repos.
# Agents reference projects as ${WORKSPACE_DIR}/project-name in add_dirs.
# Only projects that exist on disk are mounted; missing ones are skipped.
WORKSPACE_DIR=~/workspace
```

The `WORKSPACE_DIR` is where external project repositories live. For example, if an agent needs access to a separate git repo, you'd clone it to `~/workspace/my-project` and reference it in `agents.yaml`.

### Step 2: Review agents.yaml

The main configuration file `agents.yaml` defines your agent team. Open it to understand the structure:

```yaml
# Workspace root (resolved from WORKSPACE_DIR env var)
workspace_dir: ${WORKSPACE_DIR:-~/workspace}

# tmux session name for all agent windows
tmux_session: agents

# Daemon configuration
daemon:
  host: 127.0.0.1
  port: 8765

# Agent definitions
agents:
  dev-alex:
    template: dev             # Uses templates/dev/ for role config
    role: Developer
    description: Tech design, code implementation, and testing
    dispatchable: true        # Daemon can auto-assign work
    add_dirs:                 # Additional directories the agent can access
      - ${WORKSPACE_DIR}/my-project
```

**Key concepts:**

- Each agent has a unique ID in the format `<role>-<name>` (e.g., `dev-alex`, `qa-lucy`)
- `template` points to a directory under `templates/` containing the agent's system prompt and skills
- `dispatchable: true` means the daemon will auto-assign pending tasks to this agent
- `add_dirs` lists additional directories the agent can read/write

**To customize your team**, edit the `agents:` section. You can:

- Remove agents you don't need
- Add new agents with existing templates (`dev`, `qa`, `product`, `admin`)
- Change agent descriptions and directory access

### Step 3: Generate Agent Workspaces

```bash
python3 setup-agents.py
```

This creates the runtime workspace for each agent defined in `agents.yaml`:

- `agents/<name>/` — Working directory for each agent
- `.claude/agents/<name>.md` — Agent definition with role-specific system prompt
- `.mcp.json` — MCP server configuration (proxy to central daemon)
- `agents/shared/team-roster.md` — Auto-generated team roster
- Skill symlinks from `templates/shared/skills/` and `templates/<role>/skills/`

### Step 4: Start the System

```bash
./restart_all_agents.sh
```

This script:

1. Sources `.env` for environment variables
2. Builds the Web UI (if Node.js is available)
3. Starts the agents-mcp daemon on the configured port (default: 8765)
4. Creates a tmux session with one window per agent
5. Launches each agent as a Claude Code instance

**Startup options:**

```bash
# Start all agents (default)
./restart_all_agents.sh

# Start only worker agents (skip admin)
./restart_all_agents.sh --workers

# Start a single agent
./restart_all_agents.sh dev-alex

# Restart just the daemon
./restart_all_agents.sh --daemon

# Stop the daemon
./restart_all_agents.sh --stop-daemon
```

### Step 5: Verify

#### Check the tmux session

```bash
tmux attach -t agents
```

You should see a tmux session with one window per agent. Each window shows the Claude Code CLI running for that agent.

```
# Navigation:
Ctrl-b n    # Next window
Ctrl-b p    # Previous window
Ctrl-b d    # Detach (agents keep running)
```

#### Check the Web UI

Open `http://localhost:8765` in your browser. You should see:

- **Dashboard** — Agent status cards showing idle/busy state and current context
- **Agents** — Detailed list with roles, workload, and terminal output
- **Tickets** — Task list with status, assignee, and comments
- **Messages** — Inter-agent communication history
- **Token Usage** — Per-agent cost analytics with daily/weekly views

#### Test agent dispatch

Create a task and assign it to an agent:

```bash
# Via the Web UI "Create Ticket" form, or via the REST API:
curl -s -X POST http://localhost:8765/api/v1/tickets/create \
  -H 'Content-Type: application/json' \
  -d '{"headline": "Test task", "description": "Say hello", "assignee": "dev-alex"}'
```

The daemon will dispatch the task to the agent within 30 seconds (or immediately via manual dispatch from the Web UI).

---

## Configuration Reference

### agents.yaml Structure

```yaml
workspace_dir: ${WORKSPACE_DIR:-~/workspace}   # Root for external repos
tmux_session: agents                            # tmux session name

daemon:
  host: ${DAEMON_HOST:-127.0.0.1}                # Daemon bind address (env override for Docker)
  port: 8765                                     # Daemon port

daily_journal:
  time: "01:00"                                  # Daily journal write time
  stagger_minutes: 5                             # Stagger between agents

staleness:
  threshold_minutes: 30                          # Idle agent alert threshold

mcp_servers:                                     # MCP servers per agent
  agents:                                        # The proxy to central daemon
    command: uv
    args: [run, --directory, "{ROOT_DIR}/services/agents-mcp", agents-mcp-proxy]

agents:
  <agent-id>:
    template: <role>          # dev, qa, product, admin, user
    project: <project-name>   # For workload grouping
    work_stream: <stream>     # dev, qa, product, admin, user, founder
    role: <display-role>      # Human-readable role name
    description: <text>       # What this agent does
    dispatchable: true/false  # Auto-dispatch enabled
    add_dirs:                 # Extra directories to access
      - ${WORKSPACE_DIR}/my-project
    schedule:                 # Optional scheduled wake-up
      interval_hours: 24
      offset_hours: 0
      prompt: "Wake up message..."
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKSPACE_DIR` | `~/workspace` | Root directory for external project repos |
| `WEB_PORT` | `3000` | Docker: exposed port for Web UI |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | Docker Agent Mode: OAuth token from `claude setup-token` |
| `ANTHROPIC_API_KEY` | — | Docker Agent Mode: API key from console.anthropic.com |
| `DAEMON_HOST` | `127.0.0.1` | Override daemon hostname (auto-set in Docker) |
| `SKIP_DAEMON` | — | Set to `1` to skip local daemon management |

### Data Storage

The daemon uses two SQLite databases, stored alongside `agents.yaml`:

- `.agents-tasks.db` — Tickets, subtasks, comments, status labels
- `.agents-mcp.db` — Agent profiles, P2P messages, token usage data

These are automatically created on first startup. Back them up if you want to preserve project history.

---

## Agent Roles

Agent Hub ships with five agent templates:

| Template | Role | Description |
|----------|------|-------------|
| `product` | Product Manager | Decomposes requirements into milestones and tickets, performs final acceptance |
| `dev` | Developer | Implements features, writes tests, hands off to QA |
| `qa` | QA Engineer | Runs E2E tests, verifies acceptance criteria, reports bugs |
| `admin` | Admin | System configuration, skill management, agent restarts |
| `user` | User Tester | Tests the system from a user perspective in isolated environments |

Agents collaborate through a ticket lifecycle:

```
Product → Dev → QA → Product
   ↑                    │
   └────── (reject) ────┘
```

---

## Troubleshooting

### Daemon won't start

```bash
# Check if the port is already in use
lsof -i :8765

# Check daemon logs
cat .daemon.log
```

### Agent can't connect to daemon

```bash
# Verify the proxy config
cat agents/dev-alex/.mcp.json

# The proxy should point to the daemon's SSE endpoint (localhost:8765/sse)
```

### Web UI not loading

```bash
# Check if static files are built
ls services/agents-mcp/src/agents_mcp/web/static/index.html

# Rebuild manually
cd services/agents-mcp/web && npm install && npm run build
```

### Docker build fails

```bash
# Docker registry timeout — just retry
docker compose build

# Port conflict
WEB_PORT=3001 docker compose up -d
```

### Agent shows "idle" but doesn't pick up tasks

The dispatch loop runs every 30 seconds. Check that:

1. The agent's `dispatchable` is `true` in `agents.yaml`
2. The ticket is assigned to the agent (tag `agent:<agent-id>`)
3. The ticket status is 3 (new) or 4 (in progress)
4. The agent's tmux window is actually running (`tmux attach -t agents`)

### Reset everything

```bash
# Stop all agents and daemon
./restart_all_agents.sh --stop-daemon
tmux kill-session -t agents

# Remove generated files
rm -rf agents/ .mcp.json .agent-sessions

# Regenerate and restart
python3 setup-agents.py
./restart_all_agents.sh
```

---

## Next Steps

- Read [Architecture](architecture.md) to understand how the system works internally
- Explore agent templates in `templates/` to customize agent behavior
- Add project-specific skills in `templates/<role>/skills/`
- Check the Web UI at `http://localhost:8765` for real-time monitoring
