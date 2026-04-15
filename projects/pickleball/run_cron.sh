#!/bin/bash
# Cron wrapper for daily_check.py.
# - Sets a sane PATH (cron's default PATH is minimal).
# - Redirects output to a dated log file under logs/.
# - Returns the script's exit code so cron failure notifications work.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

mkdir -p "$HERE/logs"
LOG="$HERE/logs/cron-$(date +%Y-%m-%d).log"

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') run_cron.sh starting ==="
  /opt/homebrew/bin/python3 "$HERE/daily_check.py"
  rc=$?
  echo "=== exit $rc ==="
  exit $rc
} >>"$LOG" 2>&1
