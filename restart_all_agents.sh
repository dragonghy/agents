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

# Tmux window names for long-running services (not Claude agent tabs).
TMUX_WIN_MCP_DAEMON="mcp-daemon"
TMUX_WIN_TELEGRAM="telegram-bot"

services_use_tmux() {
  [[ "${SKIP_SERVICES_TMUX:-}" != "1" ]]
}

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

start_daemon() {
  local port host
  port="$(get_daemon_port)"
  host="$(get_daemon_host)"
  [[ -z "$port" ]] && return 0  # No daemon configured

  if daemon_is_running; then
    if services_use_tmux; then
      ensure_session 2>/dev/null || true
      if tmux has-session -t "$TMUX_SESSION" 2>/dev/null \
        && is_service_window_alive "$TMUX_WIN_MCP_DAEMON"; then
        echo "  Daemon already running on ${host}:${port} (tmux: ${TMUX_SESSION}:${TMUX_WIN_MCP_DAEMON})"
        return 0
      fi
      echo "  Daemon is up but not in tmux; stopping listener to relaunch in ${TMUX_WIN_MCP_DAEMON}..."
      stop_daemon
    else
      echo "  Daemon already running on ${host}:${port}"
      return 0
    fi
  fi

  # Rotate log: keep previous crash log for diagnosis
  if [[ -f "$DAEMON_LOG" ]] && [[ -s "$DAEMON_LOG" ]]; then
    mv "$DAEMON_LOG" "${DAEMON_LOG}.prev"
  fi

  if services_use_tmux; then
    ensure_session
    if is_service_window_alive "$TMUX_WIN_MCP_DAEMON"; then
      tmux kill-window -t "$TMUX_SESSION:$TMUX_WIN_MCP_DAEMON" 2>/dev/null || true
    fi
    echo "  Starting daemon on ${host}:${port} (tmux: ${TMUX_SESSION}:${TMUX_WIN_MCP_DAEMON})..."
    tmux new-window -t "$TMUX_SESSION" -n "$TMUX_WIN_MCP_DAEMON"
    local dcmd="cd \"${ROOT_DIR}\" && AGENTS_CONFIG_PATH=\"${ROOT_DIR}/agents.yaml\" uv run --directory \"${ROOT_DIR}/services/agents-mcp\" agents-mcp --daemon --host \"${host}\" --port \"${port}\" 2>&1 | tee -a \"${DAEMON_LOG}\""
    tmux send-keys -t "$TMUX_SESSION:$TMUX_WIN_MCP_DAEMON" "$dcmd" Enter
  else
    echo "  Starting daemon on ${host}:${port} (background, log: ${DAEMON_LOG})..."
    AGENTS_CONFIG_PATH="${ROOT_DIR}/agents.yaml" \
      nohup uv run --directory "${ROOT_DIR}/services/agents-mcp" \
      agents-mcp --daemon --host "$host" --port "$port" \
      >> "$DAEMON_LOG" 2>&1 &
    echo "$!" > "$DAEMON_PID_FILE"
  fi

  # Wait for daemon to be ready (up to 15 seconds)
  local tries=0
  while ! daemon_is_running; do
    tries=$((tries + 1))
    if [[ $tries -ge 30 ]]; then
      echo "  ERROR: Daemon failed to start. Check ${DAEMON_LOG} or tmux window ${TMUX_WIN_MCP_DAEMON}"
      return 1
    fi
    sleep 0.5
  done
  local listen_pid
  listen_pid="$(lsof -t -i ":${port}" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  if [[ -n "$listen_pid" ]]; then
    echo "$listen_pid" > "$DAEMON_PID_FILE"
  fi
  echo "  Daemon started (pid: ${listen_pid:-?})"
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
  if services_use_tmux && is_service_window_alive "$TMUX_WIN_MCP_DAEMON"; then
    tmux kill-window -t "$TMUX_SESSION:$TMUX_WIN_MCP_DAEMON" 2>/dev/null || true
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
# daemon's outbox and relays Human <-> Agent messages. By default it shares the
# agents tmux session (window telegram-bot); set SKIP_SERVICES_TMUX=1 for nohup.

telegram_bot_pgrep_pid() {
  # uv runs: "uv run --directory .../telegram-bot python bot.py" and a .venv python child.
  # Escape dots in the path so pgrep ERE does not treat them as wildcards.
  local ere_dir p
  ere_dir="${TELEGRAM_BOT_DIR//./\\.}"
  p="$(pgrep -f "uv run --directory ${ere_dir} python bot\\.py" 2>/dev/null | head -1 || true)"
  [[ -n "$p" ]] && echo "$p" && return 0
  p="$(pgrep -f "${ere_dir}/\\.venv/.*/python[^[:space:]]*[[:space:]]+bot\\.py" 2>/dev/null | head -1 || true)"
  [[ -n "$p" ]] && echo "$p" && return 0
  pgrep -f "${ere_dir}/bot\\.py" 2>/dev/null | head -1 || true
}

telegram_bot_pid() {
  if [[ -f "$TELEGRAM_BOT_PID_FILE" ]]; then
    local pid
    pid="$(cat "$TELEGRAM_BOT_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return 0
    fi
  fi
  local pg
  pg="$(telegram_bot_pgrep_pid)"
  if [[ -n "$pg" ]] && kill -0 "$pg" 2>/dev/null; then
    echo "$pg"
    return 0
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
    if services_use_tmux; then
      ensure_session 2>/dev/null || true
      if tmux has-session -t "$TMUX_SESSION" 2>/dev/null \
        && is_service_window_alive "$TMUX_WIN_TELEGRAM"; then
        echo "  Telegram bot already running (pid: $(telegram_bot_pid), tmux: ${TMUX_SESSION}:${TMUX_WIN_TELEGRAM})"
        return 0
      fi
      echo "  Telegram bot is up but not in tmux; stopping to relaunch in ${TMUX_WIN_TELEGRAM}..."
      stop_telegram_bot
    else
      echo "  Telegram bot already running (pid: $(telegram_bot_pid))"
      return 0
    fi
  fi

  # Rotate log
  if [[ -f "$TELEGRAM_BOT_LOG" ]] && [[ -s "$TELEGRAM_BOT_LOG" ]]; then
    mv "$TELEGRAM_BOT_LOG" "${TELEGRAM_BOT_LOG}.prev"
  fi

  if services_use_tmux; then
    ensure_session
    if is_service_window_alive "$TMUX_WIN_TELEGRAM"; then
      tmux kill-window -t "$TMUX_SESSION:$TMUX_WIN_TELEGRAM" 2>/dev/null || true
    fi
    echo "  Starting telegram-bot (tmux: ${TMUX_SESSION}:${TMUX_WIN_TELEGRAM})..."
    tmux new-window -t "$TMUX_SESSION" -n "$TMUX_WIN_TELEGRAM"
    local tcmd="cd \"${ROOT_DIR}\" && uv run --directory \"${TELEGRAM_BOT_DIR}\" python bot.py 2>&1 | tee -a \"${TELEGRAM_BOT_LOG}\""
    tmux send-keys -t "$TMUX_SESSION:$TMUX_WIN_TELEGRAM" "$tcmd" Enter
  else
    echo "  Starting telegram-bot (background, log: ${TELEGRAM_BOT_LOG})..."
    nohup uv run --directory "$TELEGRAM_BOT_DIR" python bot.py \
      >> "$TELEGRAM_BOT_LOG" 2>&1 &
    echo "$!" > "$TELEGRAM_BOT_PID_FILE"
  fi

  # uv/python may take a few seconds to appear in the process table
  local pid="" tries=0
  while [[ $tries -lt 15 ]]; do
    sleep 1
    pid="$(telegram_bot_pgrep_pid)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid" > "$TELEGRAM_BOT_PID_FILE"
      echo "  Telegram bot started (pid: $pid)"
      return 0
    fi
    tries=$((tries + 1))
  done
  echo "  ERROR: Telegram bot failed to start. Check ${TELEGRAM_BOT_LOG} or tmux ${TMUX_WIN_TELEGRAM}"
  rm -f "$TELEGRAM_BOT_PID_FILE"
  return 1
}

stop_telegram_bot() {
  if services_use_tmux && is_service_window_alive "$TMUX_WIN_TELEGRAM"; then
    echo "  Stopping telegram-bot (tmux window)..."
    tmux kill-window -t "$TMUX_SESSION:$TMUX_WIN_TELEGRAM" 2>/dev/null || true
    rm -f "$TELEGRAM_BOT_PID_FILE"
    echo "  Telegram bot stopped"
    return 0
  fi

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

is_service_window_alive() {
  local win="$1"
  tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$win"
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

  # Force-killing the last window in the session exits the tmux server; recreate session before new-window.
  ensure_session
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
  (no args)           v2 default: tmux windows mcp-daemon, telegram-bot, admin + services
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

Environment:
  SKIP_DAEMON=1         Do not start or probe the MCP daemon
  SKIP_ADMIN_TMUX=1     Default command only: skip creating the admin tmux window
  SKIP_SERVICES_TMUX=1  Run MCP daemon + telegram-bot as background processes (no tmux panes)
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
      for svc in "$TMUX_WIN_MCP_DAEMON" "$TMUX_WIN_TELEGRAM"; do
        if is_service_window_alive "$svc"; then
          tmux kill-window -t "$TMUX_SESSION:$svc" 2>/dev/null || true
        fi
      done
    fi
    stop_telegram_bot
    stop_daemon
    ;;
  --default|__default__)
    # v2 default: daemon + telegram-bot + one persistent admin tmux window.
    # Task-driven dev/ops/assistant sessions are still ephemeral (session_manager).
    echo "=== v2 default: daemon + telegram-bot + admin (tmux) ==="
    echo "    (Ephemeral v2 task agents: spawned by the daemon per ticket.)"
    echo "    (All persistent v1 windows:  ./restart_all_agents.sh --legacy)"
    if [[ "${SKIP_DAEMON:-}" != "1" ]]; then
      ensure_daemon_for_agents
    fi
    start_telegram_bot || true
    if [[ "${SKIP_ADMIN_TMUX:-}" != "1" ]] && echo "$ALL_AGENTS" | grep -qw admin; then
      ensure_session
      start_agent admin
      cleanup_init_window
      capture_new_sessions
      if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        tmux select-window -t "$TMUX_SESSION:admin" 2>/dev/null \
          || tmux select-window -t "$TMUX_SESSION:$(tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' | head -1)"
      fi
    fi
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
    start_telegram_bot || true
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
