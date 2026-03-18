#!/usr/bin/env bash
# Agent Hub Cloud — Backup Script
#
# Backs up SQLite database and instance configs.
# Usage: ./scripts/backup.sh [backup_dir] [retention_days]

set -euo pipefail

BACKUP_DIR="${1:-/var/backups/aghub}"
RETENTION_DAYS="${2:-30}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_PATH="${MGMT_DB_PATH:-management.db}"
INSTANCES_DIR="${MGMT_INSTANCES_DIR:-/var/lib/aghub/instances}"

mkdir -p "$BACKUP_DIR"

echo "[backup] Starting backup at $TIMESTAMP"

# Backup SQLite database (online backup using .backup command)
if [ -f "$DB_PATH" ]; then
    BACKUP_FILE="$BACKUP_DIR/management_${TIMESTAMP}.db"
    sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
    gzip "$BACKUP_FILE"
    echo "[backup] Database backed up: ${BACKUP_FILE}.gz"
else
    echo "[backup] Warning: Database not found at $DB_PATH"
fi

# Backup instance configs (agents.yaml, .env — not Docker volumes)
if [ -d "$INSTANCES_DIR" ]; then
    CONFIGS_FILE="$BACKUP_DIR/instances_${TIMESTAMP}.tar.gz"
    tar czf "$CONFIGS_FILE" -C "$INSTANCES_DIR" \
        --include='*/agents.yaml' \
        --include='*/.env' \
        --include='*/docker-compose.yml' \
        . 2>/dev/null || true
    echo "[backup] Instance configs backed up: $CONFIGS_FILE"
fi

# Cleanup old backups
if [ "$RETENTION_DAYS" -gt 0 ]; then
    find "$BACKUP_DIR" -name "*.gz" -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true
    echo "[backup] Cleaned up backups older than $RETENTION_DAYS days"
fi

echo "[backup] Done"
