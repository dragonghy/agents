# Getting Started

This guide walks you through setting up Agent-Hub from scratch.

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | 3.11+ | Daemon, agent scripts |
| [uv](https://docs.astral.sh/uv/) | Latest | Python package management |
| Docker + Docker Compose | Latest | Leantime backend |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | Latest | Agent runtime |
| Anthropic API key | — | Powers the Claude agents |
| Node.js | 18+ | Web UI (optional) |

## Step 1: Clone and Configure

```bash
git clone https://github.com/anthropics/agent-hub.git
cd agent-hub
```

Copy the environment template and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required
LEANTIME_API_KEY=your_leantime_api_key_here    # Get this from Leantime admin panel
LEANTIME_USER_EMAIL=your_email@example.com     # Your Leantime user email

# MySQL passwords (choose strong passwords)
MYSQL_ROOT_PASSWORD=your_mysql_root_password
MYSQL_PASSWORD=your_mysql_user_password
LEAN_SESSION_PASSWORD=your_random_session_string

# Optional
LEANTIME_URL=http://localhost:9090             # Default Leantime URL
VM_MCP_DIR=/path/to/vm-mcp                    # Only if using vm-mcp integration
```

## Step 2: Start Leantime

Leantime is the project management backend that stores tickets, comments, and project data.

```bash
source .env
docker compose -f services/leantime/docker-compose.yml up -d
```

Wait for the containers to be healthy:

```bash
docker compose -f services/leantime/docker-compose.yml ps
```

Once running, access Leantime at `http://localhost:9090` and complete the initial setup:

1. Create an admin account
2. Create a project (note the project ID — you'll use it in `agents.yaml`)
3. Go to **Settings > API** and generate an API key
4. Update `LEANTIME_API_KEY` in your `.env` file

## Step 3: Configure agents.yaml

The main configuration file `agents.yaml` defines your agent team. The default configuration includes:

- **product-kevin** — Product Manager
- **dev-alex** — Developer
- **qa-lucy** — QA Engineer

Key settings:

```yaml
# Leantime connection (credentials loaded from .env)
leantime:
  url: ${LEANTIME_URL:-http://localhost:9090}
  api_key: ${LEANTIME_API_KEY}
  project_id: 3          # Your Leantime project ID
  user_id: 1
  user_email: ${LEANTIME_USER_EMAIL}

# Daemon configuration
daemon:
  host: 127.0.0.1
  port: 8765
```

Adjust `project_id` to match the project you created in Leantime.

## Step 4: Generate Agent Workspaces

```bash
python3 setup-agents.py
```

This creates the runtime workspace for each agent:
- `.claude/agents/<instance>.md` — Instance-specific agent definition (from template)
- `.mcp.json` — MCP server configuration
- `.claude/skills/` — Symlinks to shared and role-specific skills
- `team-roster.md` — Auto-generated team roster

## Step 5: Start the System

```bash
./restart_all_agents.sh
```

This script:
1. Builds the Web UI (if Node.js is available)
2. Starts the agents-mcp daemon on the configured port
3. Creates a tmux session with one window per agent
4. Launches each agent as a Claude Code instance

## Step 6: Verify

### Check the tmux session

```bash
tmux attach -t agents
# Switch between agent windows: Ctrl-b n (next) / Ctrl-b p (previous)
# Detach: Ctrl-b d
```

### Check the Web UI

Open `http://localhost:8765` in your browser. You should see:
- Agent status cards (idle/busy)
- Ticket list from Leantime
- Real-time updates via WebSocket

### Verify agent connectivity

Create a test ticket in Leantime assigned to one of your agents, then dispatch:

```bash
# Via the Web UI, or via the REST API:
curl -s -X POST http://localhost:8765/api/v1/agents/dev-alex/dispatch
```

The agent should pick up the ticket and start working.

## Troubleshooting

### Daemon won't start

```bash
# Check if the port is in use
lsof -i :8765

# Check daemon logs
cat .daemon.log
```

### Agent can't connect to daemon

```bash
# Verify the proxy config in the agent's .mcp.json
cat agents/dev-alex/.mcp.json

# The AGENTS_DAEMON_URL should point to the daemon's SSE endpoint
```

### Leantime connection errors

```bash
# Verify your API key works
curl -s -X POST http://localhost:9090/api/jsonrpc \
  -H "Content-Type: application/json" \
  -H "x-api-key: $LEANTIME_API_KEY" \
  -d '{"jsonrpc":"2.0","method":"leantime.rpc.Tickets.Tickets.getAll","params":{"searchCriteria":{"currentProject":3}},"id":1}'
```

### Docker Compose errors about missing variables

Make sure you've sourced `.env` before running docker compose:

```bash
source .env
docker compose -f services/leantime/docker-compose.yml up -d
```

## Next Steps

- Read [Architecture](architecture.md) to understand how the system works
- Check [CONTRIBUTING.md](../CONTRIBUTING.md) if you want to contribute
- Explore the agent templates in `agents/` to customize agent behavior
