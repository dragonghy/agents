"""FastMCP server exposing WeChat tools (read + send via osascript)."""
from __future__ import annotations

import logging

from fastmcp import FastMCP

from .ratelimit import RateLimiter
from .reader import (
    ReadError,
    list_recent_chats,
    read_chat_messages,
    search_loaded_messages,
)
from .sender import send_wechat_message

logger = logging.getLogger(__name__)

mcp = FastMCP("wechat-mcp")
_rate_limiter = RateLimiter()


def _err(message: str, **extra) -> dict:
    out = {"error": message}
    out.update(extra)
    return out


@mcp.tool()
def wechat_list_chats(limit: int = 20) -> dict:
    """Return the most-recently-active WeChat conversations.

    Each entry has ``name`` (use this string when calling ``wechat_get_chat``
    or ``wechat_send``) and a best-effort ``preview`` of the last message.
    ``unread`` is reported as ``null`` — WeChat for Mac doesn't expose that
    cleanly via Accessibility in v1.

    Requires WeChat for Mac running and Accessibility permission granted to
    the host terminal process. See ``--check`` for diagnostics.
    """
    if limit <= 0 or limit > 100:
        return _err("limit must be between 1 and 100")
    res = list_recent_chats(limit=limit)
    if isinstance(res, ReadError):
        return res.to_dict()
    return {"chats": [c.to_dict() for c in res]}


@mcp.tool()
def wechat_get_chat(chat_name: str, limit: int = 50) -> dict:
    """Return up to ``limit`` recent messages from the chat named ``chat_name``.

    ``chat_name`` is the contact / group name as displayed in the WeChat
    sidebar. The conversation switcher is opened via Cmd+F and the top
    match is selected — if multiple chats share a name, the most-active
    one wins. Disambiguate at the agent layer if that matters.

    Messages returned are oldest-first (top of the visible scrollback to
    bottom). Only currently-rendered messages are returned; the server does
    not auto-scroll to load more history.
    """
    if not chat_name:
        return _err("chat_name is required")
    if limit <= 0 or limit > 200:
        return _err("limit must be between 1 and 200")
    res = read_chat_messages(chat_name=chat_name, limit=limit)
    if isinstance(res, ReadError):
        return res.to_dict()
    return {"chat_name": chat_name, "messages": [m.to_dict() for m in res]}


@mcp.tool()
def wechat_search(
    query: str,
    chat_names: list[str] | None = None,
    limit: int = 20,
) -> dict:
    """Search messages from one or more chats for a case-insensitive substring.

    Pass an explicit ``chat_names`` list to restrict the search; if omitted,
    the server pulls from the most-recently-active chats (up to 5) — handy
    for "did anyone mention $TOPIC today" sweeps without the caller needing
    to enumerate.

    The server does not maintain its own message cache: each call pulls
    fresh data via the same UI scrape that ``wechat_get_chat`` uses. That
    keeps the server stateless but means search across many chats is slow
    (~1s per chat). Keep ``chat_names`` short for interactive use.
    """
    if not query or not query.strip():
        return _err("query is required")
    if limit <= 0 or limit > 200:
        return _err("limit must be between 1 and 200")

    if not chat_names:
        recent = list_recent_chats(limit=5)
        if isinstance(recent, ReadError):
            return recent.to_dict()
        chat_names = [c.name for c in recent]

    chats: list[tuple[str, list]] = []
    for name in chat_names:
        msgs = read_chat_messages(chat_name=name, limit=50)
        if isinstance(msgs, ReadError):
            # Skip chats we couldn't open; keep going so a single failure
            # doesn't blow up the whole sweep.
            logger.warning("search: failed to read %s: %s", name, msgs.message)
            continue
        chats.append((name, msgs))

    results = search_loaded_messages(chats, query=query.strip(), limit=limit)
    return {
        "query": query,
        "searched_chats": [n for n, _ in chats],
        "results": results,
    }


@mcp.tool()
def wechat_send(chat_name: str, body: str) -> dict:
    """Send a plain-text message to ``chat_name``.

    The send is rate-limited (≥3s per same chat, ≤20/minute global) to keep
    behaviour close to a human typist — WeChat's anti-spam is the most
    plausible failure mode for an automated client.

    Returns ``ok: True`` only if osascript ran without error. The message
    *appearing* in the chat is the strongest signal; for high-stakes sends
    the agent should follow up with ``wechat_get_chat`` and verify the
    body shows up at the tail.
    """
    if not chat_name:
        return _err("chat_name is required")
    if not body:
        return _err("body is required")

    allowed, reason = _rate_limiter.check(chat_name)
    if not allowed:
        return _err(reason, rate_limited=True)

    res = send_wechat_message(chat_name=chat_name, body=body)
    if res.ok:
        _rate_limiter.record(chat_name)
    return res.to_dict()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    mcp.run()
