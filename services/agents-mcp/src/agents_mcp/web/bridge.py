"""Telegram-bot bridge routes — minimal HTTP surface kept alive while the
new orchestration model is bedded in.

Why this file exists
--------------------
The Telegram bot (`services/telegram-bot/bot.py`) talks to the daemon over
HTTP. While the orchestration v1 effort retires the rest of the legacy Web UI
(see `services/agents-mcp/src/agents_mcp/web/api.py` was 1049 LOC of dead
endpoints), the Telegram bridge is still the live channel between Human and
the Agent Harness.

Routes consumed by the bot:

- ``POST /api/v1/human/messages``   — inbound (Human → daemon)
- ``GET  /api/v1/human/outbox``     — outbound poll (daemon → bot → Human)
- ``GET  /api/v1/brief``            — ``/brief`` slash-command Morning Brief
- ``GET  /api/v1/health``           — ``/status`` slash-command healthcheck
- ``POST /api/v1/human/send``       — admin's outbound path
  (CLAUDE.md pitfall #6)

Phase 4 (channel-adapter rewrite) will replace this whole file with a clean
adapter on the new orchestration model. Until then: keep it small, keep it
boring, do not add new endpoints.
"""

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)


def create_bridge_router(get_client, get_store, get_config, resolve_agents):
    """Return the list of bridge routes.

    The returned list can be passed to ``starlette.routing.Mount("/api", routes=...)``
    in the daemon HTTP app.

    Args:
        get_client: Callable returning the SQLiteTaskClient.
        get_store: Async callable returning the AgentStore.
        get_config: Callable returning the daemon config dict.
        resolve_agents: Callable taking the config, returning the resolved
            agents map. Currently unused by bridge endpoints but kept in the
            signature for symmetry with `create_api_router`.
    """
    # ``resolve_agents`` is intentionally accepted but unused — it lets
    # callers swap bridge↔api without a signature change. Mark to silence
    # linters.
    _ = resolve_agents

    async def post_human_message(request: Request) -> JSONResponse:
        """Receive a message from Human (via Telegram Bot or other channel).

        Routing logic:
        - Brief responses (approve/defer/cancel #xxx) → executed directly.
        - Everything else → forwarded to admin as a P2P message; admin
          decides whether to reply, create a ticket, or ignore.
        """
        body = await request.json()
        text = body.get("body", "")
        channel = body.get("channel", "telegram")
        if not text:
            return JSONResponse({"error": "Missing 'body' field"}, status_code=400)
        store = await get_store()
        msg_id = await store.insert_human_message(
            direction="inbound",
            body=text,
            channel=channel,
            context_type=body.get("context_type", ""),
        )

        routed = False
        try:
            if not text.startswith("/"):
                from agents_mcp.brief_responder import parse_brief_response
                actions = parse_brief_response(text)
                has_ticket_actions = any(a.get("ticket_id") for a in actions)

                if has_ticket_actions:
                    from agents_mcp.brief_responder import execute_actions
                    client = get_client()
                    results = await execute_actions(actions, client, store)
                    summary = ", ".join(
                        f"#{r['ticket_id']} {r['action']}"
                        for r in results
                        if r.get("ticket_id")
                    )
                    await store.insert_human_message(
                        direction="outbound",
                        body=f"✅ Done: {summary}",
                        channel="system",
                        context_type="execution_confirmation",
                    )
                    routed = True
                else:
                    await store.insert_message(
                        from_agent="human",
                        to_agent="admin",
                        body=f"[Telegram] {text}",
                    )
                    routed = True
                    logger.info("Routed Human Telegram message to admin P2P inbox")
        except Exception as e:
            logger.warning(f"Human message routing failed: {e}")

        return JSONResponse({"received": True, "message_id": msg_id, "routed": routed})

    async def get_human_outbox(request: Request) -> JSONResponse:
        """Drain undelivered outbound messages (called by the Telegram bot poll loop).

        Each row is marked delivered before it's returned, so retries don't
        double-send. The bot is responsible for delivery — if the bot crashes
        between the poll response and the Telegram send, the message is
        lost. That's an acceptable trade-off for now (Phase 4 will fix this
        properly with delivery acks).
        """
        store = await get_store()
        async with store._db.execute(
            """SELECT * FROM human_messages
               WHERE direction = 'outbound' AND read_by_agent = 0
               ORDER BY created_at ASC LIMIT 10"""
        ) as cursor:
            rows = await cursor.fetchall()
        messages = [dict(r) for r in rows]
        for m in messages:
            await store.mark_human_message_processed(m["id"])
        return JSONResponse({"messages": messages, "count": len(messages)})

    async def post_human_outbound(request: Request) -> JSONResponse:
        """Send an outbound message to Human (queued for the Telegram bot to deliver).

        See CLAUDE.md pitfall #6 — agents must use this route, NOT
        ``/v1/human/messages`` which is the inbound path.
        """
        body = await request.json()
        text = body.get("body", "")
        if not text:
            return JSONResponse({"error": "Missing 'body' field"}, status_code=400)
        store = await get_store()
        msg_id = await store.insert_human_message(
            direction="outbound",
            body=text,
            channel=body.get("channel", "system"),
            source_agent_type=body.get("source_agent_type", ""),
            context_type=body.get("context_type", ""),
        )
        return JSONResponse({"sent": True, "message_id": msg_id})

    async def get_morning_brief(request: Request) -> PlainTextResponse:
        """Generate and return today's Morning Brief as Markdown."""
        from agents_mcp.morning_brief import generate_brief
        client = get_client()
        store = await get_store()
        cfg = get_config()
        brief = await generate_brief(client, store, config=cfg)
        return PlainTextResponse(brief, media_type="text/markdown")

    async def health(request: Request) -> JSONResponse:
        """Lightweight healthcheck used by the Telegram ``/status`` command.

        Reports daemon liveness + task DB reachability. (The legacy
        ``tmux_active`` / ``tmux_session`` fields were removed on
        2026-05-03 along with the v1 named-tmux-window agent model;
        orchestration v1 sessions live inside the daemon process.)
        """
        # ``get_config`` is accepted for signature symmetry but no longer
        # consulted here — kept so future fields (e.g. SSE listener count)
        # can read config without re-threading the closure.
        _ = get_config

        task_db_ok = False
        try:
            client = get_client()
            await client.get_status_labels()
            task_db_ok = True
        except Exception:
            pass

        return JSONResponse({
            "status": "ok",
            "task_db": task_db_ok,
        })

    return [
        Route("/v1/human/messages", post_human_message, methods=["POST"]),
        Route("/v1/human/outbox", get_human_outbox, methods=["GET"]),
        Route("/v1/human/send", post_human_outbound, methods=["POST"]),
        Route("/v1/brief", get_morning_brief, methods=["GET"]),
        Route("/v1/health", health, methods=["GET"]),
    ]
