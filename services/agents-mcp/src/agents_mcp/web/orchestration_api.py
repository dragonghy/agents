"""Orchestration v1 REST API — Profile registry + Session lifecycle endpoints.

This module exposes the HTTP surface for orchestration v1:

Lifecycle (MVTH, Task #17):
- ``GET  /profiles``                       — list registered Profiles
- ``GET  /profiles/{name}``                — Profile detail (registry + body)
- ``GET  /profiles/{name}/sessions``       — recent sessions of a Profile
- ``POST /sessions``                       — spawn a session
- ``POST /sessions/{id}/messages``         — append a user turn (calls Claude)
- ``POST /sessions/{id}/close``            — close a session
- ``GET  /sessions/{id}``                  — fetch session metadata
- ``GET  /sessions/{id}/history``          — render conversation transcript
- ``GET  /sessions``                       — list with filters

Cost (Task #18 Part A):
- ``GET /cost/by-session``                 — paginated session-level cost rows
- ``GET /cost/by-profile``                 — rollup grouped by profile_name
- ``GET /cost/by-ticket``                  — rollup grouped by ticket_id
- ``GET /cost/totals``                     — today/week/lifetime totals

The factory :func:`create_orchestration_router` returns a list of
:class:`starlette.routing.Route` objects (matching the bridge's
``create_bridge_router`` style). Mount it under ``/api/v1/orchestration``.

No FastAPI here — daemon HTTP is plain Starlette.

Design references:
- ``projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md`` §8
- ``projects/agent-hub/research/ui-rewrite-vs-adapt-2026-05-02.md`` §"minimum
  viable test harness"
- ``services/agents-mcp/src/agents_mcp/orchestration_session_manager.py``

The router accepts ``store`` and ``session_manager`` as constructor args (no
lazy ``get_*`` callables) because both are cheap-to-hold singletons by the
time the daemon is mounting routes.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)


# Sonnet token pricing (USD per million tokens). Mirrors
# apps/console/backend/app/pricing.py and morning_brief.py so cost numbers
# match across surfaces. We don't break out cache-read / cache-write here
# because the ``session`` table only holds aggregated tokens_in / tokens_out.
_INPUT_PER_M = 3.00
_OUTPUT_PER_M = 15.00


def _estimate_usd(tokens_in: int, tokens_out: int) -> float:
    """Compute Sonnet-rate USD cost for a (tokens_in, tokens_out) pair."""
    cost = (
        (tokens_in or 0) * _INPUT_PER_M
        + (tokens_out or 0) * _OUTPUT_PER_M
    ) / 1_000_000.0
    return round(cost, 4)


def _pricing_block() -> dict[str, Any]:
    """Pricing metadata returned alongside totals for UI display."""
    return {
        "input_per_million": _INPUT_PER_M,
        "output_per_million": _OUTPUT_PER_M,
        "note": "Sonnet rates; cost = sum over sessions of cost_tokens_in/out.",
    }


async def _resolve(value: Any) -> Any:
    """Allow the factory to be passed either a live object or a getter.

    Daemon mounting happens before the asyncio loop is running, so the
    real store / session_manager need to be wrapped in a callable that
    lazily produces them on first request. Tests (which already have
    everything live) can pass the object directly.
    """
    if value is None:
        return None
    if callable(value):
        result = value()
        if inspect.isawaitable(result):
            result = await result
        return result
    return value


def create_orchestration_router(store: Any, session_manager: Any) -> list[Route]:
    """Build the orchestration v1 routes.

    Args:
        store: Either an :class:`agents_mcp.store.AgentStore` instance or a
            zero-arg callable / async callable returning one. The daemon
            uses the callable form (lazy init); tests pass the live store
            directly.
        session_manager: Either a
            :class:`agents_mcp.orchestration_session_manager.SessionManager`
            instance or a zero-arg callable / async callable returning one.

    Returns:
        A list of :class:`Route` objects suitable for
        ``Mount("/api/v1/orchestration", routes=...)``.
    """

    async def list_profiles(request: Request) -> JSONResponse:
        """``GET /profiles`` — return registered Profiles from the registry.

        Wraps :meth:`AgentStore.list_profile_registry`. The shape per row
        mirrors what the registry stores (name, description, runner_type,
        file_path, file_hash, loaded_at, last_used_at).
        """
        del request  # unused
        s = await _resolve(store)
        rows = await s.list_profile_registry()
        return JSONResponse({"profiles": list(rows), "total": len(rows)})

    async def spawn_session(request: Request) -> JSONResponse:
        """``POST /sessions`` — spawn a session and return its row.

        Body: ``{profile_name, binding_kind, ticket_id?, channel_id?,
        parent_session_id?}``.
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "request body must be valid JSON"}, status_code=400
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "request body must be a JSON object"}, status_code=400
            )

        profile_name = body.get("profile_name")
        binding_kind = body.get("binding_kind")
        if not profile_name or not isinstance(profile_name, str):
            return JSONResponse(
                {"error": "profile_name (string) is required"}, status_code=400
            )
        if not binding_kind or not isinstance(binding_kind, str):
            return JSONResponse(
                {"error": "binding_kind (string) is required"}, status_code=400
            )

        ticket_id = body.get("ticket_id")
        if ticket_id is not None:
            try:
                ticket_id = int(ticket_id)
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": "ticket_id must be an integer"}, status_code=400
                )
        channel_id = body.get("channel_id")
        if channel_id is not None and not isinstance(channel_id, str):
            return JSONResponse(
                {"error": "channel_id must be a string"}, status_code=400
            )
        parent_session_id = body.get("parent_session_id")
        if parent_session_id is not None and not isinstance(parent_session_id, str):
            return JSONResponse(
                {"error": "parent_session_id must be a string"}, status_code=400
            )

        try:
            sm = await _resolve(session_manager)
            row = await sm.spawn(
                profile_name=profile_name,
                binding_kind=binding_kind,
                ticket_id=ticket_id,
                channel_id=channel_id,
                parent_session_id=parent_session_id,
            )
        except FileNotFoundError as e:
            return JSONResponse(
                {"error": f"unknown profile: {profile_name}", "detail": str(e)},
                status_code=404,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            logger.exception("spawn_session failed")
            return JSONResponse(
                {"error": "spawn failed", "detail": str(e)}, status_code=500
            )

        return JSONResponse(row, status_code=201)

    async def append_message(request: Request) -> JSONResponse:
        """``POST /sessions/{id}/messages`` — run one Adapter turn.

        Body: ``{text}``. May take 5-30s while Claude is called; that's
        expected.
        """
        session_id = request.path_params["id"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "request body must be valid JSON"}, status_code=400
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "request body must be a JSON object"}, status_code=400
            )
        text = body.get("text")
        if not text or not isinstance(text, str):
            return JSONResponse(
                {"error": "text (non-empty string) is required"}, status_code=400
            )

        try:
            sm = await _resolve(session_manager)
            result = await sm.append_message(session_id, text)
        except LookupError as e:
            return JSONResponse(
                {"error": f"session not found: {session_id}", "detail": str(e)},
                status_code=404,
            )
        except RuntimeError as e:
            # Closed session, missing task_client for orchestration tools, etc.
            return JSONResponse({"error": str(e)}, status_code=400)
        except FileNotFoundError as e:
            return JSONResponse(
                {"error": "profile file missing", "detail": str(e)},
                status_code=500,
            )
        except Exception as e:
            logger.exception("append_message failed for session %s", session_id)
            return JSONResponse(
                {"error": "append_message failed", "detail": str(e)},
                status_code=500,
            )

        return JSONResponse(
            {
                "assistant_text": result.assistant_text,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "native_handle": result.native_handle,
            }
        )

    async def close_session(request: Request) -> JSONResponse:
        """``POST /sessions/{id}/close`` — mark a session closed.

        Idempotent. Returns ``{ok: bool}`` where ``ok`` reflects whether
        this call transitioned the session from active to closed.
        """
        session_id = request.path_params["id"]

        s = await _resolve(store)
        # Verify the session exists for a 404 distinct from "already closed".
        existing: Optional[dict] = await s.get_session(session_id)
        if existing is None:
            return JSONResponse(
                {"error": f"session not found: {session_id}"}, status_code=404
            )

        try:
            sm = await _resolve(session_manager)
            ok = await sm.close(session_id)
        except Exception as e:
            logger.exception("close_session failed for %s", session_id)
            return JSONResponse(
                {"error": "close failed", "detail": str(e)}, status_code=500
            )

        return JSONResponse({"ok": bool(ok)})

    async def get_session(request: Request) -> JSONResponse:
        """``GET /sessions/{id}`` — fetch session metadata row."""
        session_id = request.path_params["id"]
        s = await _resolve(store)
        row = await s.get_session(session_id)
        if row is None:
            return JSONResponse(
                {"error": f"session not found: {session_id}"}, status_code=404
            )
        return JSONResponse(row)

    async def list_sessions(request: Request) -> JSONResponse:
        """``GET /sessions`` — paginated session list with optional filters.

        Query params:
            ``status`` (active|closed), ``profile`` (profile_name),
            ``ticket`` (ticket_id), ``limit`` (default 50, max 500),
            ``offset`` (default 0).
        """
        try:
            limit = min(int(request.query_params.get("limit", 50)), 500)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "limit/offset must be integers"}, status_code=400
            )
        status = request.query_params.get("status") or None
        profile = request.query_params.get("profile") or None
        ticket = request.query_params.get("ticket")
        ticket_id: Optional[int]
        if ticket:
            try:
                ticket_id = int(ticket)
            except ValueError:
                return JSONResponse(
                    {"error": "ticket must be an integer"}, status_code=400
                )
        else:
            ticket_id = None

        s = await _resolve(store)
        try:
            rows, total = await s.list_sessions_paginated(
                status=status,
                profile_name=profile,
                ticket_id=ticket_id,
                limit=limit,
                offset=offset,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse(
            {
                "sessions": rows,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    async def get_session_history(request: Request) -> JSONResponse:
        """``GET /sessions/{id}/history`` — Adapter-rendered transcript.

        Routes to ``Adapter.render_history(session_id, store)`` based on
        the session's ``runner_type``. Returns ``{messages: [...]}`` with
        each message having ``role`` / ``text`` / ``timestamp``.
        """
        session_id = request.path_params["id"]
        s = await _resolve(store)
        row = await s.get_session(session_id)
        if row is None:
            return JSONResponse(
                {"error": f"session not found: {session_id}"}, status_code=404
            )
        runner_type = row.get("runner_type") or ""
        # Local import — adapters package pulls in the Claude SDK.
        from ..adapters import get_adapter

        try:
            adapter = get_adapter(runner_type)
        except (ValueError, NotImplementedError) as e:
            return JSONResponse(
                {"error": f"no adapter for runner_type {runner_type!r}", "detail": str(e)},
                status_code=400,
            )
        try:
            rendered = await adapter.render_history(session_id, s)
        except Exception as e:
            logger.exception("render_history failed for %s", session_id)
            return JSONResponse(
                {"error": "render_history failed", "detail": str(e)},
                status_code=500,
            )
        out = [
            {"role": m.role, "text": m.text, "timestamp": m.timestamp}
            for m in rendered
        ]
        return JSONResponse({"messages": out, "total": len(out)})

    # ── Cost endpoints (Task #18 Part A) ──────────────────────────────────

    async def cost_by_session(request: Request) -> JSONResponse:
        """``GET /cost/by-session`` — paginated session-level cost rows.

        Query params:
            ``limit`` (default 50, max 500), ``offset`` (default 0),
            ``status`` (active|closed), ``profile`` (profile_name),
            ``ticket`` (ticket_id).

        Each row: id, profile_name, ticket_id, channel_id, status,
        cost_tokens_in, cost_tokens_out, cost_usd, created_at.
        """
        try:
            limit = min(int(request.query_params.get("limit", 50)), 500)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return JSONResponse({"error": "limit/offset must be integers"}, status_code=400)
        status = request.query_params.get("status") or None
        profile = request.query_params.get("profile") or None
        ticket = request.query_params.get("ticket")
        ticket_id: Optional[int]
        if ticket:
            try:
                ticket_id = int(ticket)
            except ValueError:
                return JSONResponse(
                    {"error": "ticket must be an integer"}, status_code=400
                )
        else:
            ticket_id = None

        s = await _resolve(store)
        try:
            rows, total = await s.list_sessions_paginated(
                status=status,
                profile_name=profile,
                ticket_id=ticket_id,
                limit=limit,
                offset=offset,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

        for r in rows:
            r["cost_usd"] = _estimate_usd(
                r.get("cost_tokens_in") or 0,
                r.get("cost_tokens_out") or 0,
            )
        return JSONResponse(
            {
                "sessions": rows,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    async def cost_by_profile(request: Request) -> JSONResponse:
        """``GET /cost/by-profile`` — rollup grouped by profile_name."""
        del request
        s = await _resolve(store)
        rows = await s.cost_by_profile()
        for r in rows:
            r["total_usd"] = _estimate_usd(
                r.get("total_tokens_in") or 0,
                r.get("total_tokens_out") or 0,
            )
        return JSONResponse({"rollup": rows, "total": len(rows)})

    async def cost_by_ticket(request: Request) -> JSONResponse:
        """``GET /cost/by-ticket`` — rollup grouped by ticket_id."""
        del request
        s = await _resolve(store)
        rows = await s.cost_by_ticket()
        for r in rows:
            r["total_usd"] = _estimate_usd(
                r.get("total_tokens_in") or 0,
                r.get("total_tokens_out") or 0,
            )
        return JSONResponse({"rollup": rows, "total": len(rows)})

    async def cost_totals(request: Request) -> JSONResponse:
        """``GET /cost/totals`` — today/week/lifetime totals.

        Buckets on ``session.created_at``. Each bucket contains
        ``tokens_in``, ``tokens_out``, ``sessions_count``, and a derived
        ``usd`` figure at Sonnet rates.
        """
        del request
        s = await _resolve(store)
        out = await s.cost_totals()
        for bucket in out.values():
            bucket["usd"] = _estimate_usd(
                bucket.get("tokens_in") or 0,
                bucket.get("tokens_out") or 0,
            )
        out["pricing"] = _pricing_block()
        return JSONResponse(out)

    routes = [
        Route("/profiles", list_profiles, methods=["GET"]),
        Route("/sessions", spawn_session, methods=["POST"]),
        Route("/sessions", list_sessions, methods=["GET"]),
        Route("/sessions/{id}/messages", append_message, methods=["POST"]),
        Route("/sessions/{id}/close", close_session, methods=["POST"]),
        Route("/sessions/{id}/history", get_session_history, methods=["GET"]),
        Route("/sessions/{id}", get_session, methods=["GET"]),
        Route("/cost/by-session", cost_by_session, methods=["GET"]),
        Route("/cost/by-profile", cost_by_profile, methods=["GET"]),
        Route("/cost/by-ticket", cost_by_ticket, methods=["GET"]),
        Route("/cost/totals", cost_totals, methods=["GET"]),
    ]
    return routes


__all__ = ["create_orchestration_router"]
