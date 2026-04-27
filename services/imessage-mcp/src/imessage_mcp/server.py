"""FastMCP server exposing iMessage tools."""
from __future__ import annotations

import logging

from fastmcp import FastMCP

from .db import (
    ChatDbUnavailableError,
    get_chat_messages,
    list_chats,
    open_readonly,
    search_messages,
    unread_messages,
)
from .sender import send_imessage

logger = logging.getLogger(__name__)

mcp = FastMCP("imessage-mcp")


def _err(message: str) -> dict:
    return {"error": message}


@mcp.tool()
def imessage_list_chats(limit: int = 20) -> dict:
    """Return the `limit` most-recently-active iMessage / SMS conversations.

    Each entry includes the chat identifier, display name, last-message preview,
    last-message timestamp, unread count, and whether it's a 1:1 or group chat.
    """
    if limit <= 0 or limit > 200:
        return _err("limit must be between 1 and 200")
    try:
        with open_readonly() as conn:
            chats = list_chats(conn, limit=limit)
    except ChatDbUnavailableError as e:
        return _err(str(e))
    return {"chats": [c.to_dict() for c in chats]}


@mcp.tool()
def imessage_get_chat(handle: str, limit: int = 50) -> dict:
    """Return the most recent `limit` messages for a contact.

    `handle` is a phone number (E.164: '+15551234567'), email, or a group
    chat identifier (e.g. 'chat493929391'). Messages are returned oldest-first.
    """
    if not handle:
        return _err("handle is required")
    if limit <= 0 or limit > 500:
        return _err("limit must be between 1 and 500")
    try:
        with open_readonly() as conn:
            msgs = get_chat_messages(conn, handle, limit=limit)
    except ChatDbUnavailableError as e:
        return _err(str(e))
    return {"handle": handle, "messages": [m.to_dict() for m in msgs]}


@mcp.tool()
def imessage_search(query: str, days: int = 7, limit: int = 100) -> dict:
    """Search recent messages (case-insensitive) within the past `days` days."""
    if not query or not query.strip():
        return _err("query is required")
    if days <= 0 or days > 365:
        return _err("days must be between 1 and 365")
    if limit <= 0 or limit > 500:
        return _err("limit must be between 1 and 500")
    try:
        with open_readonly() as conn:
            msgs = search_messages(conn, query.strip(), days=days, limit=limit)
    except ChatDbUnavailableError as e:
        return _err(str(e))
    return {
        "query": query,
        "days": days,
        "messages": [m.to_dict() for m in msgs],
    }


@mcp.tool()
def imessage_unread() -> dict:
    """Return all unread messages addressed to the user (newest first)."""
    try:
        with open_readonly() as conn:
            msgs = unread_messages(conn, limit=200)
    except ChatDbUnavailableError as e:
        return _err(str(e))
    return {
        "unread_count": len(msgs),
        "messages": [m.to_dict() for m in msgs],
    }


@mcp.tool()
def imessage_send(handle: str, body: str, service: str = "iMessage") -> dict:
    """Send a message to `handle` via Messages.app (osascript bridge).

    `service` is 'iMessage' (default) or 'SMS'. iMessage requires the
    recipient to be on iMessage; SMS requires Continuity (a paired iPhone).
    """
    if not handle:
        return _err("handle is required")
    if not body:
        return _err("body is required")
    if service not in ("iMessage", "SMS"):
        return _err("service must be 'iMessage' or 'SMS'")
    res = send_imessage(handle=handle, body=body, service=service)
    return res.to_dict()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    mcp.run()
