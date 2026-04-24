#!/bin/bash
# install-admin-supervisor.sh — install/uninstall the admin supervisor
# launchd job.
#
# Usage:
#   ./install-admin-supervisor.sh              # install + load
#   ./install-admin-supervisor.sh --uninstall  # unload + remove
#   ./install-admin-supervisor.sh --status     # show launchctl status

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.agents.admin.supervisor"
PLIST_SRC="${ROOT_DIR}/launchagents/${LABEL}.plist"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

case "${1:-install}" in
  install|"")
    if [[ ! -f "$PLIST_SRC" ]]; then
      echo "ERROR: plist source not found: $PLIST_SRC" >&2
      exit 1
    fi
    if [[ ! -x "${ROOT_DIR}/admin-supervisor.sh" ]]; then
      echo "Making admin-supervisor.sh executable..."
      chmod +x "${ROOT_DIR}/admin-supervisor.sh"
    fi

    # Unload any previous version so launchctl picks up edits.
    if launchctl list "$LABEL" >/dev/null 2>&1; then
      echo "Unloading existing $LABEL..."
      launchctl unload "$PLIST_DEST" 2>/dev/null || true
    fi

    echo "Copying plist to $PLIST_DEST..."
    cp "$PLIST_SRC" "$PLIST_DEST"

    echo "Loading $LABEL..."
    launchctl load "$PLIST_DEST"

    echo ""
    echo "Installed. Status:"
    launchctl list "$LABEL" 2>/dev/null || echo "  (not yet visible — retry in a few seconds)"
    echo ""
    echo "Logs:"
    echo "  supervisor: ${ROOT_DIR}/.admin-supervisor.log"
    echo "  unified:    ${ROOT_DIR}/.daemon.log  (lines prefixed 'ADMIN-SUPERVISOR:')"
    ;;

  --uninstall|uninstall)
    if [[ -f "$PLIST_DEST" ]]; then
      echo "Unloading $LABEL..."
      launchctl unload "$PLIST_DEST" 2>/dev/null || true
      echo "Removing $PLIST_DEST..."
      rm -f "$PLIST_DEST"
      echo "Uninstalled."
    else
      echo "Not installed (no plist at $PLIST_DEST)."
    fi
    ;;

  --status|status)
    echo "Plist source:  $PLIST_SRC"
    echo "Plist installed: $([ -f "$PLIST_DEST" ] && echo yes || echo no)"
    if launchctl list "$LABEL" >/dev/null 2>&1; then
      echo "launchctl status:"
      launchctl list "$LABEL"
    else
      echo "launchctl: not loaded"
    fi
    echo ""
    if [[ -f "${ROOT_DIR}/.admin-supervisor.log" ]]; then
      echo "Last 10 supervisor log lines:"
      tail -10 "${ROOT_DIR}/.admin-supervisor.log"
    fi
    ;;

  --help|-h|help)
    sed -n '2,10p' "$0"
    ;;

  *)
    echo "Unknown command: $1" >&2
    sed -n '2,10p' "$0" >&2
    exit 1
    ;;
esac
