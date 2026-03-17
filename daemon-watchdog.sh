#!/bin/bash
# Daemon watchdog: checks if daemon is alive, restarts if not.
# Designed to be called by launchd every 60 seconds.
#
# Install:
#   cp agents-mcp-daemon.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/agents-mcp-daemon.plist

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON_LOG="${ROOT_DIR}/.daemon.log"
DAEMON_PORT=8765

# Load environment
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

# Check if something is listening on the daemon port
if lsof -i ":${DAEMON_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  # Port is in use — verify it's our daemon via lightweight health endpoint.
  # Use /api/v1/health (fast, no external calls) instead of /api/v1/agents (slow).
  if curl -sf -m 10 "http://127.0.0.1:${DAEMON_PORT}/api/v1/health" >/dev/null 2>&1; then
    exit 0  # Our daemon is healthy
  fi

  # Health check failed — check if the process is agents-mcp (ours but unhealthy)
  # vs a completely different process (rogue).
  rogue_pid="$(lsof -t -i ":${DAEMON_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$rogue_pid" ]]; then
    rogue_cmd="$(ps -p "$rogue_pid" -o command= 2>/dev/null || echo unknown)"
    if [[ "$rogue_cmd" == *"agents-mcp"* ]]; then
      # It's our daemon but health check failed — could be temporarily busy.
      # Give it one more chance with a longer timeout before killing.
      sleep 5
      if curl -sf -m 15 "http://127.0.0.1:${DAEMON_PORT}/api/v1/health" >/dev/null 2>&1; then
        exit 0  # Recovered
      fi
      echo "$(date '+%Y-%m-%d %H:%M:%S') WATCHDOG: Our daemon (pid=${rogue_pid}) failed health check twice. Restarting..." >> "$DAEMON_LOG"
    else
      echo "$(date '+%Y-%m-%d %H:%M:%S') WATCHDOG: Port ${DAEMON_PORT} occupied by rogue process (pid=${rogue_pid}, cmd=${rogue_cmd}). Killing..." >> "$DAEMON_LOG"
    fi
    kill "$rogue_pid" 2>/dev/null || true
    sleep 3
  fi
fi

# Daemon is down — log and restart
echo "$(date '+%Y-%m-%d %H:%M:%S') WATCHDOG: Daemon not running, restarting..." >> "$DAEMON_LOG"

# Rotate log if > 10MB
LOG_SIZE=$(stat -f%z "$DAEMON_LOG" 2>/dev/null || echo 0)
if [[ "$LOG_SIZE" -gt 10485760 ]]; then
  mv "$DAEMON_LOG" "${DAEMON_LOG}.prev"
  echo "$(date '+%Y-%m-%d %H:%M:%S') WATCHDOG: Log rotated (was ${LOG_SIZE} bytes)" >> "$DAEMON_LOG"
fi

# Kill any zombie processes still holding the port (CLOSE_WAIT, TIME_WAIT, etc.)
stale_pids="$(lsof -t -i ":${DAEMON_PORT}" 2>/dev/null || true)"
if [[ -n "$stale_pids" ]]; then
  echo "$stale_pids" | xargs kill 2>/dev/null || true
  echo "$(date '+%Y-%m-%d %H:%M:%S') WATCHDOG: Killed stale processes on port ${DAEMON_PORT}: ${stale_pids}" >> "$DAEMON_LOG"
  sleep 3  # Wait for port to be fully released
fi

# Wait until port is truly free (up to 15 seconds)
for i in $(seq 1 15); do
  if ! lsof -i ":${DAEMON_PORT}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

AGENTS_CONFIG_PATH="${ROOT_DIR}/agents.yaml" \
  nohup /opt/homebrew/bin/uv run --directory "${ROOT_DIR}/services/agents-mcp" \
  agents-mcp --daemon --host 127.0.0.1 --port "$DAEMON_PORT" \
  >> "$DAEMON_LOG" 2>&1 &

DAEMON_PID=$!

# Wait for startup (up to 15 seconds)
for i in $(seq 1 15); do
  if lsof -i ":${DAEMON_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') WATCHDOG: Daemon restarted successfully (pid: ${DAEMON_PID})" >> "$DAEMON_LOG"
    exit 0
  fi
  sleep 1
done

echo "$(date '+%Y-%m-%d %H:%M:%S') WATCHDOG: Daemon restart FAILED after 15s" >> "$DAEMON_LOG"
