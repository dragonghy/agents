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
# Set SKIP_DAEMON=1 to skip daemon start/stop (e.g., in Docker agent mode
# where the daemon runs in a separate container).

DAEMON_LOG="${ROOT_DIR}/.daemon.log"
DAEMON_PID_FILE="${ROOT_DIR}/.daemon.pid"

TELEGRAM_BOT_DIR="${ROOT_DIR}/services/telegram-bot"
TELEGRAM_BOT_LOG="${ROOT_DIR}/.telegram-bot.log"
TELEGRAM_BOT_PID_FILE="${ROOT_DIR}/.telegram-bot.pid"

# Use agent-config.py so daemon host/port match setup-agents.py (resolve_env_vars, .env).
get_daemon_port() {
  python3 "$CONFIG" daemon-port
}

get_daemon_host() {
  python3 "$CONFIG" daemon-host
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

  # Rotate log: keep previous crash log for diagnosis
  if [[ -f "$DAEMON_LOG" ]] && [[ -s "$DAEMON_LOG" ]]; then
    mv "$DAEMON_LOG" "${DAEMON_LOG}.prev"
  fi

  echo "  Starting daemon on ${host}:${port}..."
  AGENTS_CONFIG_PATH="${ROOT_DIR}/agents.yaml" \
    nohup uv run --directory "${ROOT_DIR}/services/agents-mcp" \
    agents-mcp --daemon --host "$host" --port "$port" \
    >> "$DAEMON_LOG" 2>&1 &
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

# Start daemon when launching agents; never abort the script on failure (set -e).
# Port conflicts are common; users still expect tmux windows to come up.
ensure_daemon_for_agents() {
  if [[ "${SKIP_DAEMON:-}" == "1" ]]; then
    return 0
  fi
  if start_daemon; then
    return 0
  fi
  local dp
  dp="$(get_daemon_port)"
  echo ""
  echo "  WARNING: MCP daemon did not start. Continuing with tmux agents anyway."
  echo "  Check ${DAEMON_LOG} — often: port in use (see agents.yaml daemon.port)."
  if [[ -n "$dp" ]]; then
    echo "  Diagnose:  lsof -nP -iTCP:${dp} -sTCP:LISTEN"
  fi
  echo "  Or skip daemon:  SKIP_DAEMON=1 $0"
  echo ""
}

# --- Telegram bot management ---
# v2: Telegram bot is a long-running transport bridge (no AI). It polls the
# daemon's outbox and relays Human <-> Agent messages. It runs as a plain
# background process (not in tmux).

telegram_bot_pid() {
  if [[ -f "$TELEGRAM_BOT_PID_FILE" ]]; then
    local pid
    pid="$(cat "$TELEGRAM_BOT_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return 0
    fi
  fi
  return 1
}

telegram_bot_is_running() {
  telegram_bot_pid >/dev/null 2>&1
}

start_telegram_bot() {
  if [[ ! -f "${TELEGRAM_BOT_DIR}/bot.py" ]]; then
    echo "  Telegram bot: source not found at ${TELEGRAM_BOT_DIR}, skipping"
    return 0
  fi

  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    echo "  Telegram bot: TELEGRAM_BOT_TOKEN not set in .env, skipping"
    return 0
  fi

  if telegram_bot_is_running; then
    echo "  Telegram bot already running (pid: $(telegram_bot_pid))"
    return 0
  fi

  # Rotate log
  if [[ -f "$TELEGRAM_BOT_LOG" ]] && [[ -s "$TELEGRAM_BOT_LOG" ]]; then
    mv "$TELEGRAM_BOT_LOG" "${TELEGRAM_BOT_LOG}.prev"
  fi

  echo "  Starting telegram-bot..."
  nohup uv run --directory "$TELEGRAM_BOT_DIR" python bot.py \
    >> "$TELEGRAM_BOT_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$TELEGRAM_BOT_PID_FILE"

  # Give it a moment to actually start, then verify it didn't immediately die
  sleep 1
  if kill -0 "$pid" 2>/dev/null; then
    echo "  Telegram bot started (pid: $pid)"
  else
    echo "  ERROR: Telegram bot failed to start. Check ${TELEGRAM_BOT_LOG}"
    rm -f "$TELEGRAM_BOT_PID_FILE"
    return 1
  fi
}

stop_telegram_bot() {
  if ! telegram_bot_is_running; then
    echo "  Telegram bot not running"
    rm -f "$TELEGRAM_BOT_PID_FILE"
    return 0
  fi

  local pid
  pid="$(telegram_bot_pid)"
  kill "$pid" 2>/dev/null || true
  # Wait up to 3s for clean exit
  local waited=0
  while kill -0 "$pid" 2>/dev/null && [[ $waited -lt 3 ]]; do
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$TELEGRAM_BOT_PID_FILE"
  echo "  Telegram bot stopped"
}

# --- Agent management ---

ensure_session() {
  if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TMUX_SESSION" -n "_init"
    tmux set-option -t "$TMUX_SESSION" remain-on-exit on
  fi
}

AGENTS_NEEDING_SESSION=()

# Restart mode: "force" | "skip-busy" | "request-restart"
RESTART_MODE="${RESTART_MODE:-skip-busy}"

is_agent_window_alive() {
  local agent="$1"
  tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$agent"
}

is_agent_busy() {
  # Check if an agent has an in_progress (status=4) ticket via the daemon API
  local agent="$1"
  local port
  port="$(get_daemon_port)"
  if [[ -z "$port" ]] || ! daemon_is_running; then
    return 1  # Can't check, assume not busy
  fi
  local count
  count="$(curl -sf "http://$(get_daemon_host):${port}/api/v1/tickets?assignee=${agent}&status=4" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('total',0))" 2>/dev/null || echo 0)"
  [[ "$count" -gt 0 ]]
}

graceful_stop_agent() {
  # Gracefully stop an agent by sending /exit through tmux
  local agent="$1"
  local timeout="${2:-10}"

  if ! is_agent_window_alive "$agent"; then
    return 0  # Already stopped
  fi

  echo "  Graceful stop: $agent (sending /exit)..."

  # Send /exit command
  tmux send-keys -t "$TMUX_SESSION:$agent" "/exit" Enter

  # Wait for exit (check every second)
  local waited=0
  while is_agent_window_alive "$agent" && [[ $waited -lt $timeout ]]; do
    sleep 1
    waited=$((waited + 1))
    # Check if the pane shows a shell prompt (agent exited, shell returned)
    local pane_content
    pane_content="$(tmux capture-pane -t "$TMUX_SESSION:$agent" -p 2>/dev/null | tail -3 || true)"
    if echo "$pane_content" | grep -qE '^\$|^%|^❯|exited|Goodbye'; then
      break
    fi
  done

  # If still alive after timeout, force kill
  if is_agent_window_alive "$agent"; then
    echo "  Timeout after ${timeout}s, force killing: $agent"
    tmux kill-window -t "$TMUX_SESSION:$agent" 2>/dev/null || true
  else
    echo "  Gracefully stopped: $agent"
  fi
}

stop_agent() {
  # Stop an agent based on the current RESTART_MODE
  local agent="$1"

  if ! is_agent_window_alive "$agent"; then
    return 0  # Not running
  fi

  case "$RESTART_MODE" in
    skip-busy)
      if is_agent_busy "$agent"; then
        echo "  SKIP (busy): $agent — has in-progress tickets"
        return 1  # Signal to caller: don't restart
      fi
      graceful_stop_agent "$agent"
      ;;
    request-restart)
      if is_agent_busy "$agent"; then
        echo "  REQUEST: $agent — sending restart request via MCP"
        local port
        port="$(get_daemon_port)"
        if [[ -n "$port" ]] && daemon_is_running; then
          curl -sf -X POST "http://$(get_daemon_host):${port}/api/v1/agents/${agent}/request-restart" \
            -H 'Content-Type: application/json' -d '{}' >/dev/null 2>&1 || true
        fi
        return 1  # Don't restart now, agent will self-restart
      fi
      graceful_stop_agent "$agent"
      ;;
    force|*)
      graceful_stop_agent "$agent"
      ;;
  esac
}

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

  # Gracefully stop existing agent (respects RESTART_MODE)
  if is_agent_window_alive "$agent"; then
    if ! stop_agent "$agent"; then
      return  # Agent was busy and mode says skip/request
    fi
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

  echo "=== Capturing session IDs (polling up to 60s) ==="
  local remaining=("${AGENTS_NEEDING_SESSION[@]}")
  local max_attempts=12  # 12 × 5s = 60s
  local attempt=0

  while [[ ${#remaining[@]} -gt 0 && $attempt -lt $max_attempts ]]; do
    attempt=$((attempt + 1))
    sleep 5

    local still_missing=()
    for agent in "${remaining[@]}"; do
      local new_sid
      new_sid="$(python3 "$CONFIG" detect-session "$agent")"
      if [[ -n "$new_sid" ]]; then
        python3 "$CONFIG" set-session "$agent" "$new_sid"
        echo "  ${agent}: ${new_sid} (after ${attempt}×5s)"
      else
        still_missing+=("$agent")
      fi
    done
    remaining=("${still_missing[@]}")

    if [[ ${#remaining[@]} -gt 0 ]]; then
      echo "  ... waiting (${#remaining[@]} agents remaining, attempt ${attempt}/${max_attempts})"
    fi
  done

  # Report any agents that still couldn't be captured
  for agent in "${remaining[@]}"; do
    echo "  ${agent}: (no session found after 60s — will capture on next restart)"
  done
}

cleanup_init_window() {
  if tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "_init"; then
    tmux kill-window -t "$TMUX_SESSION:_init" 2>/dev/null || true
  fi
}

# --- Main ---

usage() {
  cat <<EOF
Usage: $0 [command] [restart-mode]

v2 is task-driven: ephemeral agent sessions are spawned by the daemon's
session_manager when tasks arrive. This script no longer launches the 18
persistent v1 agent windows by default.

Commands:
  (no args)           Ensure daemon + telegram-bot are running (v2 default)
  --daemon            Restart the MCP daemon only
  --stop-daemon       Stop the MCP daemon
  --telegram          Restart the telegram-bot transport service
  --stop-telegram     Stop the telegram-bot transport service
  --stop-all          Stop daemon + telegram-bot + all legacy v1 agents
  <name>              Restart a single v1 agent (${ALL_AGENTS})
  --legacy            Legacy v1 mode: restart daemon + ALL persistent v1 agents
  --legacy-workers    Legacy v1 mode: restart all v1 agents except admin

Restart modes (apply to agent restarts, default: --skip-busy):
  --skip-busy         Skip agents with in-progress tickets
  --force             Graceful /exit for all agents (wait, then force kill)
  --request-restart   Ask busy agents to self-restart via MCP
EOF
}

# Parse restart mode flags from any position in args
POSITIONAL_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --skip-busy)      RESTART_MODE="skip-busy" ;;
    --force)          RESTART_MODE="force" ;;
    --request-restart) RESTART_MODE="request-restart" ;;
    *)                POSITIONAL_ARGS+=("$arg") ;;
  esac
done
set -- "${POSITIONAL_ARGS[@]:-}"

# Auto-generate workspaces (.mcp.json, skill symlinks, team-roster)
python3 "${ROOT_DIR}/setup-agents.py"

echo "  Restart mode: ${RESTART_MODE}"

case "${1:-__default__}" in
  --daemon)
    echo "=== Restarting daemon ==="
    stop_daemon
    start_daemon
    ;;
  --stop-daemon)
    echo "=== Stopping daemon ==="
    stop_daemon
    ;;
  --telegram|--telegram-bot)
    echo "=== Restarting telegram-bot ==="
    stop_telegram_bot
    start_telegram_bot
    ;;
  --stop-telegram|--stop-telegram-bot)
    echo "=== Stopping telegram-bot ==="
    stop_telegram_bot
    ;;
  --stop-all)
    echo "=== Stopping all services ==="
    # Stop legacy v1 agent windows if any
    if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
      for agent in $ALL_AGENTS; do
        if is_agent_window_alive "$agent"; then
          graceful_stop_agent "$agent" 5
        fi
      done
    fi
    stop_telegram_bot
    stop_daemon
    ;;
  --default|__default__)
    # v2 default: only ensure daemon + telegram-bot. No v1 agent windows.
    echo "=== v2 default: ensure daemon + telegram-bot ==="
    echo "    (v2 agents are ephemeral — the daemon spawns them per task.)"
    echo "    (For legacy v1 behavior, use --legacy.)"
    if [[ "${SKIP_DAEMON:-}" != "1" ]]; then
      ensure_daemon_for_agents
    fi
    start_telegram_bot || true
    ;;
  --legacy|--all)
    # Legacy v1: restart daemon + ALL persistent v1 agent windows.
    # Kept for migration-period fallback; not the recommended path in v2.
    if [[ "${SKIP_DAEMON:-}" != "1" ]]; then
      echo "=== Ensuring daemon ==="
      ensure_daemon_for_agents
    fi
    echo "=== [legacy] Restarting all v1 agents ==="
    ensure_session
    for agent in $ALL_AGENTS; do
      start_agent "$agent"
    done
    cleanup_init_window
    capture_new_sessions
    start_telegram_bot || true
    tmux select-window -t "$TMUX_SESSION:$(tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' | head -1)"
    ;;
  --legacy-workers|--workers)
    if [[ "${SKIP_DAEMON:-}" != "1" ]]; then
      echo "=== Ensuring daemon ==="
      ensure_daemon_for_agents
    fi
    echo "=== [legacy] Restarting v1 workers ==="
    ensure_session
    for agent in $WORKERS; do
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
      if [[ "${SKIP_DAEMON:-}" != "1" ]]; then
        echo "=== Ensuring daemon ==="
        ensure_daemon_for_agents
      fi
      echo "=== Restarting $agent ==="
      ensure_session
      start_agent "$agent"
      capture_new_sessions
    else
      echo "Unknown command or agent: $agent"
      usage
      exit 1
    fi
    ;;
esac

echo ""
# Print Web UI URL if daemon is running (skip in Docker agent mode)
if [[ "${SKIP_DAEMON:-}" != "1" ]]; then
  DAEMON_PORT="$(get_daemon_port)"
  DAEMON_HOST="$(get_daemon_host)"
  if [[ -n "$DAEMON_PORT" ]] && daemon_is_running; then
    echo "  Web UI:  http://${DAEMON_HOST}:${DAEMON_PORT}/"
  fi
fi
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  echo "  tmux attach -t $TMUX_SESSION"
  echo ""
  echo "Switch tabs:  Ctrl-b n / Ctrl-b p"
  echo "Detach:       Ctrl-b d"
fi
if telegram_bot_is_running; then
  echo "  Telegram bot: pid $(telegram_bot_pid)  log: ${TELEGRAM_BOT_LOG}"
fi
