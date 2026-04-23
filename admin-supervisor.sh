#!/bin/bash
# admin-supervisor.sh — Detect and recover stalled admin tmux window.
#
# Designed to be invoked by launchd every 60 seconds via
# ~/Library/LaunchAgents/com.agents.admin.supervisor.plist.
#
# Detection logic (all must hold for restart):
#   1. tmux session "agents" exists
#   2. window "admin" exists inside it
#   3. #{window_activity} is > STALL_THRESHOLD_SECS stale
#   4. admin has pending work: unread P2P inbox > 0 OR morning-brief
#      window is open and no brief has been sent today.
#
# If only (1,2,3) hold but there is no pending work, we consider admin
# legitimately idle and do NOT restart.
#
# Recovery:
#   - Rate-limit via .admin-supervisor.state (1h cooldown)
#   - Skip entirely if daemon is down (that's a different watchdog's job)
#   - Run ./restart_all_agents.sh admin --force
#   - Notify Human via POST /api/v1/human/send
#   - Log to both .daemon.log (unified timeline) and stdout (plist log)
#
# Exit codes: always 0 (launchd StartInterval jobs should not accumulate
# failure counters; we log and move on).

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON_LOG="${ROOT_DIR}/.daemon.log"
STATE_FILE="${ROOT_DIR}/.admin-supervisor.state"
BRIEF_LOG_DIR="${ROOT_DIR}/templates/shared/skills/executive-brief/log"

# Tunables (override via env for testing)
STALL_THRESHOLD_SECS="${STALL_THRESHOLD_SECS:-14400}"   # 4h
COOLDOWN_SECS="${COOLDOWN_SECS:-3600}"                   # 1h between restarts
TMUX_SESSION="${TMUX_SESSION:-agents}"
ADMIN_WINDOW="${ADMIN_WINDOW:-admin}"
DAEMON_PORT="${DAEMON_PORT:-8765}"
DAEMON_HOST="${DAEMON_HOST:-127.0.0.1}"
DRY_RUN="${DRY_RUN:-0}"    # if 1, log decisions but do not actually restart or notify

# Load .env if present (picks up any overrides)
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

now_epoch() { date +%s; }

ts_prefix() { date '+%Y-%m-%d %H:%M:%S'; }

log() {
  # Append to daemon log AND echo to stdout (plist captures stdout).
  local line="$(ts_prefix) ADMIN-SUPERVISOR: $*"
  echo "$line"
  echo "$line" >> "$DAEMON_LOG" 2>/dev/null || true
}

# --- State file helpers ---

read_last_restart() {
  if [[ -f "$STATE_FILE" ]]; then
    local v
    v="$(cat "$STATE_FILE" 2>/dev/null | tr -d '[:space:]')"
    [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 0
  else
    echo 0
  fi
}

# --- Probes ---

daemon_alive() {
  curl -sf -m 5 "http://${DAEMON_HOST}:${DAEMON_PORT}/api/v1/health" >/dev/null 2>&1
}

tmux_session_exists() {
  tmux has-session -t "$TMUX_SESSION" 2>/dev/null
}

admin_window_exists() {
  tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null \
    | grep -qx "$ADMIN_WINDOW"
}

admin_window_activity() {
  # Returns last-activity unix epoch, or empty string on failure.
  tmux display-message -t "${TMUX_SESSION}:${ADMIN_WINDOW}" \
    -p '#{window_activity}' 2>/dev/null | tr -d '[:space:]'
}

admin_unread_inbox_count() {
  # Returns unread count as integer; empty string if the daemon is
  # unreachable or the endpoint response is malformed.
  local json count
  json="$(curl -sf -m 5 \
    "http://${DAEMON_HOST}:${DAEMON_PORT}/api/v1/messages/inbox/admin?unread_only=true&limit=1" \
    2>/dev/null)" || return 1
  count="$(printf '%s' "$json" \
    | python3 -c 'import sys,json;
try:
    d=json.load(sys.stdin); print(int(d.get("unread_count", 0)))
except Exception:
    pass' 2>/dev/null)"
  [[ -n "$count" ]] && echo "$count"
}

morning_brief_pending() {
  # Returns 0 (yes, pending) / 1 (no, not pending or cannot determine).
  #
  # Signal: brief runs at 07:00 local daily. If current local time is
  # between 07:00 and 10:00 AND no log file exists for today under
  # executive-brief/log/, treat as pending.
  local hour today brief_file
  hour="$(date +%H)"
  today="$(date +%Y-%m-%d)"
  # Strip leading zero so we can compare numerically
  hour="$((10#$hour))"

  if (( hour < 7 || hour > 10 )); then
    return 1  # outside brief window — not pending
  fi

  brief_file="${BRIEF_LOG_DIR}/${today}.md"
  [[ -f "$brief_file" ]] && return 1  # brief already written today
  return 0
}

