"""SQLite-based task management client for ticket/comment/subtask operations."""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)

# ── Field sets ──

SUMMARY_FIELDS = {
    "id", "headline", "status", "tags", "priority",
    "date", "dateToEdit", "type", "dependingTicketId",
    "projectId", "milestoneid", "assignee", "start_time",
}

DETAIL_FIELDS = SUMMARY_FIELDS | {
    "description", "userId", "editFrom", "editTo",
    "storypoints", "sprint", "acceptanceCriteria",
    "depends_on",
}

COMMENT_FIELDS = {"id", "text", "userId", "date", "moduleId", "author"}

# ── Helpers ──


def extract_assignee(ticket: dict) -> Optional[str]:
    """Extract agent assignee from tags (e.g. 'agent:dev' -> 'dev').

    DEPRECATED: Use the native 'assignee' column instead.
    Kept for backward compatibility during transition.
    """
    tags = ticket.get("tags") or ""
    for part in tags.split(","):
        part = part.strip()
        if part.startswith("agent:"):
            return part[6:]
    return None


def inject_assignee(ticket: dict) -> dict:
    """Add 'assignee' field extracted from tags.

    DEPRECATED: The 'assignee' column is now native in the DB schema.
    Kept for backward compatibility during transition.
    """
    ticket = dict(ticket)
    # Prefer native assignee column if set, fall back to tags extraction
    if not ticket.get("assignee"):
        ticket["assignee"] = extract_assignee(ticket)
    return ticket


def tags_with_assignee(existing_tags: Optional[str], assignee: str) -> str:
    """Add/replace agent: tag in a tags string.

    Still used to maintain tag redundancy during transition period.
    """
    parts = []
    if existing_tags:
        parts = [p.strip() for p in existing_tags.split(",") if not p.strip().startswith("agent:")]
    parts.append(f"agent:{assignee}")
    return ",".join(parts)


# ── Schema ──

_TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    headline            TEXT NOT NULL DEFAULT '',
    description         TEXT DEFAULT '',
    type                TEXT DEFAULT 'task',
    status              INTEGER DEFAULT 3,
    priority            TEXT DEFAULT 'medium',
    tags                TEXT DEFAULT '',
    projectId           INTEGER DEFAULT 3,
    userId              INTEGER DEFAULT 1,
    date                TEXT DEFAULT '',
    dateToEdit          TEXT DEFAULT '',
    editFrom            TEXT DEFAULT '0000-00-00 00:00:00',
    editTo              TEXT DEFAULT '0000-00-00 00:00:00',
    dependingTicketId   INTEGER DEFAULT 0,
    milestoneid         INTEGER DEFAULT 0,
    storypoints         INTEGER DEFAULT 0,
    sprint              INTEGER DEFAULT 0,
    acceptanceCriteria  TEXT DEFAULT '',
    assignee            TEXT DEFAULT '',
    depends_on          TEXT DEFAULT '',
    start_time          TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL DEFAULT '',
    module      TEXT DEFAULT 'ticket',
    moduleId    INTEGER NOT NULL,
    userId      INTEGER DEFAULT 1,
    date        TEXT DEFAULT '',
    author      TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_comments_module
    ON comments(module, moduleId);
