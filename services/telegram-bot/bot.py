"""Telegram Bot Service: channel adapter for the orchestration v1 model.

This is a thin, always-running process with NO AI logic. It bridges Telegram
chats to the daemon's orchestration session model:

Inbound (Human → daemon):
  1. Telegram update arrives → extract chat_id, build channel_id "telegram:<chat_id>".
  2. GET /api/v1/orchestration/sessions?channel_id=...&status=active to find an
     active human-channel session for this chat. Newest active session wins.
  3. If found → POST /api/v1/orchestration/sessions/<id>/messages with the body.
  4. If none → POST /api/v1/orchestration/sessions to spawn a new secretary
     session bound to this channel, then POST messages with the body.

Outbound (daemon → Human):
  Subscribes to GET /api/v1/orchestration/events (SSE). On
  ``session.message_appended`` events with role=assistant whose session is
  bound to ``telegram:<chat_id>``, sends ``payload.text`` back via the
  Telegram sendMessage API. Auto-reconnects with exponential backoff (max 60s)
  and replays via Last-Event-ID so dropped events recover gracefully.

Slash commands preserved from the legacy bot:
  /start, /brief, /status, /list, /new, /profile <name>, /session <id>, /help

Setup:
  1. Create a bot via @BotFather; save the token to .env as TELEGRAM_BOT_TOKEN.
  2. Get your Telegram user id (send /start to @userinfobot); save as
     TELEGRAM_HUMAN_CHAT_ID in .env (legacy alias) — this also becomes the
     allow-listed chat the bot will respond to.
  3. Run: uv run python bot.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Optional

import aiohttp


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
HUMAN_CHAT_ID = os.environ.get("TELEGRAM_HUMAN_CHAT_ID", "")
DAEMON_URL = os.environ.get("DAEMON_URL", "http://127.0.0.1:8765").rstrip("/")
DEFAULT_PROFILE = os.environ.get("DEFAULT_PROFILE", "secretary")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# SSE reconnect bounds — exponential backoff capped at 60s, matches the
# replay-buffer assumptions on the daemon side.
SSE_MIN_BACKOFF = 1.0
SSE_MAX_BACKOFF = 60.0


# ── Telegram I/O helpers ─────────────────────────────────────────────────


async def send_telegram(
    chat_id: str,
    text: str,
    session: aiohttp.ClientSession,
) -> None:
    """Send a message to a Telegram chat (4096-char chunked, markdown-safe).

    Telegram limits messages to 4096 chars; we chunk at 4000 to leave room.
    Markdown is best-effort: if Telegram rejects with a parse error we retry
    once without markdown. All failures are logged but never raise — the bot
    must keep running through transient Telegram outages.
    """
    if not text:
        return
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            async with session.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Telegram send failed: {resp.status} {body}")
                    if "can't parse" in body.lower():
                        async with session.post(
                            f"{TELEGRAM_API}/sendMessage",
                            json={"chat_id": chat_id, "text": chunk},
                        ) as resp2:
                            if resp2.status != 200:
                                logger.error(
                                    f"Telegram send retry failed: "
                                    f"{await resp2.text()}"
                                )
        except aiohttp.ClientError as e:
            logger.error(f"Telegram send transport error: {e}")


# ── Daemon orchestration helpers ─────────────────────────────────────────


def _channel_id_for_chat(chat_id: str) -> str:
    """Return the daemon-side channel_id for a Telegram chat."""
    return f"telegram:{chat_id}"


def _chat_id_from_channel_id(channel_id: Optional[str]) -> Optional[str]:
    """Inverse of :func:`_channel_id_for_chat`. Returns None if not telegram:."""
    if not channel_id or not channel_id.startswith("telegram:"):
        return None
    return channel_id[len("telegram:"):] or None


async def find_active_session(
    chat_id: str,
    session: aiohttp.ClientSession,
) -> Optional[dict]:
    """Return the newest active human-channel session for this Telegram chat.

    The daemon orders by ``created_at DESC`` so the first row is the newest.
    Returns ``None`` if no active session exists (caller will spawn one).
    """
    channel_id = _channel_id_for_chat(chat_id)
    try:
        async with session.get(
            f"{DAEMON_URL}/api/v1/orchestration/sessions",
            params={"channel_id": channel_id, "status": "active", "limit": 1},
        ) as resp:
            if resp.status != 200:
                logger.warning(
                    f"find_active_session: unexpected status {resp.status} "
                    f"for {channel_id}: {await resp.text()}"
                )
                return None
            data = await resp.json()
    except aiohttp.ClientError as e:
        logger.error(f"find_active_session transport error: {e}")
        return None

    sessions = data.get("sessions") or []
    return sessions[0] if sessions else None


async def spawn_session(
    chat_id: str,
    profile_name: str,
    session: aiohttp.ClientSession,
) -> Optional[dict]:
    """Spawn a new human-channel session bound to this Telegram chat.

    Returns the session row dict, or ``None`` on failure.
    """
    channel_id = _channel_id_for_chat(chat_id)
    try:
        async with session.post(
            f"{DAEMON_URL}/api/v1/orchestration/sessions",
            json={
                "profile_name": profile_name,
                "binding_kind": "human-channel",
                "channel_id": channel_id,
            },
        ) as resp:
            if resp.status not in (200, 201):
                logger.error(
                    f"spawn_session failed for {channel_id}: "
                    f"{resp.status} {await resp.text()}"
                )
                return None
            return await resp.json()
    except aiohttp.ClientError as e:
        logger.error(f"spawn_session transport error: {e}")
        return None


async def append_message(
    session_id: str,
    text: str,
    session: aiohttp.ClientSession,
) -> bool:
    """POST a user turn to a session. Fire-and-forget from the bot's POV.

    The Adapter runs an LLM turn; the assistant response will arrive later
    via SSE and the outbound listener will relay it. Returns True if the
    daemon accepted the request (HTTP 200).
    """
    try:
        async with session.post(
            f"{DAEMON_URL}/api/v1/orchestration/sessions/{session_id}/messages",
            json={"text": text},
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status != 200:
                logger.error(
                    f"append_message {session_id}: "
                    f"{resp.status} {await resp.text()}"
                )
                return False
            return True
    except aiohttp.ClientError as e:
        logger.error(f"append_message transport error: {e}")
        return False


async def close_session(
    session_id: str,
    session: aiohttp.ClientSession,
) -> bool:
    """POST /sessions/{id}/close. Idempotent; True on success."""
    try:
        async with session.post(
            f"{DAEMON_URL}/api/v1/orchestration/sessions/{session_id}/close",
        ) as resp:
            return resp.status == 200
    except aiohttp.ClientError as e:
        logger.error(f"close_session transport error: {e}")
        return False


async def list_sessions_for_chat(
    chat_id: str,
    session: aiohttp.ClientSession,
    limit: int = 10,
) -> list[dict]:
    """Return recent sessions for this chat (any status). Newest first."""
    channel_id = _channel_id_for_chat(chat_id)
    try:
        async with session.get(
            f"{DAEMON_URL}/api/v1/orchestration/sessions",
            params={"channel_id": channel_id, "limit": limit},
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("sessions") or []
    except aiohttp.ClientError as e:
        logger.error(f"list_sessions_for_chat transport error: {e}")
        return []


async def get_session_meta(
    session_id: str,
    session: aiohttp.ClientSession,
) -> Optional[dict]:
    """Fetch a session row for the SSE listener's binding lookup."""
    try:
        async with session.get(
            f"{DAEMON_URL}/api/v1/orchestration/sessions/{session_id}",
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except aiohttp.ClientError as e:
        logger.debug(f"get_session_meta transport error: {e}")
        return None


# ── Inbound handler ──────────────────────────────────────────────────────


async def handle_human_message(
    chat_id: str,
    text: str,
    session: aiohttp.ClientSession,
) -> None:
    """Route a free-text Human message into an orchestration session.

    Called for non-slash messages. Looks up the active human-channel
    session for the chat; spawns a new one if none exists; then appends
    the user turn. The assistant reply will arrive later via SSE.
    """
    active = await find_active_session(chat_id, session)
    if active is None:
        logger.info(
            f"No active session for chat {chat_id}; spawning {DEFAULT_PROFILE!r}"
        )
        active = await spawn_session(chat_id, DEFAULT_PROFILE, session)
        if active is None:
            await send_telegram(
                chat_id,
                "Failed to start a session. Please try again in a moment.",
                session,
            )
            return

    session_id = active.get("id")
    if not session_id:
        logger.error(f"Session row missing id: {active}")
        await send_telegram(
            chat_id,
            "Internal error: session row missing id.",
            session,
        )
        return

    ok = await append_message(session_id, text, session)
    if not ok:
        await send_telegram(
            chat_id,
            "Failed to forward your message to the agent. Try again?",
            session,
        )


# ── Slash commands ───────────────────────────────────────────────────────


HELP_TEXT = (
    "🤖 *Agent Harness — channel-adapter mode*\n\n"
    "Send any message and I'll route it to your active agent. "
    "By default that's the Secretary, who handles small things directly "
    "and spawns specialists when needed.\n\n"
    "*Commands:*\n"
    "/brief — Today's Morning Brief\n"
    "/status — System health\n"
    "/list — Recent sessions in this chat\n"
    "/new — Close current session, start fresh with same Profile\n"
    "/profile `<name>` — Switch to a different Profile (closes current)\n"
    "/session `<id>` — (Not yet supported in v1)\n"
    "/help — This message"
)


async def cmd_start(chat_id: str, session: aiohttp.ClientSession) -> None:
    await send_telegram(
        chat_id,
        "🤖 *Agent Harness connected.*\n\n"
        "I'm your channel adapter. Send any message and I'll forward it to "
        "the right agent (Secretary by default).\n\n"
        "Type /help to see all commands.",
        session,
    )


async def cmd_brief(chat_id: str, session: aiohttp.ClientSession) -> None:
    """Fetch today's Morning Brief from the legacy bridge endpoint.

    The orchestration-driven brief delivery (option (b) in the task) is
    handled by the daemon's morning brief loop spawning a secretary session
    automatically; this command is a manual on-demand fetch of the cached
    brief markdown for read-back.
    """
    try:
        async with session.get(f"{DAEMON_URL}/api/v1/brief") as resp:
            if resp.status == 200:
                brief = await resp.text()
                await send_telegram(chat_id, brief, session)
            else:
                await send_telegram(chat_id, "Failed to generate brief.", session)
    except aiohttp.ClientError as e:
        await send_telegram(chat_id, f"Error fetching brief: {e}", session)


async def cmd_status(chat_id: str, session: aiohttp.ClientSession) -> None:
    try:
        async with session.get(f"{DAEMON_URL}/api/v1/health") as resp:
            if resp.status == 200:
                data = await resp.json()
                msg = (
                    f"System: {'✅ OK' if data.get('status') == 'ok' else '❌ Error'}\n"
                    f"Task DB: {'✅' if data.get('task_db') else '❌'}\n"
                    f"TMux: {'✅' if data.get('tmux_active') else '❌'}"
                )
            else:
                msg = f"Health endpoint returned {resp.status}"
    except aiohttp.ClientError as e:
        msg = f"Error: {e}"
    await send_telegram(chat_id, msg, session)


async def cmd_list(chat_id: str, session: aiohttp.ClientSession) -> None:
    sessions = await list_sessions_for_chat(chat_id, session, limit=10)
    if not sessions:
        await send_telegram(chat_id, "No sessions yet for this chat.", session)
        return
    lines = ["*Recent sessions:*"]
    for s in sessions:
        sid = s.get("id", "?")
        profile = s.get("profile_name", "?")
        status = s.get("status", "?")
        created = s.get("created_at", "?")
        lines.append(f"`{sid}` — {profile} — {status} — {created}")
    await send_telegram(chat_id, "\n".join(lines), session)


async def cmd_new(chat_id: str, session: aiohttp.ClientSession) -> None:
    """Close current session, spawn a fresh one with the same Profile."""
    active = await find_active_session(chat_id, session)
    profile = (active or {}).get("profile_name") or DEFAULT_PROFILE
    if active and active.get("id"):
        await close_session(active["id"], session)
    new_row = await spawn_session(chat_id, profile, session)
    if new_row:
        await send_telegram(
            chat_id,
            f"Started a new {profile} session: `{new_row.get('id', '?')}`",
            session,
        )
    else:
        await send_telegram(
            chat_id, f"Failed to spawn new {profile} session.", session
        )


async def cmd_profile(
    chat_id: str,
    arg: str,
    session: aiohttp.ClientSession,
) -> None:
    """Switch to a different Profile — close current, spawn new with given name."""
    profile = arg.strip()
    if not profile:
        await send_telegram(
            chat_id,
            "Usage: `/profile <name>` (e.g. `/profile secretary`)",
            session,
        )
        return
    active = await find_active_session(chat_id, session)
    if active and active.get("id"):
        await close_session(active["id"], session)
    new_row = await spawn_session(chat_id, profile, session)
    if new_row:
        await send_telegram(
            chat_id,
            f"Switched to *{profile}* (session `{new_row.get('id', '?')}`).",
            session,
        )
    else:
        await send_telegram(
            chat_id,
            f"Failed to spawn {profile} session — does that Profile exist?",
            session,
        )


async def cmd_session(
    chat_id: str,
    arg: str,
    session: aiohttp.ClientSession,
) -> None:
    """Resume an old session.

    v1 doesn't support promote-to-active semantics for an old session
    (the daemon doesn't have a "switch active session" endpoint and we'd
    need to either close other actives in the chat or accept multiple
    actives — both have semantics issues). Punt and tell Human to /new.
    """
    del arg  # unused
    await send_telegram(
        chat_id,
        "Session resume not yet supported in v1. Use /new to start fresh, "
        "or /list to view session history.",
        session,
    )


async def cmd_help(chat_id: str, session: aiohttp.ClientSession) -> None:
    await send_telegram(chat_id, HELP_TEXT, session)


# Mapping of slash-command → handler. Keeps handle_updates compact.
SLASH_HANDLERS_NOARG = {
    "/start": cmd_start,
    "/brief": cmd_brief,
    "/status": cmd_status,
    "/list": cmd_list,
    "/new": cmd_new,
    "/help": cmd_help,
}
SLASH_HANDLERS_WITH_ARG = {
    "/profile": cmd_profile,
    "/session": cmd_session,
}


async def dispatch_command(
    chat_id: str,
    text: str,
    session: aiohttp.ClientSession,
) -> bool:
    """If ``text`` is a recognized slash command, handle it and return True.

    Returns False if it's not a slash command (caller routes it to the
    orchestration session).
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return False
    parts = stripped.split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""
    handler_no = SLASH_HANDLERS_NOARG.get(cmd)
    if handler_no is not None:
        await handler_no(chat_id, session)
        return True
    handler_arg = SLASH_HANDLERS_WITH_ARG.get(cmd)
    if handler_arg is not None:
        await handler_arg(chat_id, arg, session)
        return True
    # Unknown slash command — surface help.
    await send_telegram(
        chat_id,
        f"Unknown command: {cmd}. Type /help for the command list.",
        session,
    )
    return True


# ── Telegram update polling ──────────────────────────────────────────────


async def handle_updates(session: aiohttp.ClientSession) -> None:
    """Long-poll Telegram for new messages and route each one."""
    offset = 0
    while True:
        try:
            async with session.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=aiohttp.ClientTimeout(total=35),
            ) as resp:
                if resp.status != 200:
                    logger.error(f"getUpdates failed: {resp.status}")
                    await asyncio.sleep(5)
                    continue
                data = await resp.json()

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text", "") or ""
                chat_id = str(message.get("chat", {}).get("id", ""))

                # Allow-list the configured chat. Multiple chats / users are
                # a future extension; v1 is single-tenant.
                if HUMAN_CHAT_ID and chat_id != HUMAN_CHAT_ID:
                    logger.warning(f"Ignoring message from unknown chat: {chat_id}")
                    continue
                if not chat_id or not text:
                    continue

                logger.info(
                    f"Received from {chat_id}: {text[:80]}"
                    f"{'...' if len(text) > 80 else ''}"
                )

                # Slash commands first; otherwise route to orchestration.
                handled = await dispatch_command(chat_id, text, session)
                if handled:
                    continue
                await handle_human_message(chat_id, text, session)

        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.exception(f"Update handler error: {e}")
            await asyncio.sleep(5)


# ── SSE listener: outbound (daemon → Human) ──────────────────────────────


def _parse_sse_block(block: str) -> Optional[dict]:
    """Parse one SSE block (text up to a blank line) into an event dict.

    Returns ``{id, kind, payload}`` for a complete frame, or ``None`` if
    the block is just keep-alive comments / lacks a data line.
    """
    event_id: Optional[int] = None
    kind: Optional[str] = None
    data_lines: list[str] = []
    for line in block.splitlines():
        if not line or line.startswith(":"):
            continue
        if ":" not in line:
            continue
        field, _, value = line.partition(":")
        # SSE allows one optional space after the colon.
        if value.startswith(" "):
            value = value[1:]
        if field == "id":
            try:
                event_id = int(value)
            except ValueError:
                event_id = None
        elif field == "event":
            kind = value
        elif field == "data":
            data_lines.append(value)
    if not data_lines:
        return None
    raw = "\n".join(data_lines)
    try:
        payload_outer = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"SSE: bad JSON in data line: {raw[:200]}")
        return None
    return {
        "id": event_id if event_id is not None else payload_outer.get("id"),
        "kind": kind or payload_outer.get("kind"),
        "payload": payload_outer.get("payload") or {},
    }


async def _stream_sse(
    session: aiohttp.ClientSession,
    last_event_id: Optional[int],
):
    """Async generator yielding parsed events from the SSE endpoint.

    Sends ``Last-Event-ID`` on the request so the daemon's replay buffer
    catches up any events missed during the disconnect window.
    """
    headers = {"Accept": "text/event-stream"}
    if last_event_id is not None and last_event_id > 0:
        headers["Last-Event-ID"] = str(last_event_id)
    url = f"{DAEMON_URL}/api/v1/orchestration/events"
    # No total timeout — the SSE stream is supposed to live forever.
    timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
    async with session.get(url, headers=headers, timeout=timeout) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(
                f"SSE connect failed: {resp.status} {text[:200]}"
            )
        buffer = ""
        async for chunk in resp.content.iter_any():
            if not chunk:
                continue
            buffer += chunk.decode("utf-8", errors="replace")
            # SSE frames are separated by a blank line ("\n\n").
            while "\n\n" in buffer:
                block, _, buffer = buffer.partition("\n\n")
                event = _parse_sse_block(block)
                if event is not None:
                    yield event


async def outbound_sse_loop(session: aiohttp.ClientSession) -> None:
    """Long-running SSE consumer — relays assistant turns to Telegram.

    Behavior:
    - Subscribes to the daemon's event stream.
    - On ``session.message_appended`` with role=assistant, looks up the
      session's channel_id (cached per session) and if it's
      ``telegram:<chat>``, sends the text to that chat.
    - On disconnect / error: exponential backoff + reconnect with the
      last seen event id so we don't miss anything in the replay window.

    A small in-process cache maps session_id → channel_id so we don't
    re-fetch the session row for every message turn.
    """
    last_event_id: Optional[int] = None
    backoff = SSE_MIN_BACKOFF
    # Tiny per-process cache: session_id → channel_id (or "" for non-telegram).
    # Bounded by daemon session count which is small. No eviction needed for v1.
    channel_cache: dict[str, str] = {}

    while True:
        try:
            logger.info(
                f"SSE: connecting (last_event_id={last_event_id})"
            )
            async for event in _stream_sse(session, last_event_id):
                # Reset backoff on a successfully consumed event.
                backoff = SSE_MIN_BACKOFF

                if event.get("id") is not None:
                    last_event_id = event["id"]

                kind = event.get("kind")
                payload = event.get("payload") or {}

                if kind != "session.message_appended":
                    continue
                if payload.get("role") != "assistant":
                    continue
                session_id = payload.get("session_id")
                text = payload.get("text") or ""
                if not session_id or not text:
                    continue

                channel_id = channel_cache.get(session_id)
                if channel_id is None:
                    meta = await get_session_meta(session_id, session)
                    channel_id = (meta or {}).get("channel_id") or ""
                    channel_cache[session_id] = channel_id

                chat_id = _chat_id_from_channel_id(channel_id)
                if not chat_id:
                    continue
                if HUMAN_CHAT_ID and chat_id != HUMAN_CHAT_ID:
                    # Some other tenant's chat — don't relay.
                    logger.debug(
                        f"SSE: skipping non-allowlisted chat {chat_id}"
                    )
                    continue

                logger.info(
                    f"SSE: relaying assistant turn from {session_id} "
                    f"to chat {chat_id} ({len(text)} chars)"
                )
                await send_telegram(chat_id, text, session)

            # If the generator returns cleanly, the server closed the stream
            # gracefully; reconnect after the minimum backoff.
            logger.info("SSE: stream ended cleanly; reconnecting")
            await asyncio.sleep(SSE_MIN_BACKOFF)
            backoff = SSE_MIN_BACKOFF
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                f"SSE: stream error ({type(e).__name__}: {e}); "
                f"reconnecting in {backoff:.1f}s"
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, SSE_MAX_BACKOFF)


# ── Entry point ──────────────────────────────────────────────────────────


async def main_async() -> None:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set. Get one from @BotFather.")
        sys.exit(1)
    if not HUMAN_CHAT_ID:
        logger.warning(
            "TELEGRAM_HUMAN_CHAT_ID not set — bot will accept messages from "
            "any chat. Set it in .env to allow-list a single Human."
        )

    logger.info(
        f"Telegram channel adapter starting (daemon={DAEMON_URL}, "
        f"default_profile={DEFAULT_PROFILE})"
    )

    async with aiohttp.ClientSession() as session:
        # Verify the bot token before starting any loops.
        async with session.get(f"{TELEGRAM_API}/getMe") as resp:
            if resp.status == 200:
                me = await resp.json()
                bot_name = me.get("result", {}).get("username", "unknown")
                logger.info(f"Bot authenticated: @{bot_name}")
            else:
                logger.error(f"Bot authentication failed: {await resp.text()}")
                sys.exit(1)

        # Run inbound poll + outbound SSE relay in parallel forever.
        await asyncio.gather(
            handle_updates(session),
            outbound_sse_loop(session),
        )


def main() -> None:
    """Synchronous entry point used by the pyproject ``[project.scripts]``."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Shutdown via KeyboardInterrupt")


if __name__ == "__main__":
    main()
