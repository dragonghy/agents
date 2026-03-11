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
"""


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
