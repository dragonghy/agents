"""Read-only access to ~/Library/Messages/chat.db.

This module never writes to chat.db. The connection is opened with the
`mode=ro` URI flag, which is enforced by SQLite at the C layer.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .decoder import decode_attributed_body
from .epoch import apple_ns_to_unix

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def default_chat_db_path() -> Path:
    """Return the canonical chat.db location.

    Override with IMESSAGE_CHAT_DB env var (used by tests).
    """
    env = os.environ.get("IMESSAGE_CHAT_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Library" / "Messages" / "chat.db"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ChatDbUnavailableError(RuntimeError):
    """chat.db couldn't be opened. Most likely Full Disk Access missing."""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
@dataclass
class Message:
    rowid: int
    chat_id: int
    text: str
    is_from_me: bool
    date_unix: float
    handle: str | None  # None when sent by self
    service: str  # "iMessage", "SMS"
    is_read: bool
    decode_failed: bool = False

    def to_dict(self) -> dict:
        return {
            "rowid": self.rowid,
            "chat_id": self.chat_id,
            "text": self.text,
            "is_from_me": self.is_from_me,
            "date_unix": self.date_unix,
            "handle": self.handle,
            "service": self.service,
            "is_read": self.is_read,
            "decode_failed": self.decode_failed,
        }


