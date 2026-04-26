"""End-to-end DB tests against a synthetic chat.db.

We construct a minimal SQLite database matching the columns used by the
real chat.db and assert that `list_chats`, `get_chat_messages`,
`search_messages`, and `unread_messages` return the expected shapes.

This catches regressions in our SQL without requiring Full Disk Access
or a real macOS chat.db.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from imessage_mcp.db import (
    Chat,
    Message,
    get_chat_messages,
    list_chats,
    open_readonly,
    search_messages,
    unread_messages,
)
from imessage_mcp.epoch import unix_to_apple_ns


@pytest.fixture
def synthetic_db(tmp_path: Path) -> Path:
    """Build a chat.db-shaped SQLite file with two chats and a few messages."""
    db = tmp_path / "chat.db"
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE handle (
          ROWID INTEGER PRIMARY KEY,
          id TEXT,
          service TEXT,
          country TEXT
        );
        CREATE TABLE chat (
          ROWID INTEGER PRIMARY KEY,
          guid TEXT,
          chat_identifier TEXT,
          service_name TEXT,
          display_name TEXT,
          style INTEGER
        );
        CREATE TABLE message (
          ROWID INTEGER PRIMARY KEY,
          guid TEXT,
          text TEXT,
          attributedBody BLOB,
          handle_id INTEGER,
          service TEXT,
          date INTEGER,
          is_from_me INTEGER,
          is_read INTEGER,
          date_read INTEGER
        );
        CREATE TABLE chat_message_join (
          chat_id INTEGER,
          message_id INTEGER
        );
        CREATE TABLE chat_handle_join (
          chat_id INTEGER,
          handle_id INTEGER
        );
        """
    )
    now = time.time()
    # Two contacts
    cur.execute("INSERT INTO handle VALUES (1, '+15551111111', 'iMessage', 'us')")
    cur.execute("INSERT INTO handle VALUES (2, 'alice@example.com', 'iMessage', 'us')")
    # Two 1:1 chats
    cur.execute(
        "INSERT INTO chat VALUES (1, 'g1', '+15551111111', 'iMessage', '', 1)"
    )
    cur.execute(
        "INSERT INTO chat VALUES (2, 'g2', 'alice@example.com', 'iMessage', 'Alice', 1)"
    )
    cur.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
    cur.execute("INSERT INTO chat_handle_join VALUES (2, 2)")
    # Messages
    rows = [
        # rowid, text, handle_id, date_unix, is_from_me, is_read, chat_id
        (1, "hey there", 1, now - 600, 0, 1, 1),
        (2, "im here", None, now - 590, 1, 1, 1),
        (3, "lunch?", 1, now - 60, 0, 0, 1),  # unread inbound
        (4, "hi alice", None, now - 7200, 1, 1, 2),
        (5, "happy birthday", 2, now - 30, 0, 0, 2),  # unread inbound
    ]
    for rowid, text, handle_id, date_unix, is_from_me, is_read, chat_id in rows:
        cur.execute(
            "INSERT INTO message (ROWID, text, handle_id, service, date, is_from_me, is_read) "
            "VALUES (?, ?, ?, 'iMessage', ?, ?, ?)",
            (rowid, text, handle_id, unix_to_apple_ns(date_unix), is_from_me, is_read),
        )
        cur.execute(
            "INSERT INTO chat_message_join VALUES (?, ?)", (chat_id, rowid)
        )
    conn.commit()
    conn.close()
    return db


def test_list_chats_orders_by_recent(synthetic_db: Path):
    with open_readonly(synthetic_db) as conn:
        chats = list_chats(conn, limit=10)
    assert len(chats) == 2
    # alice (rowid=2) has the most recent message (now-30) so should be first.
    assert chats[0].rowid == 2
    assert chats[0].display_name == "Alice"
    assert chats[0].last_message_preview == "happy birthday"
    assert chats[0].last_from_me is False
    assert chats[0].unread_count == 1
    # second chat
    assert chats[1].rowid == 1
    assert chats[1].chat_identifier == "+15551111111"
    assert chats[1].unread_count == 1


def test_get_chat_by_phone(synthetic_db: Path):
    with open_readonly(synthetic_db) as conn:
        msgs = get_chat_messages(conn, "+15551111111", limit=50)
    assert [m.text for m in msgs] == ["hey there", "im here", "lunch?"]
    # Oldest-first ordering enforced.
    assert msgs[0].date_unix < msgs[-1].date_unix
    assert msgs[0].handle == "+15551111111"
    assert msgs[1].is_from_me is True


def test_get_chat_by_email(synthetic_db: Path):
    with open_readonly(synthetic_db) as conn:
        msgs = get_chat_messages(conn, "alice@example.com", limit=50)
    assert [m.text for m in msgs] == ["hi alice", "happy birthday"]


def test_get_chat_unknown_handle(synthetic_db: Path):
    with open_readonly(synthetic_db) as conn:
        msgs = get_chat_messages(conn, "+19999999999")
    assert msgs == []


def test_search_finds_keyword(synthetic_db: Path):
    with open_readonly(synthetic_db) as conn:
        msgs = search_messages(conn, "lunch", days=1)
    assert len(msgs) == 1
    assert msgs[0].text == "lunch?"


def test_search_case_insensitive(synthetic_db: Path):
    with open_readonly(synthetic_db) as conn:
        msgs = search_messages(conn, "BIRTHDAY", days=1)
    assert len(msgs) == 1
    assert "birthday" in msgs[0].text.lower()


def test_search_respects_window(synthetic_db: Path):
    with open_readonly(synthetic_db) as conn:
        # date filter cuts to last 0.001 days = ~86s; the "happy birthday"
        # at now-30 is included, "hi alice" at now-7200 is not.
        msgs = search_messages(conn, "hi", days=7)
    assert any("hi alice" in m.text for m in msgs)


def test_unread_only_inbound_unread(synthetic_db: Path):
    with open_readonly(synthetic_db) as conn:
        msgs = unread_messages(conn)
    assert len(msgs) == 2
    # Both unread messages are inbound.
    assert all(m.is_from_me is False for m in msgs)
    assert all(m.is_read is False for m in msgs)
    texts = {m.text for m in msgs}
    assert texts == {"lunch?", "happy birthday"}
    # Newest first.
    assert msgs[0].date_unix > msgs[1].date_unix
