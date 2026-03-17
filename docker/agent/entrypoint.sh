#!/bin/bash
set -euo pipefail

echo "=== Agent Hub — Docker Agent Mode ==="
echo "  Claude Code: $(claude --version 2>/dev/null || echo 'not found')"
echo "  Node.js:     $(node --version)"
echo "  Python:      $(python3 --version)"
echo "  uv:          $(uv --version)"
echo ""

# --- Authentication check ---
if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] && [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ERROR: No authentication configured."
  echo ""
  echo "Set one of these environment variables:"
  echo "  CLAUDE_CODE_OAUTH_TOKEN  — Run 'claude setup-token' locally to get a token"
  echo "  ANTHROPIC_API_KEY        — API key from console.anthropic.com"
  echo ""
  echo "Example:"
  echo "  echo 'CLAUDE_CODE_OAUTH_TOKEN=sk-...' >> .env"
  echo "  docker compose --profile agents up"
  exit 1
fi

if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  echo "  Auth: OAuth token"
else
  echo "  Auth: API key"
fi

# --- Install MCP proxy Python dependencies ---
echo ""
echo "=== Installing MCP proxy dependencies ==="
cd /app/services/agents-mcp
# Try frozen install first, fall back to unfrozen if lock file mismatch
uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev
cd /app

# --- Generate agent workspaces ---
echo ""
echo "=== Generating agent workspaces ==="
python3 setup-agents.py

# --- Start agents (daemon runs in separate container) ---
echo ""
echo "=== Starting agents ==="
export SKIP_DAEMON=1
./restart_all_agents.sh

echo ""
echo "=== Agents running ==="
echo "  Attach to tmux: docker exec -it <container> tmux attach -t agents"
echo "  View agent:     docker exec -it <container> tmux select-window -t agents:<agent-id>"
echo ""

# Keep container alive (agents run in tmux background)
exec tail -f /dev/null