# --- Recovery actions ---

notify_human() {
  local text="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY_RUN: would notify Human: ${text}"
    return 0
  fi
  # Best-effort; if the daemon is down the notification is lost (the
  # .daemon.log line is forensic backup).
  local payload
  payload="$(python3 -c "
import json, sys
print(json.dumps({
    'body': sys.argv[1],
    'channel': 'system',
    'source_agent_type': 'admin-supervisor',
}))
" "$text")"
  curl -sf -m 5 -X POST \
    "http://${DAEMON_HOST}:${DAEMON_PORT}/api/v1/human/send" \
    -H 'Content-Type: application/json' \
    -d "$payload" >/dev/null 2>&1 || true
}

restart_admin() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY_RUN: would exec './restart_all_agents.sh admin --force'"
    return 0
  fi
  # Use the existing restart path. --force bypasses busy check, which is
  # what we want for a stalled admin (it IS busy-in-status but
  # unresponsive).
  cd "$ROOT_DIR" || return 1
  RESTART_MODE=force ./restart_all_agents.sh admin --force \
    >> "$DAEMON_LOG" 2>&1
}

write_last_restart() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY_RUN: would write last-restart=$1 to ${STATE_FILE}"
    return 0
  fi
  echo "$1" > "$STATE_FILE"
}

# --- Main ---

main() {
  local now; now="$(now_epoch)"

  # Step 1: tmux session itself must be alive. If not, restart.
  if ! tmux_session_exists; then
    log "tmux session '${TMUX_SESSION}' missing — restarting admin"
    restart_admin
    write_last_restart "$now"
    notify_human "⚠️ Admin auto-restarted — tmux session '${TMUX_SESSION}' was missing"
    exit 0
  fi

  # Step 2: admin window must exist inside session.
  if ! admin_window_exists; then
    log "admin window missing in session '${TMUX_SESSION}' — restarting"
    restart_admin
    write_last_restart "$now"
    notify_human "⚠️ Admin auto-restarted — tmux window was missing"
    exit 0
  fi

  # Step 3: compute stall seconds.
  local activity stall
  activity="$(admin_window_activity)"
  if [[ -z "$activity" || ! "$activity" =~ ^[0-9]+$ ]]; then
    log "could not read window_activity for admin (tmux query failed) — skipping this tick"
    exit 0
  fi
  stall=$(( now - activity ))

  if (( stall <= STALL_THRESHOLD_SECS )); then
    # Healthy. Exit silently (no log spam).
    exit 0
  fi

  # Step 4: pending-work AND-clause.
  # On query failure we default to "pending" — err toward recovery.
  local unread pending_brief work_hint
  unread="$(admin_unread_inbox_count)"
  if [[ -z "$unread" ]]; then
    unread="?"
    # Inbox query failed. Usually means daemon is down. Bail on restart
    # (daemon-watchdog will handle that) BUT log the observation.
    log "stall=${stall}s but inbox query failed (daemon down?) — deferring to daemon-watchdog"
    exit 0
  fi

  if morning_brief_pending; then
    pending_brief="yes"
  else
    pending_brief="no"
  fi

  if (( unread == 0 )) && [[ "$pending_brief" == "no" ]]; then
    # Legitimately idle; no work waiting. Do not restart.
    log "stall=${stall}s but no pending work (unread=0, brief_pending=no) — admin is idle, not stalled"
    exit 0
  fi

  work_hint="unread=${unread}, brief_pending=${pending_brief}"

  # Step 5: cooldown + daemon-alive fences before restarting.
  local last_restart since_last
  last_restart="$(read_last_restart)"
  since_last=$(( now - last_restart ))
  if (( last_restart > 0 && since_last < COOLDOWN_SECS )); then
    log "stall=${stall}s (${work_hint}) — SUPPRESSED, last restart was ${since_last}s ago (<${COOLDOWN_SECS}s cooldown)"
    exit 0
  fi

  if ! daemon_alive; then
    log "stall=${stall}s (${work_hint}) — SKIPPED, daemon is down; admin restart without daemon is pointless"
    exit 0
  fi

  # Step 6: fire.
  local stall_hours; stall_hours=$(( stall / 3600 ))
  log "stall=${stall}s (~${stall_hours}h), ${work_hint} — RESTARTING admin"
  restart_admin
  write_last_restart "$now"
  notify_human "⚠️ Admin auto-restarted — stalled ~${stall_hours}h (${work_hint})"
  log "admin restart dispatched; next check in 60s"
}

main
