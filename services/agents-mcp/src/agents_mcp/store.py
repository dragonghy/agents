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

    async def get_conversation_threads(self) -> list[dict]:
        """Get unique conversation pairs with latest message info."""
        async with self._db.execute(
            """SELECT
                 CASE WHEN from_agent < to_agent THEN from_agent ELSE to_agent END AS agent_a,
                 CASE WHEN from_agent < to_agent THEN to_agent ELSE from_agent END AS agent_b,
                 MAX(created_at) AS last_message_at,
                 COUNT(*) AS message_count
               FROM messages
               GROUP BY agent_a, agent_b
               ORDER BY last_message_at DESC"""
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