@dataclass
class Chat:
    rowid: int
    chat_identifier: str  # phone/email for 1:1, "chat<n>" for groups
    display_name: str
    style: int  # 1 = 1:1, 43 = group
    service_name: str  # "iMessage" / "SMS"
    last_message_unix: float | None
    last_message_preview: str | None
    last_from_me: bool | None
    handles: list[str] = field(default_factory=list)
    unread_count: int = 0

    @property
    def is_group(self) -> bool:
        return self.style == 43

    def to_dict(self) -> dict:
        return {
            "rowid": self.rowid,
            "chat_identifier": self.chat_identifier,
            "display_name": self.display_name,
            "is_group": self.is_group,
            "service": self.service_name,
            "last_message_unix": self.last_message_unix,
            "last_message_preview": self.last_message_preview,
            "last_from_me": self.last_from_me,
            "handles": self.handles,
            "unread_count": self.unread_count,
        }


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
@contextmanager
def open_readonly(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = (path or default_chat_db_path()).resolve()
    if not db_path.exists():
        raise ChatDbUnavailableError(
            f"chat.db not found at {db_path}. "
            "On macOS, ensure Messages.app has been opened at least once."
        )
    # mode=ro: SQLite refuses any write. immutable=1 disables WAL recovery
    # which we don't want — readers should still see committed writes.
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.OperationalError as e:
        raise ChatDbUnavailableError(
            f"Failed to open chat.db at {db_path}: {e}. "
            "If you see 'unable to open database file', the host process "
            "lacks Full Disk Access. See services/imessage-mcp/README.md."
        ) from e
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Row -> Message
# ---------------------------------------------------------------------------
def _row_to_message(row: sqlite3.Row, chat_id: int | None = None) -> Message:
    text = row["text"]
    decode_failed = False
    if not text:
        # iOS 14+ stores rich text in attributedBody only.
        body = row["attributedBody"]
        if body:
            decoded = decode_attributed_body(body)
            if decoded is None:
                decode_failed = True
                text = "(unable to decode message body)"
            else:
                text = decoded
        else:
            text = ""
    return Message(
        rowid=row["ROWID"],
        chat_id=chat_id if chat_id is not None else (row["chat_id"] if "chat_id" in row.keys() else 0),
        text=text or "",
        is_from_me=bool(row["is_from_me"]),
        date_unix=apple_ns_to_unix(row["date"]) if row["date"] else 0.0,
        handle=row["handle_id_str"] if "handle_id_str" in row.keys() else None,
        service=row["service"] or "iMessage",
        is_read=bool(row["is_read"]),
        decode_failed=decode_failed,
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def list_chats(conn: sqlite3.Connection, limit: int = 20) -> list[Chat]:
    """Return the `limit` most-recently-active chats."""
    sql = """
    SELECT
      c.ROWID                  AS rowid,
      c.chat_identifier        AS chat_identifier,
      COALESCE(c.display_name, '') AS display_name,
      c.style                  AS style,
      c.service_name           AS service_name,
      MAX(m.date)              AS last_date,
      (
        SELECT m2.ROWID FROM message m2
        JOIN chat_message_join cmj2 ON cmj2.message_id = m2.ROWID
        WHERE cmj2.chat_id = c.ROWID
        ORDER BY m2.date DESC LIMIT 1
      ) AS last_msg_rowid
    FROM chat c
    JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
    JOIN message m            ON m.ROWID = cmj.message_id
    GROUP BY c.ROWID
    ORDER BY last_date DESC
    LIMIT ?;
    """
    rows = conn.execute(sql, (limit,)).fetchall()
    chats: list[Chat] = []
    for r in rows:
        # Fetch last-message preview + sender flag.
        last_preview = None
        last_from_me = None
        if r["last_msg_rowid"]:
            mrow = conn.execute(
                "SELECT ROWID, text, attributedBody, is_from_me, date, handle_id, "
                "service, is_read FROM message WHERE ROWID = ?",
                (r["last_msg_rowid"],),
            ).fetchone()
            if mrow:
                # Build a synthetic row dict for _row_to_message convenience.
                body = mrow["text"]
                if not body and mrow["attributedBody"]:
                    decoded = decode_attributed_body(mrow["attributedBody"])
                    body = decoded or "(unable to decode)"
                last_preview = (body or "")[:140]
                last_from_me = bool(mrow["is_from_me"])

        # Fetch handles for this chat.
        handle_rows = conn.execute(
            "SELECT h.id FROM handle h "
            "JOIN chat_handle_join chj ON chj.handle_id = h.ROWID "
            "WHERE chj.chat_id = ?",
            (r["rowid"],),
        ).fetchall()
        handles = [hr["id"] for hr in handle_rows if hr["id"]]

        # Unread count: messages where is_from_me=0 AND is_read=0 in this chat.
        unread_row = conn.execute(
            "SELECT COUNT(*) AS n FROM message m "
            "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
            "WHERE cmj.chat_id = ? AND m.is_from_me = 0 AND m.is_read = 0",
            (r["rowid"],),
        ).fetchone()
        unread = int(unread_row["n"]) if unread_row else 0

        chats.append(
            Chat(
                rowid=r["rowid"],
                chat_identifier=r["chat_identifier"] or "",
                display_name=r["display_name"] or "",
                style=int(r["style"] or 0),
                service_name=r["service_name"] or "iMessage",
                last_message_unix=apple_ns_to_unix(r["last_date"]) if r["last_date"] else None,
                last_message_preview=last_preview,
                last_from_me=last_from_me,
                handles=handles,
                unread_count=unread,
            )
        )
    return chats


def _resolve_chat_ids_by_handle(conn: sqlite3.Connection, handle: str) -> list[int]:
    """Return chat ROWIDs whose membership includes `handle`.

    Matches both phone-number and email handles. Falls back to
    chat_identifier match (in case the caller passes a chat-level identifier
    or a group "chat<NNN>" id).
    """
    rows = conn.execute(
        """
        SELECT DISTINCT c.ROWID AS rowid
        FROM chat c
        LEFT JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
        LEFT JOIN handle h ON h.ROWID = chj.handle_id
        WHERE h.id = ? OR c.chat_identifier = ?
        """,
        (handle, handle),
    ).fetchall()
    return [r["rowid"] for r in rows]


def get_chat_messages(
    conn: sqlite3.Connection, handle: str, limit: int = 50
) -> list[Message]:
    """Return the most-recent `limit` messages with `handle`, oldest-first."""
    chat_ids = _resolve_chat_ids_by_handle(conn, handle)
    if not chat_ids:
        return []
    placeholders = ",".join("?" for _ in chat_ids)
    sql = f"""
    SELECT m.ROWID, m.text, m.attributedBody, m.is_from_me, m.date,
           m.handle_id, h.id AS handle_id_str, m.service, m.is_read,
           cmj.chat_id AS chat_id
    FROM message m
    JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
    LEFT JOIN handle h ON h.ROWID = m.handle_id
    WHERE cmj.chat_id IN ({placeholders})
    ORDER BY m.date DESC
    LIMIT ?;
    """
    rows = conn.execute(sql, (*chat_ids, limit)).fetchall()
    msgs = [_row_to_message(r) for r in rows]
    msgs.reverse()  # oldest-first for readability
    return msgs


def search_messages(
    conn: sqlite3.Connection, query: str, days: int = 7, limit: int = 100
) -> list[Message]:
    """Case-insensitive LIKE search across the past `days` days."""
    if not query:
        return []
    # Apple ns since 2001-01-01 of the cutoff.
    import time as _t

    cutoff_unix = _t.time() - days * 86400
    cutoff_apple_ns = int((cutoff_unix - 978_307_200) * 1_000_000_000)
    like = f"%{query}%"
    sql = """
    SELECT m.ROWID, m.text, m.attributedBody, m.is_from_me, m.date,
           m.handle_id, h.id AS handle_id_str, m.service, m.is_read,
           cmj.chat_id AS chat_id
    FROM message m
    JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
    LEFT JOIN handle h ON h.ROWID = m.handle_id
    WHERE m.date >= ?
      AND (
        m.text LIKE ? COLLATE NOCASE
        OR m.attributedBody IS NOT NULL  -- fallback: scan in Python below
      )
    ORDER BY m.date DESC
    LIMIT ?;
    """
    rows = conn.execute(sql, (cutoff_apple_ns, like, limit * 4)).fetchall()
    out: list[Message] = []
    q_lower = query.lower()
    for r in rows:
        msg = _row_to_message(r)
        if q_lower in msg.text.lower():
            out.append(msg)
            if len(out) >= limit:
                break
    return out


def unread_messages(conn: sqlite3.Connection, limit: int = 50) -> list[Message]:
    """Return messages where is_from_me=0 AND is_read=0, newest-first."""
    sql = """
    SELECT m.ROWID, m.text, m.attributedBody, m.is_from_me, m.date,
           m.handle_id, h.id AS handle_id_str, m.service, m.is_read,
           cmj.chat_id AS chat_id
    FROM message m
    JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
    LEFT JOIN handle h ON h.ROWID = m.handle_id
    WHERE m.is_from_me = 0 AND m.is_read = 0
    ORDER BY m.date DESC
    LIMIT ?;
    """
    rows = conn.execute(sql, (limit,)).fetchall()
    return [_row_to_message(r) for r in rows]
