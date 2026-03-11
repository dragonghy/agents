#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${ROOT_DIR}/projects"
CONFIG="${ROOT_DIR}/agent-config.py"

# Load environment variables from .env (for credentials and paths)
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

TMUX_SESSION="$(python3 "$CONFIG" tmux-session)"
ALL_AGENTS="$(python3 "$CONFIG" list-agents | tr '\n' ' ')"
WORKERS="$(python3 "$CONFIG" list-workers | tr '\n' ' ')"

mkdir -p "$PROJECT_DIR"

# --- Daemon management ---

DAEMON_LOG="${ROOT_DIR}/.daemon.log"
DAEMON_PID_FILE="${ROOT_DIR}/.daemon.pid"

get_daemon_port() {
  python3 -c "
import yaml, sys
with open('${ROOT_DIR}/agents.yaml') as f:
    cfg = yaml.safe_load(f)
d = cfg.get('daemon', {})
print(d.get('port', ''))
"
}

get_daemon_host() {
  python3 -c "
import yaml, sys
with open('${ROOT_DIR}/agents.yaml') as f:
    cfg = yaml.safe_load(f)
d = cfg.get('daemon', {})
print(d.get('host', '127.0.0.1'))
"
}

daemon_is_running() {
  local port
  port="$(get_daemon_port)"
  [[ -z "$port" ]] && return 1
  lsof -i ":${port}" -sTCP:LISTEN >/dev/null 2>&1
}

build_web_ui() {
  local web_dir="${ROOT_DIR}/services/agents-mcp/web"
  local static_dir="${ROOT_DIR}/services/agents-mcp/src/agents_mcp/web/static"

  if [[ -f "${static_dir}/index.html" ]]; then
    return 0  # Already built
  fi

  if [[ ! -f "${web_dir}/package.json" ]]; then
    echo "  Web UI: source not found, skipping build"
    return 0
  fi

  if ! command -v npm &>/dev/null; then
    echo "  Web UI: npm not found, skipping build (install Node.js to enable)"
    return 0
  fi

  echo "  Web UI: building frontend..."
  (cd "$web_dir" && npm install --silent 2>/dev/null && npm run build --silent 2>/dev/null)
  if [[ -f "${static_dir}/index.html" ]]; then
    echo "  Web UI: build successful"
  else
    echo "  Web UI: build failed (daemon will start without Web UI)"
  fi
}

start_daemon() {
  local port host
  port="$(get_daemon_port)"
  host="$(get_daemon_host)"
  [[ -z "$port" ]] && return 0  # No daemon configured

  if daemon_is_running; then
    echo "  Daemon already running on ${host}:${port}"
    return 0
  fi

  # Build Web UI if not already built
  build_web_ui

  echo "  Starting daemon on ${host}:${port}..."
  AGENTS_CONFIG_PATH="${ROOT_DIR}/agents.yaml" \
    nohup uv run --directory "${ROOT_DIR}/services/agents-mcp" \
    agents-mcp --daemon --host "$host" --port "$port" \
    > "$DAEMON_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$DAEMON_PID_FILE"

  # Wait for daemon to be ready (up to 15 seconds)
  local tries=0
  while ! daemon_is_running; do
    tries=$((tries + 1))
    if [[ $tries -ge 30 ]]; then
      echo "  ERROR: Daemon failed to start. Check ${DAEMON_LOG}"
      return 1
    fi
    sleep 0.5
  done
  echo "  Daemon started (pid: $pid)"
}

