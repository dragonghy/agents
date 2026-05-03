"""Orchestration v1 REST API — Profile registry + Session lifecycle endpoints.

This module exposes the minimum HTTP surface needed by the Phase 1+2 test
harness (Task #17) so a browser can drive a Session end-to-end:

- ``GET  /profiles``                       — list registered Profiles
- ``POST /sessions``                       — spawn a session
- ``POST /sessions/{id}/messages``         — append a user turn (calls Claude)
- ``POST /sessions/{id}/close``            — close a session
- ``GET  /sessions/{id}``                  — fetch session metadata

The factory :func:`create_orchestration_router` returns a list of
:class:`starlette.routing.Route` objects (matching the bridge's
``create_bridge_router`` style). Mount it under ``/api/v1/orchestration``.

No FastAPI here — daemon HTTP is plain Starlette.

Design references:
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

    routes = [
        Route("/profiles", list_profiles, methods=["GET"]),
        Route("/sessions", spawn_session, methods=["POST"]),
        Route("/sessions/{id}/messages", append_message, methods=["POST"]),
        Route("/sessions/{id}/close", close_session, methods=["POST"]),
        Route("/sessions/{id}", get_session, methods=["GET"]),
    ]
    return routes


__all__ = ["create_orchestration_router"]
