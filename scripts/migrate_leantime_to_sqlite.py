#!/usr/bin/env python3
"""Migrate all tickets and comments from Leantime (JSON-RPC) to SQLite.

Usage:
    python scripts/migrate_leantime_to_sqlite.py

Reads LEANTIME_URL, LEANTIME_API_KEY from environment (or .env).
Writes to .agents-tasks.db in the repo root (next to agents.yaml).
"""

import asyncio
import json
import os
import sys

import httpx

# Add project to path so we can import sqlite_task_client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "agents-mcp", "src"))

from agents_mcp.sqlite_task_client import SQLiteTaskClient


def load_dotenv(path: str):
    """Minimal .env loader."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key not in os.environ:
                os.environ[key] = value


class LeantimeExporter:
    """Minimal Leantime client for data export."""

    def __init__(self, base_url: str, api_key: str):
        self.endpoint = f"{base_url.rstrip('/')}/api/jsonrpc"
        self.api_key = api_key
        self._id = 0

    async def _call(self, method: str, params: dict = None) -> any:
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._id,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.endpoint,
                json=payload,
                headers={"Content-Type": "application/json", "X-API-KEY": self.api_key},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"API error: {data['error']}")
            return data.get("result")

    async def get_all_tickets(self, project_id: int) -> list[dict]:
        """Get ALL tickets (all statuses)."""
        result = await self._call(
            "leantime.rpc.Tickets.Tickets.getAll",
            {"searchCriteria": {"currentProject": project_id}},
        )
        return result if isinstance(result, list) else []

    async def get_comments(self, module: str, module_id: int) -> list[dict]:
        """Get comments for a module entity."""
        result = await self._call(
            "leantime.rpc.Comments.getComments",
            {"module": module, "entityId": module_id},
        )
        return result if isinstance(result, list) else []


# Ticket field mapping: Leantime field -> SQLite column
TICKET_FIELDS = [
    "id", "headline", "description", "type", "status", "priority",
    "tags", "projectId", "userId", "date", "dateToEdit",
    "editFrom", "editTo", "dependingTicketId", "milestoneid",
    "storypoints", "sprint", "acceptanceCriteria",
]


async def migrate(leantime_url: str, api_key: str, project_id: int, db_path: str):
    """Run the full migration."""
    exporter = LeantimeExporter(leantime_url, api_key)
    client = SQLiteTaskClient(db_path, project_id=project_id)

    print(f"Exporting from Leantime at {leantime_url} ...")
    print(f"Target SQLite DB: {db_path}")

    # 1. Export all tickets
    tickets = await exporter.get_all_tickets(project_id)
    print(f"Found {len(tickets)} tickets")

    # Initialize DB (creates tables)
    db = await client._get_db()

    # 2. Insert tickets with their original IDs
    ticket_count = 0
    for t in tickets:
        values = {}
        for field in TICKET_FIELDS:
            if field in t and t[field] is not None:
                values[field] = t[field]

        # Ensure required fields
        if "id" not in values:
            continue

        # Convert status to integer if string
        if "status" in values:
            try:
                values["status"] = int(values["status"])
            except (ValueError, TypeError):
                values["status"] = 3

        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        try:
            await db.execute(
                f"INSERT OR REPLACE INTO tickets ({columns}) VALUES ({placeholders})",
                list(values.values()),
            )
            ticket_count += 1
        except Exception as e:
            print(f"  WARNING: Failed to insert ticket #{values.get('id')}: {e}")

    await db.commit()
    print(f"Imported {ticket_count} tickets")

    # 3. Export and insert comments for each ticket
    comment_count = 0
    for t in tickets:
        tid = t.get("id")
        if not tid:
            continue

        # Try both "ticket" and "tickets" module names
        for module in ("ticket", "tickets"):
            try:
                comments = await exporter.get_comments(module, int(tid))
            except Exception:
                comments = []

            for c in comments:
                cid = c.get("id")
                text = c.get("text", "")
                user_id = c.get("userId", 1)
                date = c.get("date", "")
                module_id = c.get("moduleId", tid)

                if not text:
                    continue

                try:
                    await db.execute(
                        "INSERT OR REPLACE INTO comments (id, text, module, moduleId, userId, date) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (cid, text, "ticket", int(module_id), user_id, date),
                    )
                    comment_count += 1
                except Exception as e:
                    print(f"  WARNING: Failed to insert comment #{cid}: {e}")

    await db.commit()
    print(f"Imported {comment_count} comments")

    # 4. Verify
    async with db.execute("SELECT COUNT(*) as cnt FROM tickets") as cur:
        row = await cur.fetchone()
        db_ticket_count = row[0]

    async with db.execute("SELECT COUNT(*) as cnt FROM comments") as cur:
        row = await cur.fetchone()
        db_comment_count = row[0]

    print(f"\nVerification:")
    print(f"  Tickets in DB: {db_ticket_count} (source: {len(tickets)})")
    print(f"  Comments in DB: {db_comment_count}")

    if db_ticket_count == ticket_count:
        print("\n✅ Migration complete!")
    else:
        print(f"\n⚠️  Ticket count mismatch: imported {ticket_count}, DB has {db_ticket_count}")

    await client.close()


def main():
    # Find repo root (where agents.yaml lives)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)

    # Load .env (check repo root, also check AGENTS_CONFIG_PATH parent)
    load_dotenv(os.path.join(repo_root, ".env"))
    config_path = os.environ.get("AGENTS_CONFIG_PATH")
    if config_path:
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(config_path)), ".env"))

    leantime_url = os.environ.get("LEANTIME_URL", "http://localhost:9090")
    api_key = os.environ.get("LEANTIME_API_KEY")
    project_id = int(os.environ.get("LEANTIME_PROJECT_ID", "3"))

    if not api_key:
        print("ERROR: LEANTIME_API_KEY not set in environment or .env")
        sys.exit(1)

    db_path = os.path.join(repo_root, ".agents-tasks.db")

    asyncio.run(migrate(leantime_url, api_key, project_id, db_path))


if __name__ == "__main__":
    main()