stop_daemon() {
  local port
  port="$(get_daemon_port)"
  [[ -z "$port" ]] && return 0

  if ! daemon_is_running; then
    echo "  Daemon not running"
    return 0
  fi

  # Find and kill the process listening on the daemon port
  local pids
  pids="$(lsof -t -i ":${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill 2>/dev/null || true
    echo "  Daemon stopped"
  fi
  rm -f "$DAEMON_PID_FILE"
}

# --- Agent management ---

ensure_session() {
  if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TMUX_SESSION" -n "_init"
    tmux set-option -t "$TMUX_SESSION" remain-on-exit on
  fi
}

AGENTS_NEEDING_SESSION=()

start_agent() {
  local agent="$1"
  local agent_def="${ROOT_DIR}/.claude/agents/${agent}.md"

  if [[ ! -f "$agent_def" ]]; then
    echo "  SKIP: no agent definition found at ${agent_def}"
    return
  fi
  local agent_flag="--agent ${agent}"

  local sid
  sid="$(python3 "$CONFIG" get-session "$agent")"

  # Track agents without session ID for post-startup capture
  if [[ -z "$sid" ]]; then
    AGENTS_NEEDING_SESSION+=("$agent")
  fi

  # Build --add-dir flags
  local add_dir_flags=""
  while IFS= read -r dir; do
    [[ -n "$dir" ]] && add_dir_flags="${add_dir_flags} --add-dir ${dir}"
  done < <(python3 "$CONFIG" get-add-dirs "$agent")

  # Kill existing window if present
  if tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$agent"; then
    tmux kill-window -t "$TMUX_SESSION:$agent"
  fi

  local cmd="cd ${ROOT_DIR}/agents/${agent} && claude --dangerously-skip-permissions ${agent_flag}${add_dir_flags}"
  if [[ -n "$sid" ]]; then
    cmd="${cmd} --resume ${sid}"
  fi

  tmux new-window -t "$TMUX_SESSION" -n "$agent"
  tmux send-keys -t "$TMUX_SESSION:$agent" "$cmd" Enter
  echo "  Started: $agent"
}

capture_new_sessions() {
  if [[ ${#AGENTS_NEEDING_SESSION[@]} -eq 0 ]]; then
    return
  fi

  echo "=== Capturing session IDs (waiting 15s for Claude Code startup) ==="
  sleep 15

  for agent in "${AGENTS_NEEDING_SESSION[@]}"; do
    local new_sid
    new_sid="$(python3 "$CONFIG" detect-session "$agent")"
    if [[ -n "$new_sid" ]]; then
      python3 "$CONFIG" set-session "$agent" "$new_sid"
      echo "  ${agent}: ${new_sid}"
    else
      echo "  ${agent}: (no session found yet)"
    fi
  done
}

cleanup_init_window() {
  if tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "_init"; then
    tmux kill-window -t "$TMUX_SESSION:_init" 2>/dev/null || true
  fi
}

# --- Main ---

usage() {
  echo "Usage: $0 [agent|--workers|--all|--daemon|--stop-daemon]"
  echo ""
  echo "  (no args)       Restart all agents (including admin) + ensure daemon"
  echo "  --workers       Restart all except admin"
  echo "  <name>          Restart a single agent (${ALL_AGENTS})"
  echo "  --daemon        Restart the MCP daemon only"
  echo "  --stop-daemon   Stop the MCP daemon"
}

# Auto-generate workspaces (.mcp.json, skill symlinks, team-roster)
python3 "${ROOT_DIR}/setup-agents.py"

case "${1:-__all__}" in
  --daemon)
    echo "=== Restarting daemon ==="
    stop_daemon
    start_daemon
    ;;
  --stop-daemon)
    echo "=== Stopping daemon ==="
    stop_daemon
    ;;
  --workers)
    echo "=== Ensuring daemon ==="
    start_daemon
    echo "=== Restarting workers ==="
    ensure_session
    for agent in $WORKERS; do
      start_agent "$agent"
    done
    cleanup_init_window
    capture_new_sessions
    tmux select-window -t "$TMUX_SESSION:$(tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' | head -1)"
    ;;
  --all|__all__)
    echo "=== Ensuring daemon ==="
    start_daemon
    echo "=== Restarting all agents ==="
    ensure_session
    for agent in $ALL_AGENTS; do
      start_agent "$agent"
    done
    cleanup_init_window
    capture_new_sessions
    tmux select-window -t "$TMUX_SESSION:$(tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' | head -1)"
    ;;
  --help|-h)
    usage
    exit 0
    ;;
  *)
    agent="$1"
    if echo "$ALL_AGENTS" | grep -qw "$agent"; then
      echo "=== Ensuring daemon ==="
      start_daemon
      echo "=== Restarting $agent ==="
      ensure_session
      start_agent "$agent"
      capture_new_sessions
    else
      echo "Unknown agent: $agent"
      usage
      exit 1
    fi
    ;;
esac

echo ""
# Print Web UI URL if daemon is running
DAEMON_PORT="$(get_daemon_port)"
DAEMON_HOST="$(get_daemon_host)"
if [[ -n "$DAEMON_PORT" ]] && daemon_is_running; then
  echo "  Web UI:  http://${DAEMON_HOST}:${DAEMON_PORT}/"
fi
echo "  tmux attach -t $TMUX_SESSION"
echo ""
echo "Switch tabs:  Ctrl-b n / Ctrl-b p"
echo "Detach:       Ctrl-b d"
