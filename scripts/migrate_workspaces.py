#!/usr/bin/env python3
"""Migrate `.agents-tasks.db` (and optionally `.agents-mcp.db`) to add the
Workspace hierarchy introduced in ticket #490.

What it does:
    1. Adds a `workspaces` table if missing.
    2. Adds a `workspace_id` column to `tickets` if missing.
    3. Seeds 'Work' (id=1) and 'Personal' (id=2) workspaces idempotently.
    4. Backfills `workspace_id` on every ticket that doesn't have one yet:
        - type='project' rows → Work
        - other rows → workspace inherited from project ancestor (parent chain),
          falling back to Work for orphans.

The schema migration also runs automatically when the daemon starts up via
`SQLiteTaskClient._migrate()`. This script exists so ops can run a *dry-run*
preview before promoting the change to production.

Usage:
    python3 scripts/migrate_workspaces.py             # apply, default db
    python3 scripts/migrate_workspaces.py --dry-run   # preview only, no writes
    python3 scripts/migrate_workspaces.py --db /path/to/.agents-tasks.db
    python3 scripts/migrate_workspaces.py --all-dbs   # also migrates .agents-mcp.db
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DBS = [REPO_ROOT / ".agents-tasks.db"]
ALL_DBS = [REPO_ROOT / ".agents-tasks.db", REPO_ROOT / ".agents-mcp.db"]


WORKSPACES_DDL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    kind                TEXT NOT NULL DEFAULT 'work',
    description         TEXT DEFAULT '',
    default_assignee    TEXT DEFAULT '',
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
"""

WORKSPACE_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_tickets_workspace ON tickets(workspace_id);"
)

DEFAULT_WORK_WORKSPACE_ID = 1
DEFAULT_PERSONAL_WORKSPACE_ID = 2


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _derive_workspace(
    conn: sqlite3.Connection, parent_id: int, max_depth: int = 6
) -> int:
    """Walk up dependingTicketId chain looking for a non-zero workspace_id."""
    visited: set[int] = set()
    current = parent_id
    for _ in range(max_depth):
        if not current or current in visited:
            return 0
        visited.add(current)
        cur = conn.execute(
            "SELECT workspace_id, dependingTicketId FROM tickets WHERE id = ?",
            (current,),
        )
        row = cur.fetchone()
        if not row:
            return 0
        ws, parent = row
        if ws:
            return ws
        current = parent or 0
    return 0


def migrate(db_path: Path, dry_run: bool = False) -> dict:
    """Run the migration. Returns a stats dict."""
    if not db_path.exists():
        return {"db": str(db_path), "skipped": "file does not exist"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "tickets"):
            return {"db": str(db_path), "skipped": "no tickets table"}

        stats: dict = {
            "db": str(db_path),
            "added_workspace_table": False,
            "added_workspace_column": False,
            "seeded_workspaces": [],
            "backfilled_tickets": 0,
            "dry_run": dry_run,
        }

        # 1. Add workspaces table
        if not _table_exists(conn, "workspaces"):
            stats["added_workspace_table"] = True
            if not dry_run:
                conn.executescript(WORKSPACES_DDL)

        # 2. Add workspace_id column on tickets
        if not _column_exists(conn, "tickets", "workspace_id"):
            stats["added_workspace_column"] = True
            if not dry_run:
                conn.execute(
                    "ALTER TABLE tickets ADD COLUMN workspace_id INTEGER DEFAULT 0"
                )
                conn.execute(WORKSPACE_INDEX_DDL)

        # We need the table available even in dry-run to seed; if it's still
        # missing, we report planned actions below.
        if not _table_exists(conn, "workspaces") and dry_run:
            stats["seeded_workspaces"] = ["Work (planned)", "Personal (planned)"]
        else:
            # 3. Seed default workspaces
            for ws_id, name, kind, desc in (
                (DEFAULT_WORK_WORKSPACE_ID, "Work", "work",
                 "Default workspace for work / engineering tickets."),
                (DEFAULT_PERSONAL_WORKSPACE_ID, "Personal", "personal",
                 "Default workspace for personal / life tickets."),
            ):
                cur = conn.execute(
                    "SELECT id FROM workspaces WHERE name = ?", (name,)
                )
                if cur.fetchone() is None:
                    stats["seeded_workspaces"].append(f"{name} (id={ws_id})")
                    if not dry_run:
                        conn.execute(
                            "INSERT INTO workspaces (id, name, kind, description) "
                            "VALUES (?, ?, ?, ?)",
                            (ws_id, name, kind, desc),
                        )

        # 4. Backfill tickets — only meaningful if column exists.
        if not _column_exists(conn, "tickets", "workspace_id") and dry_run:
            cur = conn.execute("SELECT COUNT(*) FROM tickets")
            stats["backfilled_tickets"] = cur.fetchone()[0]
        elif _column_exists(conn, "tickets", "workspace_id"):
            cur = conn.execute(
                "SELECT id, type, dependingTicketId FROM tickets "
                "WHERE workspace_id IS NULL OR workspace_id = 0"
            )
            unset = cur.fetchall()
            stats["backfilled_tickets"] = len(unset)
            if not dry_run and unset:
                # First, project-type tickets default to Work
                conn.execute(
                    "UPDATE tickets SET workspace_id = ? "
                    "WHERE type = 'project' AND (workspace_id IS NULL OR workspace_id = 0)",
                    (DEFAULT_WORK_WORKSPACE_ID,),
                )
                # Then individual non-project rows
                for row in unset:
                    if row["type"] == "project":
                        continue
                    ws = _derive_workspace(conn, row["dependingTicketId"]) or DEFAULT_WORK_WORKSPACE_ID
                    conn.execute(
                        "UPDATE tickets SET workspace_id = ? WHERE id = ?",
                        (ws, row["id"]),
                    )

        if not dry_run:
            conn.commit()
        return stats
    finally:
        conn.close()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't commit, just report what would change")
    parser.add_argument("--db", action="append", dest="dbs",
                        help="Path to a SQLite db (can repeat). Defaults to .agents-tasks.db")
    parser.add_argument("--all-dbs", action="store_true",
                        help="Migrate both .agents-tasks.db and .agents-mcp.db")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.all_dbs:
        dbs: list[Path] = ALL_DBS
    elif args.dbs:
        dbs = [Path(p) for p in args.dbs]
    else:
        dbs = DEFAULT_DBS

    print(f"Workspace migration{' (dry-run)' if args.dry_run else ''}\n")
    for db in dbs:
        result = migrate(db, dry_run=args.dry_run)
        print(f"== {db} ==")
        for k, v in result.items():
            print(f"  {k}: {v}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