"""


class SQLiteTaskClient:
    """SQLite-backed task management client."""

    def __init__(self, db_path: str, project_id: int = 3):
        self.db_path = db_path
        self.project_id = project_id
        self._db: Optional[aiosqlite.Connection] = None

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_TASK_SCHEMA)
            await self._db.commit()
            await self._migrate(self._db)
        return self._db

    async def _migrate(self, db: aiosqlite.Connection):
        """Run incremental migrations for existing databases.

        Adds columns that may not exist in older schemas and backfills data.
        ALTER TABLE ADD COLUMN is idempotent-safe: we catch errors for
        already-existing columns.
        """
        migrations = [
            ("tickets", "assignee", "TEXT DEFAULT ''"),
            ("tickets", "depends_on", "TEXT DEFAULT ''"),
            ("comments", "author", "TEXT DEFAULT ''"),
            ("tickets", "start_time", "TEXT DEFAULT ''"),
        ]
        changed = False
        for table, column, col_type in migrations:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                changed = True
                logger.info("Migration: added %s.%s", table, column)
            except Exception:
                # Column already exists — expected for new DBs or re-runs
                pass

        # Backfill: populate assignee column from agent:xxx tags where empty
        async with db.execute(
            "SELECT id, tags FROM tickets WHERE (assignee IS NULL OR assignee = '') AND tags LIKE '%agent:%'"
        ) as cur:
            rows = await cur.fetchall()
        if rows:
            for row in rows:
                assignee = extract_assignee(dict(row))
                if assignee:
                    await db.execute(
                        "UPDATE tickets SET assignee = ? WHERE id = ?",
                        (assignee, row["id"]),
                    )
            changed = True
            logger.info("Migration: backfilled assignee for %d tickets", len(rows))

        # Create index if not exists (idempotent)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee)"
        )

        # FTS5 virtual table for full-text search on headline + description
        await self._migrate_fts(db)

        if changed:
            await db.commit()

    async def _migrate_fts(self, db: aiosqlite.Connection):
        """Create or rebuild FTS5 index for ticket search.

        The FTS table stores its own copy of headline + description,
        rebuilt on startup and kept in sync on insert/update.
        """
        # Check if FTS table exists
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tickets_fts'"
        ) as cur:
            exists = await cur.fetchone()

        if not exists:
            await db.execute(
                "CREATE VIRTUAL TABLE tickets_fts USING fts5(headline, description)"
            )
            logger.info("Migration: created FTS5 table tickets_fts")

        # Rebuild: clear and re-populate from tickets table
        # This ensures FTS is always in sync, even after manual DB edits
        await db.execute("DELETE FROM tickets_fts")
        await db.execute(
            "INSERT INTO tickets_fts(rowid, headline, description) "
            "SELECT id, headline, COALESCE(description, '') FROM tickets"
        )
        await db.commit()
        logger.info("Migration: FTS5 index rebuilt")

    async def close(self):
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ── Internal helpers ──

    def _row_to_dict(self, row: aiosqlite.Row) -> dict:
        """Convert a Row object to a plain dict."""
        return dict(row)

    # ── Ticket operations ──

    async def get_ticket(self, ticket_id: int, prune: bool = True) -> dict:
        """Get ticket by ID. If prune=True, returns DETAIL_FIELDS (includes assignee, depends_on)."""
        db = await self._get_db()
        async with db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        raw = self._row_to_dict(row)
        if not prune:
            return inject_assignee(raw)
        pruned = {k: v for k, v in raw.items() if k in DETAIL_FIELDS}
        return inject_assignee(pruned)

    async def list_tickets(
        self,
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        tags: Optional[str] = None,
        dateFrom: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        include_future: bool = False,
    ) -> dict:
        """List tickets with summary fields and pagination.

        Returns:
            {"tickets": [...], "total": N, "offset": N, "limit": N}
        """
        db = await self._get_db()
        pid = project_id or self.project_id

        conditions = ["projectId = ?"]
        params: list[Any] = [pid]

        # Status filter (default: active only)
        effective_status = status if status is not None else "1,3,4"
        if effective_status != "all":
            allowed = [int(s.strip()) for s in effective_status.split(",")]
            placeholders = ",".join("?" for _ in allowed)
            conditions.append(f"status IN ({placeholders})")
            params.extend(allowed)

        # Assignee filter — use native column
        if assignee:
            conditions.append("assignee = ?")
            params.append(assignee)

        # Tags filter (independent of assignee)
        if tags:
            conditions.append("tags LIKE ?")
            params.append(f"%{tags}%")

        # Date filter
        if dateFrom:
            conditions.append("date >= ?")
            params.append(dateFrom)

        # Future ticket filter: exclude tickets with start_time in the future
        if not include_future:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conditions.append("(start_time IS NULL OR start_time = '' OR start_time <= ?)")
            params.append(now)

        where = " AND ".join(conditions)
        query = f"SELECT * FROM tickets WHERE {where} ORDER BY id DESC"

        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()

        all_tickets = [self._row_to_dict(r) for r in rows]
        total = len(all_tickets)

        # Pagination (limit=0 or None means no limit, for backward compatibility)
        if offset and offset > 0:
            all_tickets = all_tickets[offset:]
        if limit and limit > 0:
            all_tickets = all_tickets[:limit]

        # Field pruning + assignee injection
        pruned = [
            inject_assignee({k: v for k, v in t.items() if k in SUMMARY_FIELDS})
            for t in all_tickets
        ]

        return {
            "tickets": pruned,
            "total": total,
            "offset": offset,
            "limit": limit if limit and limit > 0 else total,
        }

    async def search_tickets(
        self,
        query: str,
        limit: int = 10,
        time_range: Optional[str] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> dict:
        """Full-text search on ticket headline and description using FTS5.

        Args:
            query: Search keywords (FTS5 query syntax supported).
            limit: Max results (default 10, max 50).
            time_range: Filter by recency, e.g. "7d" = last 7 days, "30d" = last 30 days.
            status: Comma-separated status codes to filter (e.g. "3,4").
            assignee: Filter by agent name.

        Returns:
            {"tickets": [...], "total": N, "query": str}
        """
        db = await self._get_db()
        limit = min(max(limit, 1), 50)

        # Build the FTS query — escape special chars for safety
        # FTS5 supports implicit AND between terms
        fts_query = query.strip()
        if not fts_query:
            return {"tickets": [], "total": 0, "query": query}

        # Join FTS results with tickets table for filtering and full data
        conditions = ["t.projectId = ?"]
        params: list[Any] = [self.project_id]

        if status:
            allowed = [int(s.strip()) for s in status.split(",")]
            placeholders = ",".join("?" for _ in allowed)
            conditions.append(f"t.status IN ({placeholders})")
            params.extend(allowed)

        if assignee:
            conditions.append("t.assignee = ?")
            params.append(assignee)

        if time_range:
            # Parse "7d", "30d", "1d" etc.
            match = re.match(r"^(\d+)d$", time_range.strip())
            if match:
                days = int(match.group(1))
                cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                conditions.append("t.date >= ?")
                params.append(cutoff)

        where = " AND ".join(conditions)
        params.append(fts_query)

        sql = (
            "SELECT t.*, fts.rank "
            "FROM tickets_fts fts "
            "JOIN tickets t ON t.id = fts.rowid "
            f"WHERE {where} AND tickets_fts MATCH ? "
            "ORDER BY fts.rank "
            f"LIMIT {limit}"
        )

        try:
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        except Exception as e:
            logger.warning("FTS search failed: %s", e)
            return {"tickets": [], "total": 0, "query": query, "error": str(e)}

        tickets = [
            inject_assignee({k: v for k, v in self._row_to_dict(r).items() if k in SUMMARY_FIELDS})
            for r in rows
        ]

        return {
            "tickets": tickets,
            "total": len(tickets),
            "query": query,
        }

    async def create_ticket(
        self,
        headline: str,
        project_id: Optional[int] = None,
        user_id: int = 1,
        tags: Optional[str] = None,
        assignee: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Create ticket. Writes assignee to native column AND agent:xxx tag (compat)."""
        effective_tags = tags
        if assignee:
            effective_tags = tags_with_assignee(tags, assignee)

        values = {
            "headline": headline,
            "projectId": project_id or self.project_id,
            "userId": user_id,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **kwargs,
        }
        if effective_tags is not None:
            values["tags"] = effective_tags
        if assignee:
            values["assignee"] = assignee

        db = await self._get_db()
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        async with db.execute(
            f"INSERT INTO tickets ({columns}) VALUES ({placeholders})",
            list(values.values()),
        ) as cur:
            ticket_id = cur.lastrowid

        # Sync FTS index
        await self._fts_upsert(db, ticket_id, values.get("headline", ""), values.get("description", ""))
        await db.commit()
        return ticket_id

    async def _fts_upsert(self, db: aiosqlite.Connection, ticket_id: int, headline: str, description: str):
        """Insert or update FTS index entry for a ticket."""
        try:
            # Delete existing entry (if any), then insert new
            await db.execute("DELETE FROM tickets_fts WHERE rowid = ?", (ticket_id,))
            await db.execute(
                "INSERT INTO tickets_fts(rowid, headline, description) VALUES(?, ?, ?)",
                (ticket_id, headline or "", description or ""),
            )
        except Exception:
            pass  # FTS table may not exist yet (pre-migration)

    async def update_ticket(
        self,
        ticket_id: int,
        project_id: Optional[int] = None,
        assignee: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Update ticket. Writes assignee to native column AND agent:xxx tag (compat)."""
        db = await self._get_db()

        # Build update values
        update_values = dict(kwargs)
        if project_id is not None:
            update_values["projectId"] = project_id

        if assignee:
            # Write native assignee column
            update_values["assignee"] = assignee
            # Also update tags for backward compatibility
            async with db.execute("SELECT tags FROM tickets WHERE id = ?", (ticket_id,)) as cur:
                row = await cur.fetchone()
            current_tags = row["tags"] if row else ""
            update_values["tags"] = tags_with_assignee(current_tags, assignee)

        if not update_values:
            return True

        set_clause = ", ".join(f"{k} = ?" for k in update_values.keys())
        params = list(update_values.values()) + [ticket_id]
        await db.execute(f"UPDATE tickets SET {set_clause} WHERE id = ?", params)

        # Sync FTS if headline or description changed
        if "headline" in update_values or "description" in update_values:
            async with db.execute(
                "SELECT headline, description FROM tickets WHERE id = ?", (ticket_id,)
            ) as cur:
                row = await cur.fetchone()
            if row:
                await self._fts_upsert(db, ticket_id, row["headline"], row["description"] or "")

        await db.commit()
        return True

    # ── Comments ──

    @staticmethod
    def _normalize_module(module: str) -> str:
        """Normalize module name: 'tickets' -> 'ticket'."""
        if module == "tickets":
            return "ticket"
        return module

    async def add_comment(
        self, module: str, module_id: int, comment: str, author: Optional[str] = None
    ) -> Any:
        """Add a comment with optional author attribution."""
        module = self._normalize_module(module)
        db = await self._get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with db.execute(
            "INSERT INTO comments (text, module, moduleId, date, author) VALUES (?, ?, ?, ?, ?)",
            (comment, module, module_id, now, author or ""),
        ) as cur:
            comment_id = cur.lastrowid
        await db.commit()
        return comment_id

    async def get_comments(
        self, module: str, module_id: int, limit: int = 10, offset: int = 0
    ) -> dict:
        """Get comments for a module entity with pagination.

        Args:
            module: Module type (e.g. 'ticket').
            module_id: ID of the module entity.
            limit: Max comments to return. Default 10. Use 0 for all (backward compat).
            offset: Skip first N comments. Default 0.

        Returns:
            {"comments": [...], "total": N, "limit": N, "offset": N}
        """
        module = self._normalize_module(module)
        db = await self._get_db()
        # Query both normalized and legacy module names for compatibility
        modules = [module]
        if module == "ticket":
            modules.append("tickets")
        placeholders = ",".join("?" for _ in modules)

        # Total count
        async with db.execute(
            f"SELECT COUNT(*) as cnt FROM comments WHERE module IN ({placeholders}) AND moduleId = ?",
            modules + [module_id],
        ) as cur:
            row = await cur.fetchone()
            total = row["cnt"] if row else 0

        # Fetch with pagination (limit=0 means all, for backward compatibility)
        if limit and limit > 0:
            async with db.execute(
                f"SELECT * FROM comments WHERE module IN ({placeholders}) AND moduleId = ? ORDER BY id LIMIT ? OFFSET ?",
                modules + [module_id, limit, offset],
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                f"SELECT * FROM comments WHERE module IN ({placeholders}) AND moduleId = ? ORDER BY id",
                modules + [module_id],
            ) as cur:
                rows = await cur.fetchall()

        comments = [
            {k: v for k, v in self._row_to_dict(r).items() if k in COMMENT_FIELDS}
            for r in rows
        ]
        return {
            "comments": comments,
            "total": total,
            "limit": limit if limit and limit > 0 else total,
            "offset": offset,
        }

    # ── Subtasks ──

    async def get_all_subtasks(self, ticket_id: int) -> Any:
        """Get all subtasks for a ticket (subtasks have dependingTicketId = parent)."""
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM tickets WHERE dependingTicketId = ? AND type = 'subtask' ORDER BY id",
            (ticket_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [inject_assignee(self._row_to_dict(r)) for r in rows]

    async def upsert_subtask(
        self,
        parent_ticket_id: int,
        headline: str,
        tags: Optional[str] = None,
        assignee: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Create a subtask under a parent ticket."""
        parent = await self.get_ticket(parent_ticket_id, prune=False)
        if not parent:
            raise ValueError(f"Parent ticket {parent_ticket_id} not found")

        effective_tags = tags
        if assignee:
            effective_tags = tags_with_assignee(tags, assignee)

        values = {
            "headline": headline,
            "type": "subtask",
            "projectId": parent.get("projectId", self.project_id),
            "userId": parent.get("userId", 1),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dependingTicketId": parent_ticket_id,
            "milestoneid": parent.get("milestoneid") or 0,
            **kwargs,
        }
        if effective_tags is not None:
            values["tags"] = effective_tags
        if assignee:
            values["assignee"] = assignee

        db = await self._get_db()
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        async with db.execute(
            f"INSERT INTO tickets ({columns}) VALUES ({placeholders})",
            list(values.values()),
        ) as cur:
            subtask_id = cur.lastrowid
        await db.commit()
        return subtask_id

    # ── Status labels ──

    async def get_status_labels(self) -> Any:
        """Return fixed status labels."""
        return {
            "-1": "Archived",
            "0": "Done",
            "1": "Blocked",
            "3": "New",
            "4": "In Progress",
        }

    # ── Dependency checking (for auto-dispatch) ──

    # Statuses considered "done": 0=已完成, -1=已归档, 5=agents also use this
    DONE_STATUSES = (0, -1, 5)

    def _extract_dep_ids(self, ticket: dict) -> list[int]:
        """Extract dependency IDs from both depends_on column and description DEPENDS_ON.

        Sources (merged, deduplicated):
        1. Native depends_on column (comma-separated IDs, e.g. "10,20,30")
        2. Legacy DEPENDS_ON in description (e.g. "DEPENDS_ON: #10, #20")
        """
        dep_ids = set()

        # Source 1: native depends_on column
        depends_on = ticket.get("depends_on") or ""
        for part in depends_on.split(","):
            part = part.strip()
            if part.isdigit():
                dep_ids.add(int(part))

        # Source 2: description DEPENDS_ON (legacy)
        desc = ticket.get("description") or ""
        match = re.search(
            r"DEPENDS_ON:\s*((?:#\d+|&#35;\d+)(?:\s*,\s*(?:#\d+|&#35;\d+))*)",
            desc,
        )
        if match:
            for num in re.findall(r"(\d+)", match.group(1)):
                dep_ids.add(int(num))

        return sorted(dep_ids)

    async def check_and_unblock_deps(self) -> list[str]:
        """Check dependencies across tickets and auto-correct status.

        Uses both native depends_on column and legacy DEPENDS_ON in description.

        Two passes:
        1. Auto-lock: status=3 tickets with unresolved deps → set to status=1
        2. Auto-unlock: status=1 tickets whose deps are all done → set to status=3
        """
        db = await self._get_db()

        # Get all tickets for the project
        async with db.execute(
            "SELECT id, status, description, depends_on FROM tickets WHERE projectId = ?",
            (self.project_id,),
        ) as cur:
            rows = await cur.fetchall()

        tickets = [self._row_to_dict(r) for r in rows]
        status_map = {t["id"]: t["status"] for t in tickets}

        messages = []

        # Pass 1: Auto-lock status=3 tickets with unresolved deps
        for t in tickets:
            if t["status"] != 3:
                continue
            dep_ids = self._extract_dep_ids(t)
            if not dep_ids:
                continue
            # If all deps are done, leave as status=3 (actionable)
            if all(status_map.get(d, 99) in self.DONE_STATUSES for d in dep_ids):
                continue

            ticket_id = t["id"]
            await db.execute(
                "UPDATE tickets SET status = 1 WHERE id = ?", (ticket_id,)
            )
            messages.append(f"Auto-locked #{ticket_id} (deps {dep_ids} not all done)")

        # Pass 2: Unblock status=1 tickets whose deps are all done
        for t in tickets:
            if t["status"] != 1:
                continue
            dep_ids = self._extract_dep_ids(t)
            if not dep_ids:
                continue
            if not all(status_map.get(d, 99) in self.DONE_STATUSES for d in dep_ids):
                continue

            ticket_id = t["id"]
            await db.execute(
                "UPDATE tickets SET status = 3 WHERE id = ?", (ticket_id,)
            )
            messages.append(f"Unblocked #{ticket_id} (deps {dep_ids} all done)")

        if messages:
            await db.commit()
        return messages

    async def update_depends_on(self, ticket_id: int, depends_on: str) -> bool:
        """Update the depends_on field for a ticket.

        Args:
            ticket_id: Ticket ID to update.
            depends_on: Comma-separated ticket IDs (e.g. "10,20,30").
        """
        db = await self._get_db()
        # Normalize: strip spaces, remove empty parts
        parts = [p.strip() for p in depends_on.split(",") if p.strip()]
        normalized = ",".join(parts)
        await db.execute(
            "UPDATE tickets SET depends_on = ? WHERE id = ?",
            (normalized, ticket_id),
        )
        await db.commit()
        return True

    async def has_pending_tasks(self, agent: str) -> bool:
        """Check if an agent has pending tasks (status 3 or 4, not future-scheduled)."""
        db = await self._get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM tickets WHERE assignee = ? AND status IN (3, 4) AND projectId = ? "
            "AND (start_time IS NULL OR start_time = '' OR start_time <= ?)",
            (agent, self.project_id, now),
        ) as cur:
            row = await cur.fetchone()
        return row["cnt"] > 0 if row else False

    async def get_stale_in_progress(self, agent: str, threshold_minutes: int = 30) -> list[dict]:
        """Get in_progress (status=4) tickets for agent older than threshold (not future-scheduled)."""
        db = await self._get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cutoff = (datetime.utcnow() - timedelta(minutes=threshold_minutes)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        async with db.execute(
            "SELECT id, headline, date FROM tickets "
            "WHERE assignee = ? AND status = 4 AND projectId = ? "
            "AND date < ? AND date > '0001-01-01' "
            "AND (start_time IS NULL OR start_time = '' OR start_time <= ?)",
            (agent, self.project_id, cutoff, now),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {"id": r["id"], "headline": r["headline"], "date": r["date"]}
            for r in rows
        ]

    async def get_unattended_new_tickets(self, agent: str, threshold_minutes: int = 30) -> list[dict]:
        """Get new (status=3) tickets assigned to agent that have been sitting for too long.

        These are tickets that were assigned but never picked up (never moved to status=4).
        Excludes future-scheduled tickets (start_time in the future).
        """
        db = await self._get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cutoff = (datetime.utcnow() - timedelta(minutes=threshold_minutes)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        async with db.execute(
            "SELECT id, headline, date FROM tickets "
            "WHERE assignee = ? AND status = 3 AND projectId = ? "
            "AND date < ? AND date > '0001-01-01' "
            "AND (start_time IS NULL OR start_time = '' OR start_time <= ?)",
            (agent, self.project_id, cutoff, now),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {"id": r["id"], "headline": r["headline"], "date": r["date"]}
            for r in rows
        ]

    async def get_agent_workload(self, agents: list[str]) -> dict[str, dict]:
        """Get workload info for multiple agents."""
        db = await self._get_db()
        workloads = {}
        for agent in agents:
            async with db.execute(
                "SELECT status, COUNT(*) as cnt FROM tickets "
                "WHERE assignee = ? AND projectId = ? "
                "GROUP BY status",
                (agent, self.project_id),
            ) as cur:
                rows = await cur.fetchall()

            counts = {r["status"]: r["cnt"] for r in rows}
            in_progress = counts.get(4, 0)
            new = counts.get(3, 0)
            blocked = counts.get(1, 0)
            workloads[agent] = {
                "in_progress": in_progress,
                "new": new,
                "blocked": blocked,
                "total_active": in_progress + new,
            }
        return workloads
