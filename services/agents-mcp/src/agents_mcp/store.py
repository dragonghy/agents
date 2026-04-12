"""Local SQLite store for agent profiles and P2P messages."""

import json
import logging
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_profiles (
    agent_id        TEXT PRIMARY KEY,
    identity        TEXT,
    current_context TEXT,
    active_skills   TEXT,
    expertise       TEXT,
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent      TEXT NOT NULL,
    to_agent        TEXT NOT NULL,
    body            TEXT NOT NULL,
    is_read         INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_msg_inbox
    ON messages(to_agent, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_msg_conv
    ON messages(from_agent, to_agent, created_at DESC);

CREATE TABLE IF NOT EXISTS token_usage_daily (
    agent_id        TEXT NOT NULL,
    date            TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cache_read_tokens  INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    message_count   INTEGER DEFAULT 0,
    PRIMARY KEY (agent_id, date, model)
);

CREATE INDEX IF NOT EXISTS idx_usage_agent
    ON token_usage_daily(agent_id, date DESC);

CREATE TABLE IF NOT EXISTS usage_scan_state (
    agent_id        TEXT NOT NULL,
    filename        TEXT NOT NULL,
    byte_offset     INTEGER DEFAULT 0,
    PRIMARY KEY (agent_id, filename)
);

CREATE TABLE IF NOT EXISTS schedules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    interval_hours  REAL NOT NULL,
    prompt          TEXT NOT NULL,
    last_dispatched_at REAL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sched_agent
    ON schedules(agent_id);

CREATE TABLE IF NOT EXISTS deleted_schedules (
    agent_id        TEXT NOT NULL,
    prompt_hash     TEXT NOT NULL,
    deleted_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (agent_id, prompt_hash)
);

CREATE TABLE IF NOT EXISTS dispatch_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    trigger_type    TEXT NOT NULL,
    message         TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dispatch_agent
    ON dispatch_events(agent_id, created_at DESC);

-- Pub/Sub: ticket subscriptions
CREATE TABLE IF NOT EXISTS ticket_subscribers (
    ticket_id   INTEGER NOT NULL,
    agent_id    TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticket_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_sub_agent
    ON ticket_subscribers(agent_id);

-- Pub/Sub: event-driven notifications
CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    ticket_id       INTEGER,
    type            TEXT NOT NULL,
    source_agent_id TEXT,
    title           TEXT DEFAULT '',
    body            TEXT DEFAULT '',
    state           TEXT DEFAULT 'unread',
    created_at      TEXT DEFAULT (datetime('now')),
    read_at         TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_notif_agent
    ON notifications(agent_id, state, created_at DESC);

-- Singleton service advisory locks
CREATE TABLE IF NOT EXISTS service_locks (
    service_id  TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    acquired_at TEXT DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);
"""

# Max dispatch events to keep per agent (auto-cleanup on insert)
_MAX_DISPATCH_EVENTS_PER_AGENT = 200

# Max notifications to keep per agent (auto-cleanup on insert)
_MAX_NOTIFICATIONS_PER_AGENT = 500


class AgentStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AgentStore initialized: %s", self.db_path)

    async def close(self):
        if self._db:
            await self._db.close()

    # ── Profile methods ──

    async def upsert_profile(self, agent_id: str, **fields) -> dict:
        """Insert or update an agent profile. Only non-None fields are updated."""
        allowed = {"identity", "current_context", "active_skills", "expertise"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}

        existing = await self.get_profile(agent_id)
        if existing:
            if not updates:
                return existing
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            set_clause += ", updated_at = datetime('now')"
            values = list(updates.values()) + [agent_id]
            await self._db.execute(
                f"UPDATE agent_profiles SET {set_clause} WHERE agent_id = ?",
                values,
            )
        else:
            cols = ["agent_id"] + list(updates.keys()) + ["updated_at"]
            placeholders = ["?"] * len(updates) + ["datetime('now')"]
            all_placeholders = ["?"] + placeholders
            values = [agent_id] + list(updates.values())
            await self._db.execute(
                f"INSERT INTO agent_profiles ({', '.join(cols)}) VALUES ({', '.join(all_placeholders)})",
                values,
            )
        await self._db.commit()
        return await self.get_profile(agent_id)

    async def get_profile(self, agent_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM agent_profiles WHERE agent_id = ?", (agent_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_all_profiles(self) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM agent_profiles ORDER BY agent_id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Message methods ──

    async def insert_message(self, from_agent: str, to_agent: str, body: str) -> int:
        async with self._db.execute(
            "INSERT INTO messages (from_agent, to_agent, body) VALUES (?, ?, ?)",
            (from_agent, to_agent, body),
        ) as cursor:
            msg_id = cursor.lastrowid
        await self._db.commit()
        return msg_id

    async def get_inbox(
        self,
        agent_id: str,
        unread_only: bool = True,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        where = "to_agent = ?"
        params: list = [agent_id]
        if unread_only:
            where += " AND is_read = 0"

        # Total count
        async with self._db.execute(
            f"SELECT COUNT(*) FROM messages WHERE {where}", params
        ) as cursor:
            total = (await cursor.fetchone())[0]

        # Unread count (always)
        async with self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE to_agent = ? AND is_read = 0",
            (agent_id,),
        ) as cursor:
            unread_count = (await cursor.fetchone())[0]

        # Messages
        async with self._db.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cursor:
            rows = await cursor.fetchall()

        return {
            "messages": [dict(r) for r in rows],
            "total": total,
            "unread_count": unread_count,
        }

    async def get_conversation(
        self,
        agent_id: str,
        with_agent: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        async with self._db.execute(
            """SELECT * FROM messages
               WHERE (from_agent = ? AND to_agent = ?)
                  OR (from_agent = ? AND to_agent = ?)
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (agent_id, with_agent, with_agent, agent_id, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def mark_read(self, agent_id: str, message_ids: list[int]) -> int:
        if not message_ids:
            return 0
        placeholders = ", ".join("?" for _ in message_ids)
        async with self._db.execute(
            f"UPDATE messages SET is_read = 1 WHERE to_agent = ? AND id IN ({placeholders})",
            [agent_id] + message_ids,
        ) as cursor:
            count = cursor.rowcount
        await self._db.commit()
        return count

    async def get_unread_count(self, agent_id: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE to_agent = ? AND is_read = 0",
            (agent_id,),
        ) as cursor:
            return (await cursor.fetchone())[0]

    async def get_all_messages(
        self, limit: int = 100, offset: int = 0
    ) -> dict:
        """Get all messages, newest first. Used by Display UI messages page."""
        async with self._db.execute(
            "SELECT COUNT(*) FROM messages"
        ) as cursor:
            total = (await cursor.fetchone())[0]

        async with self._db.execute(
            "SELECT * FROM messages ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()

        return {
            "messages": [dict(r) for r in rows],
            "total": total,
        }

    async def get_conversation_threads(
        self, agent_ids: Optional[list[str]] = None
    ) -> list[dict]:
        """Get unique conversation pairs with latest message info.

        Args:
            agent_ids: If provided, only return threads where BOTH participants
                       are in this list (used for "current agents only" filter).
        """
        if agent_ids:
            placeholders = ", ".join("?" for _ in agent_ids)
            where_clause = (
                f"WHERE from_agent IN ({placeholders}) "
                f"AND to_agent IN ({placeholders})"
            )
            query_params = agent_ids + agent_ids
        else:
            where_clause = ""
            query_params = []

        async with self._db.execute(
            f"""SELECT
                 CASE WHEN from_agent < to_agent THEN from_agent ELSE to_agent END AS agent_a,
                 CASE WHEN from_agent < to_agent THEN to_agent ELSE from_agent END AS agent_b,
                 MAX(created_at) AS last_message_at,
                 COUNT(*) AS message_count
               FROM messages
               {where_clause}
               GROUP BY agent_a, agent_b
               ORDER BY last_message_at DESC""",
            query_params,
        ) as cursor:
            rows = await cursor.fetchall()

        threads = []
        for row in rows:
            row_dict = dict(row)
            # Fetch the latest message for preview
            async with self._db.execute(
                """SELECT body, from_agent FROM messages
                   WHERE (from_agent = ? AND to_agent = ?)
                      OR (from_agent = ? AND to_agent = ?)
                   ORDER BY created_at DESC LIMIT 1""",
                (row_dict["agent_a"], row_dict["agent_b"],
                 row_dict["agent_b"], row_dict["agent_a"]),
            ) as cursor2:
                latest = await cursor2.fetchone()
            if latest:
                latest_dict = dict(latest)
                row_dict["last_message"] = latest_dict["body"][:100]
                row_dict["last_sender"] = latest_dict["from_agent"]
            threads.append(row_dict)

        return threads

    # ── Token usage methods ──

    async def get_scan_state(self, agent_id: str) -> dict:
        """Get the JSONL scan state for an agent (filename -> byte offset)."""
        async with self._db.execute(
            "SELECT filename, byte_offset FROM usage_scan_state WHERE agent_id = ?",
            (agent_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return {row["filename"]: row["byte_offset"] for row in rows}

    async def save_scan_state(self, agent_id: str, scan_state: dict):
        """Save the JSONL scan state for an agent."""
        for filename, offset in scan_state.items():
            await self._db.execute(
                """INSERT INTO usage_scan_state (agent_id, filename, byte_offset)
                   VALUES (?, ?, ?)
                   ON CONFLICT(agent_id, filename) DO UPDATE SET byte_offset = ?""",
                (agent_id, filename, offset, offset),
            )
        await self._db.commit()

    async def upsert_daily_usage(self, agent_id: str, daily: dict):
        """Merge daily usage data into the database.

        Args:
            agent_id: Agent ID
            daily: {date_str: {model: {input_tokens, output_tokens, ...}}}
        """
        for date_str, models in daily.items():
            for model, usage in models.items():
                # Check if row exists
                async with self._db.execute(
                    """SELECT input_tokens, output_tokens, cache_read_tokens,
                              cache_write_tokens, message_count
                       FROM token_usage_daily
                       WHERE agent_id = ? AND date = ? AND model = ?""",
                    (agent_id, date_str, model),
                ) as cursor:
                    existing = await cursor.fetchone()

                if existing:
                    # Add incremental values
                    await self._db.execute(
                        """UPDATE token_usage_daily SET
                             input_tokens = input_tokens + ?,
                             output_tokens = output_tokens + ?,
                             cache_read_tokens = cache_read_tokens + ?,
                             cache_write_tokens = cache_write_tokens + ?,
                             message_count = message_count + ?
                           WHERE agent_id = ? AND date = ? AND model = ?""",
                        (
                            usage.get("input_tokens", 0),
                            usage.get("output_tokens", 0),
                            usage.get("cache_read_tokens", 0),
                            usage.get("cache_write_tokens", 0),
                            usage.get("message_count", 0),
                            agent_id, date_str, model,
                        ),
                    )
                else:
                    await self._db.execute(
                        """INSERT INTO token_usage_daily
                           (agent_id, date, model, input_tokens, output_tokens,
                            cache_read_tokens, cache_write_tokens, message_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            agent_id, date_str, model,
                            usage.get("input_tokens", 0),
                            usage.get("output_tokens", 0),
                            usage.get("cache_read_tokens", 0),
                            usage.get("cache_write_tokens", 0),
                            usage.get("message_count", 0),
                        ),
                    )
        await self._db.commit()

    async def get_agent_usage(self, agent_id: str) -> dict:
        """Get aggregated token usage for an agent.

        Returns:
            {
                "today": {totals},
                "lifetime": {totals},
                "by_model": {model: {totals}},
                "daily_totals": [{date, totals}, ...],
            }
        """
        from datetime import datetime, timezone
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch all daily rows for this agent
        async with self._db.execute(
            """SELECT date, model, input_tokens, output_tokens,
                      cache_read_tokens, cache_write_tokens, message_count
               FROM token_usage_daily
               WHERE agent_id = ?
               ORDER BY date""",
            (agent_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        lifetime = {
            "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "message_count": 0,
        }
        today = dict(lifetime)
        by_model = {}
        daily_map = {}  # date -> {totals}

        for row in rows:
            row = dict(row)
            date_str = row["date"]
            model = row["model"]

            for key in ("input_tokens", "output_tokens",
                        "cache_read_tokens", "cache_write_tokens",
                        "message_count"):
                val = row[key]
                lifetime[key] += val

                if date_str == today_str:
                    today[key] += val

                if model not in by_model:
                    by_model[model] = {
                        "input_tokens": 0, "output_tokens": 0,
                        "cache_read_tokens": 0, "cache_write_tokens": 0,
                        "message_count": 0,
                    }
                by_model[model][key] += val

                if date_str not in daily_map:
                    daily_map[date_str] = {
                        "date": date_str,
                        "input_tokens": 0, "output_tokens": 0,
                        "cache_read_tokens": 0, "cache_write_tokens": 0,
                        "message_count": 0,
                    }
                daily_map[date_str][key] += val

        daily_totals = sorted(daily_map.values(), key=lambda d: d["date"])

        return {
            "today": today,
            "lifetime": lifetime,
            "by_model": by_model,
            "daily_totals": daily_totals,
        }

    # ── Schedule methods ──

    async def create_schedule(self, agent_id: str, interval_hours: float, prompt: str,
                              last_dispatched_at: float = None) -> dict:
        async with self._db.execute(
            "INSERT INTO schedules (agent_id, interval_hours, prompt, last_dispatched_at) VALUES (?, ?, ?, ?)",
            (agent_id, interval_hours, prompt, last_dispatched_at),
        ) as cursor:
            sched_id = cursor.lastrowid
        await self._db.commit()
        return await self.get_schedule(sched_id)

    async def seed_schedule(self, agent_id: str, interval_hours: float, prompt: str,
                            last_dispatched_at: float = None) -> Optional[dict]:
        """Create a schedule only if the agent has no existing schedules
        AND the schedule was not previously deleted by a user.

        Used on daemon startup to seed agents.yaml schedules into DB.
        Returns the new schedule if created, None if agent already has one
        or if the schedule was previously deleted.
        """
        existing = await self.get_agent_schedules(agent_id)
        if existing:
            return None

        # Check if this specific schedule was previously deleted
        import hashlib
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        async with self._db.execute(
            "SELECT 1 FROM deleted_schedules WHERE agent_id = ? AND prompt_hash = ?",
            (agent_id, prompt_hash),
        ) as cursor:
            if await cursor.fetchone():
                logger.debug(
                    "Skipping seed for %s: schedule was previously deleted", agent_id
                )
                return None

        return await self.create_schedule(agent_id, interval_hours, prompt,
                                          last_dispatched_at=last_dispatched_at)

    async def get_schedule(self, schedule_id: int) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_agent_schedules(self, agent_id: str) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM schedules WHERE agent_id = ? ORDER BY id", (agent_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_all_schedules(self) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM schedules ORDER BY agent_id, id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def delete_schedule(self, schedule_id: int) -> bool:
        # Fetch the schedule before deleting so we can record it
        schedule = await self.get_schedule(schedule_id)
        async with self._db.execute(
            "DELETE FROM schedules WHERE id = ?", (schedule_id,)
        ) as cursor:
            deleted = cursor.rowcount > 0
        if deleted and schedule:
            # Record deletion so seed_schedule won't recreate it on restart
            import hashlib
            prompt_hash = hashlib.sha256(schedule["prompt"].encode()).hexdigest()[:16]
            await self._db.execute(
                "INSERT OR REPLACE INTO deleted_schedules (agent_id, prompt_hash) VALUES (?, ?)",
                (schedule["agent_id"], prompt_hash),
            )
        await self._db.commit()
        return deleted

    async def update_schedule_dispatched(self, schedule_id: int, timestamp: float):
        await self._db.execute(
            "UPDATE schedules SET last_dispatched_at = ? WHERE id = ?",
            (timestamp, schedule_id),
        )
        await self._db.commit()

    async def get_all_agents_usage_summary(self) -> list[dict]:
        """Get usage summary for all agents (for dashboard)."""
        from datetime import datetime, timezone
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async with self._db.execute(
            """SELECT agent_id,
                      SUM(input_tokens) as total_input,
                      SUM(output_tokens) as total_output,
                      SUM(cache_read_tokens) as total_cache_read,
                      SUM(cache_write_tokens) as total_cache_write,
                      SUM(message_count) as total_messages
               FROM token_usage_daily
               GROUP BY agent_id
               ORDER BY agent_id"""
        ) as cursor:
            lifetime_rows = await cursor.fetchall()

        async with self._db.execute(
            """SELECT agent_id,
                      SUM(input_tokens) as today_input,
                      SUM(output_tokens) as today_output,
                      SUM(cache_read_tokens) as today_cache_read,
                      SUM(cache_write_tokens) as today_cache_write,
                      SUM(message_count) as today_messages
               FROM token_usage_daily
               WHERE date = ?
               GROUP BY agent_id""",
            (today_str,),
        ) as cursor:
            today_rows = await cursor.fetchall()

        today_map = {row["agent_id"]: dict(row) for row in today_rows}

        result = []
        for row in lifetime_rows:
            row = dict(row)
            agent_id = row["agent_id"]
            today_data = today_map.get(agent_id, {})
            result.append({
                "agent_id": agent_id,
                "lifetime": {
                    "input_tokens": row["total_input"],
                    "output_tokens": row["total_output"],
                    "cache_read_tokens": row["total_cache_read"],
                    "cache_write_tokens": row["total_cache_write"],
                    "message_count": row["total_messages"],
                },
                "today": {
                    "input_tokens": today_data.get("today_input", 0),
                    "output_tokens": today_data.get("today_output", 0),
                    "cache_read_tokens": today_data.get("today_cache_read", 0),
                    "cache_write_tokens": today_data.get("today_cache_write", 0),
                    "message_count": today_data.get("today_messages", 0),
                },
            })

        return result

    # ── Dispatch event logging ──

    async def log_dispatch_event(
        self, agent_id: str, trigger_type: str, message: str = ""
    ) -> int:
        """Log a dispatch event.

        Args:
            agent_id: Target agent that was dispatched.
            trigger_type: One of 'periodic', 'reassign', 'deferred', 'staleness',
                         'unattended', 'messages', 'schedule', 'manual'.
            message: Human-readable description of what happened.

        Returns:
            The event ID.
        """
        async with self._db.execute(
            "INSERT INTO dispatch_events (agent_id, trigger_type, message) VALUES (?, ?, ?)",
            (agent_id, trigger_type, message),
        ) as cursor:
            event_id = cursor.lastrowid
        await self._db.commit()

        # Auto-cleanup: keep only the most recent events per agent
        await self._db.execute(
            """DELETE FROM dispatch_events
               WHERE agent_id = ? AND id NOT IN (
                   SELECT id FROM dispatch_events
                   WHERE agent_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?
               )""",
            (agent_id, agent_id, _MAX_DISPATCH_EVENTS_PER_AGENT),
        )
        await self._db.commit()
        return event_id

    async def get_dispatch_events(
        self,
        agent_id: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Get dispatch events, optionally filtered by agent.

        Returns:
            {"events": [...], "total": N}
        """
        if agent_id:
            where = "WHERE agent_id = ?"
            params: list = [agent_id]
        else:
            where = ""
            params = []

        async with self._db.execute(
            f"SELECT COUNT(*) FROM dispatch_events {where}", params
        ) as cursor:
            total = (await cursor.fetchone())[0]

        async with self._db.execute(
            f"SELECT * FROM dispatch_events {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cursor:
            rows = await cursor.fetchall()

        return {
            "events": [dict(r) for r in rows],
            "total": total,
        }

    # ── Pub/Sub: Subscriber methods ──

    async def subscribe(self, ticket_id: int, agent_id: str) -> bool:
        """Subscribe an agent to a ticket. Idempotent (INSERT OR IGNORE).

        Returns True if a new subscription was created, False if already existed.
        """
        async with self._db.execute(
            "INSERT OR IGNORE INTO ticket_subscribers (ticket_id, agent_id) VALUES (?, ?)",
            (ticket_id, agent_id),
        ) as cursor:
            created = cursor.rowcount > 0
        await self._db.commit()
        return created

    async def unsubscribe(self, ticket_id: int, agent_id: str) -> bool:
        """Unsubscribe an agent from a ticket. Returns True if removed."""
        async with self._db.execute(
            "DELETE FROM ticket_subscribers WHERE ticket_id = ? AND agent_id = ?",
            (ticket_id, agent_id),
        ) as cursor:
            removed = cursor.rowcount > 0
        await self._db.commit()
        return removed

    async def get_subscribers(self, ticket_id: int) -> list[str]:
        """Get all agent_ids subscribed to a ticket."""
        async with self._db.execute(
            "SELECT agent_id FROM ticket_subscribers WHERE ticket_id = ? ORDER BY agent_id",
            (ticket_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [row["agent_id"] for row in rows]

    async def get_subscriptions(self, agent_id: str) -> list[int]:
        """Get all ticket_ids an agent is subscribed to."""
        async with self._db.execute(
            "SELECT ticket_id FROM ticket_subscribers WHERE agent_id = ? ORDER BY ticket_id",
            (agent_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [row["ticket_id"] for row in rows]

    # ── Pub/Sub: Notification methods ──

    async def create_notification(
        self,
        agent_id: str,
        type: str,
        title: str,
        ticket_id: int = None,
        source_agent_id: str = None,
        body: str = "",
    ) -> int:
        """Create a notification for an agent. Returns notification id.

        Auto-cleans old notifications beyond _MAX_NOTIFICATIONS_PER_AGENT.
        """
        async with self._db.execute(
            """INSERT INTO notifications
               (agent_id, ticket_id, type, source_agent_id, title, body)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (agent_id, ticket_id, type, source_agent_id, title, body),
        ) as cursor:
            notif_id = cursor.lastrowid
        await self._db.commit()

        # Auto-cleanup: keep only the most recent notifications per agent
        await self._db.execute(
            """DELETE FROM notifications
               WHERE agent_id = ? AND id NOT IN (
                   SELECT id FROM notifications
                   WHERE agent_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?
               )""",
            (agent_id, agent_id, _MAX_NOTIFICATIONS_PER_AGENT),
        )
        await self._db.commit()
        return notif_id

    async def get_notifications(
        self,
        agent_id: str,
        state: str = "unread",
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Get notifications for an agent.

        Args:
            state: 'unread', 'read', or 'all'.

        Returns:
            {"notifications": [...], "total": N, "unread_count": N}
        """
        where = "agent_id = ?"
        params: list = [agent_id]
        if state != "all":
            where += " AND state = ?"
            params.append(state)

        async with self._db.execute(
            f"SELECT COUNT(*) FROM notifications WHERE {where}", params
        ) as cursor:
            total = (await cursor.fetchone())[0]

        async with self._db.execute(
            "SELECT COUNT(*) FROM notifications WHERE agent_id = ? AND state = 'unread'",
            (agent_id,),
        ) as cursor:
            unread_count = (await cursor.fetchone())[0]

        async with self._db.execute(
            f"""SELECT * FROM notifications WHERE {where}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ) as cursor:
            rows = await cursor.fetchall()

        return {
            "notifications": [dict(r) for r in rows],
            "total": total,
            "unread_count": unread_count,
        }

    async def mark_notifications_read(
        self, agent_id: str, notification_ids: list[int]
    ) -> int:
        """Mark notifications as read. Returns count updated."""
        if not notification_ids:
            return 0
        placeholders = ", ".join("?" for _ in notification_ids)
        async with self._db.execute(
            f"""UPDATE notifications
                SET state = 'read', read_at = datetime('now')
                WHERE agent_id = ? AND id IN ({placeholders})""",
            [agent_id] + notification_ids,
        ) as cursor:
            count = cursor.rowcount
        await self._db.commit()
        return count

    async def get_unread_notification_count(self, agent_id: str) -> int:
        """Get count of unread notifications for an agent."""
        async with self._db.execute(
            "SELECT COUNT(*) FROM notifications WHERE agent_id = ? AND state = 'unread'",
            (agent_id,),
        ) as cursor:
            return (await cursor.fetchone())[0]

    # ── Service lock methods ──

    async def acquire_lock(
        self, service_id: str, agent_id: str, ttl_seconds: int = 300
    ) -> dict:
        """Try to acquire an advisory lock on a singleton service.

        Expired locks are automatically reclaimed.

        Returns:
            {"acquired": bool, "holder": str, "expires_at": str}
        """
        # First, delete expired lock for this service
        await self._db.execute(
            "DELETE FROM service_locks WHERE service_id = ? AND expires_at < datetime('now')",
            (service_id,),
        )
        await self._db.commit()

        expires_at = f"datetime('now', '+{ttl_seconds} seconds')"
        try:
            await self._db.execute(
                f"""INSERT INTO service_locks (service_id, agent_id, expires_at)
                    VALUES (?, ?, {expires_at})""",
                (service_id, agent_id),
            )
            await self._db.commit()
            # Fetch the actual expires_at value
            async with self._db.execute(
                "SELECT expires_at FROM service_locks WHERE service_id = ?",
                (service_id,),
            ) as cursor:
                row = await cursor.fetchone()
            return {"acquired": True, "holder": agent_id, "expires_at": row["expires_at"]}
        except Exception:
            # Lock already held — fetch the current holder
            async with self._db.execute(
                "SELECT agent_id, expires_at FROM service_locks WHERE service_id = ?",
                (service_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                return {"acquired": False, "holder": row["agent_id"], "expires_at": row["expires_at"]}
            # Race condition: lock was released between our check and insert
            return {"acquired": False, "holder": "unknown", "expires_at": ""}

    async def release_lock(self, service_id: str, agent_id: str) -> bool:
        """Release a lock held by agent_id. Returns True if released."""
        async with self._db.execute(
            "DELETE FROM service_locks WHERE service_id = ? AND agent_id = ?",
            (service_id, agent_id),
        ) as cursor:
            released = cursor.rowcount > 0
        await self._db.commit()
        return released

    async def list_locks(self) -> list[dict]:
        """List all active (non-expired) service locks."""
        async with self._db.execute(
            """SELECT service_id, agent_id, acquired_at, expires_at
               FROM service_locks
               WHERE expires_at >= datetime('now')
               ORDER BY acquired_at"""
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def cleanup_expired_locks(self) -> int:
        """Remove expired locks. Returns count removed."""
        async with self._db.execute(
            "DELETE FROM service_locks WHERE expires_at < datetime('now')"
        ) as cursor:
            count = cursor.rowcount
        if count:
            await self._db.commit()
        return count
