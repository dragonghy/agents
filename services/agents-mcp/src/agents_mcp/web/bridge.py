"""Legacy minimal HTTP surface — `/api/v1/health` + `/api/v1/brief` only.

History: this file used to host 5 routes for the v1 Telegram bridge
(``/v1/human/messages``, ``/v1/human/outbox``, ``/v1/human/send``,
``/v1/brief``, ``/v1/health``). After the Phase 4 channel-adapter
rewrite (PR #32) the v1 bot was retired in favor of orchestration v1
session-based routing — the three ``/v1/human/*`` routes had no
remaining consumers and were removed in the Phase 5b cleanup
(2026-05-03, ticket #27).

What remains:

- ``GET  /api/v1/brief``   — backs the Telegram bot's ``/brief`` slash
  command. Calls :func:`agents_mcp.morning_brief.generate_brief` and
  returns the Markdown body. Eventually folded into the secretary's
  channel-adapter flow (the morning-brief refactor in PR #32 added a
  daemon-side scheduler that drives the secretary directly), but the
  on-demand ``/brief`` slash command still uses this endpoint.
- ``GET  /api/v1/health`` — backs the bot's ``/status`` slash command
  and ``proxy.py``'s connection check. Kept until both consumers
  migrate to a path under ``/api/v1/orchestration/``.

Do not add new endpoints here — anything new belongs in
``orchestration_api.py``.
"""

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)


def create_bridge_router(get_client, get_store, get_config, resolve_agents):
    """Return the list of legacy bridge routes.

    The returned list is mounted under ``/api`` in the daemon HTTP app.

    Args:
        get_client: Callable returning the SQLiteTaskClient.
        get_store: Async callable returning the AgentStore (kept in the
            signature for symmetry with ``create_orchestration_router``;
            the surviving routes don't need it).
        get_config: Callable returning the daemon config dict (also
            unused by the surviving routes — see comment in ``health``).
        resolve_agents: Same — accepted for signature compatibility but
            not consulted. Linter-silenced below.
    """
    _ = get_store
    _ = resolve_agents

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

        Reports daemon liveness + task DB reachability. The legacy
        ``tmux_active`` / ``tmux_session`` fields were removed on
        2026-05-03 along with the v1 named-tmux-window agent model;
        orchestration v1 sessions live inside the daemon process.
        """
        _ = get_config  # see module docstring

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
        Route("/v1/brief", get_morning_brief, methods=["GET"]),
        Route("/v1/health", health, methods=["GET"]),
    ]
