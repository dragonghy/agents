#!/bin/bash
set -euo pipefail

# Phase 5a (2026-05-03): this script used to spawn 18 v1 agent tmux windows
# (admin, dev-alex, qa-lucy, ...) via setup-agents.py + tmux send-keys. The
# v2 ephemeral-agent + named-tmux-window model has been retired. Sessions are
# now spawned inside the daemon process by the orchestration v1 runtime; no
# external tmux windows are involved.
#
# Surviving responsibilities of this script:
#   --daemon        restart the agents-mcp daemon (HTTP + MCP SSE on :8765)
#   --telegram-bot  restart the Telegram transport bridge
#
# Everything else (legacy v1 agent windows, --default, --legacy, --all,
# setup-agents.py invocation) was deleted because it has no caller in the
# new model.

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load environment variables from .env (for credentials and paths).
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

# Use agent-config.py so daemon host/port match agents.yaml (.env-aware).
CONFIG="${ROOT_DIR}/agent-config.py"

DAEMON_LOG="${ROOT_DIR}/.daemon.log"
DAEMON_PID_FILE="${ROOT_DIR}/.daemon.pid"

TELEGRAM_BOT_DIR="${ROOT_DIR}/services/telegram-bot"
TELEGRAM_BOT_LOG="${ROOT_DIR}/.telegram-bot.log"
TELEGRAM_BOT_PID_FILE="${ROOT_DIR}/.telegram-bot.pid"

# --- Daemon ---

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
    echo "  Daemon already running on ${host}:${port}"
    return 0
  fi

  # Rotate log: keep previous crash log for diagnosis.
  if [[ -f "$DAEMON_LOG" ]] && [[ -s "$DAEMON_LOG" ]]; then
    mv "$DAEMON_LOG" "${DAEMON_LOG}.prev"
  fi

  echo "  Starting daemon on ${host}:${port} (background, log: ${DAEMON_LOG})..."
  AGENTS_CONFIG_PATH="${ROOT_DIR}/agents.yaml" \
    nohup uv run --directory "${ROOT_DIR}/services/agents-mcp" \
    agents-mcp --daemon --host "$host" --port "$port" \
    >> "$DAEMON_LOG" 2>&1 &
  echo "$!" > "$DAEMON_PID_FILE"

  # Wait for daemon to be ready (up to 15 seconds).
  local tries=0
  while ! daemon_is_running; do
    tries=$((tries + 1))
    if [[ $tries -ge 30 ]]; then
      echo "  ERROR: Daemon failed to start. Check ${DAEMON_LOG}"
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

  local pids
  pids="$(lsof -t -i ":${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill 2>/dev/null || true
    echo "  Daemon stopped"
  fi
  rm -f "$DAEMON_PID_FILE"
}

# --- Telegram bot ---

telegram_bot_pgrep_pid() {
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
    echo "  Telegram bot already running (pid: $(telegram_bot_pid))"
    return 0
  fi

  if [[ -f "$TELEGRAM_BOT_LOG" ]] && [[ -s "$TELEGRAM_BOT_LOG" ]]; then
    mv "$TELEGRAM_BOT_LOG" "${TELEGRAM_BOT_LOG}.prev"
  fi

  echo "  Starting telegram-bot (background, log: ${TELEGRAM_BOT_LOG})..."
  nohup uv run --directory "$TELEGRAM_BOT_DIR" python bot.py \
    >> "$TELEGRAM_BOT_LOG" 2>&1 &
  echo "$!" > "$TELEGRAM_BOT_PID_FILE"

  # uv/python may take a few seconds to appear in the process table.
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
  echo "  ERROR: Telegram bot failed to start. Check ${TELEGRAM_BOT_LOG}"
  rm -f "$TELEGRAM_BOT_PID_FILE"
  return 1
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

# --- Main ---

usage() {
  cat <<EOF
Usage: $0 <command>

In the orchestration v1 model, agent sessions live inside the daemon
process — they are not external tmux windows. This script only manages
the two long-running services (daemon + Telegram bridge).

Commands:
  --daemon         Restart the MCP daemon
  --stop-daemon    Stop the MCP daemon
  --telegram       Restart the Telegram bot transport
  --stop-telegram  Stop the Telegram bot transport
  --help, -h       Show this message
EOF
}

case "${1:-}" in
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
  --help|-h|"")
    usage
    [[ -z "${1:-}" ]] && exit 1 || exit 0
    ;;
  *)
    echo "Unknown command: $1"
    usage
    exit 1
    ;;
esac

echo ""
DAEMON_PORT="$(get_daemon_port 2>/dev/null || true)"
DAEMON_HOST="$(get_daemon_host 2>/dev/null || true)"
if [[ -n "$DAEMON_PORT" ]] && daemon_is_running; then
  echo "  Web UI:  http://${DAEMON_HOST}:${DAEMON_PORT}/"
fi
if telegram_bot_is_running; then
  echo "  Telegram bot: pid $(telegram_bot_pid)  log: ${TELEGRAM_BOT_LOG}"
fi
