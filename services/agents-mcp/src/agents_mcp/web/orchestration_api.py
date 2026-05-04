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

Tickets (Task #20 — UI rework):
- ``GET   /tickets``                       — list with workspace/project/status filters
- ``GET   /tickets/tree``                  — Workspace > Project > umbrella tree
- ``GET   /tickets/{id}``                  — single ticket + dependency lists
- ``GET   /tickets/{id}/comments``         — comments
- ``GET   /tickets/{id}/sessions``         — sessions bound to this ticket
- ``PATCH /tickets/{id}``                  — minimal status / priority / headline edit
- ``POST  /tickets``                       — create a ticket (Task #34)
- ``POST  /tickets/{id}/comments``         — append a comment (Task #34)

The factory :func:`create_orchestration_router` returns a list of
:class:`starlette.routing.Route` objects (matching the bridge's
``create_bridge_router`` style). Mount it under ``/api/v1/orchestration``.

No FastAPI here — daemon HTTP is plain Starlette.

Design references:
- ``projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md`` §8
- ``projects/agent-hub/research/ui-rewrite-vs-adapt-2026-05-02.md`` §"minimum
  viable test harness"
- ``projects/agent-hub/research/ticket-ui-findings-2026-05-03.md`` (Task #20)
- ``services/agents-mcp/src/agents_mcp/orchestration_session_manager.py``

The router accepts ``store``, ``session_manager``, optional ``profiles_dir``,
and optional ``task_client`` as constructor args. Each may be a live object
or a zero-arg (sync or async) callable returning one — the daemon uses the
callable form because mount happens before the asyncio loop is up; tests
pass live mocks directly.
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


def create_orchestration_router(
    store: Any,
    session_manager: Any,
    profiles_dir: Any = None,
    task_client: Any = None,
) -> list[Route]:
    """Build the orchestration v1 routes.

    Args:
        store: Either an :class:`agents_mcp.store.AgentStore` instance or a
            zero-arg callable / async callable returning one. The daemon
            uses the callable form (lazy init); tests pass the live store
            directly.
        session_manager: Either a
            :class:`agents_mcp.orchestration_session_manager.SessionManager`
            instance or a zero-arg callable / async callable returning one.
        profiles_dir: Optional path (or zero-arg callable returning a path)
            to the ``profiles/`` directory. Used by GET /profiles/{name}
            to read the system prompt body. If omitted, the route falls
            back to the registry's ``file_path`` column.
        task_client: Optional Leantime/SQLite task client (or callable
            returning one). Required for the Ticket endpoints; the cost +
            session endpoints don't need it. Tests pass a fake client
            implementing the methods used: ``get_ticket``, ``list_tickets``,
            ``update_ticket``, ``get_comments``, ``list_workspaces``.

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

    async def get_profile(request: Request) -> JSONResponse:
        """``GET /profiles/{name}`` — registry row + parsed Profile body.

        Returns:
            ``{registry: <row>, profile: {name, description, runner_type,
            mcp_servers, skills, system_prompt, orchestration_tools}}``.
            ``profile`` is ``null`` if the file is missing/malformed; the
            registry row is still returned for diagnosis.
        """
        name = request.path_params["name"]
        s = await _resolve(store)
        registry_row = await s.get_profile_registry(name)
        if registry_row is None:
            return JSONResponse(
                {"error": f"profile not found: {name}"}, status_code=404
            )

        # Resolve the Profile body. Try profiles_dir first; fall back to
        # the registry's file_path (use its parent's parent as the dir).
        from pathlib import Path as _Path

        profile_dict: Optional[dict[str, Any]] = None
        try:
            from ..profile_loader import load_profile

            pd = await _resolve(profiles_dir)
            if pd is None:
                # Derive from registry row: file_path = .../profiles/<name>/profile.md
                fp = _Path(registry_row.get("file_path") or "")
                pd = fp.parent.parent if fp.name == "profile.md" else None
            if pd is not None:
                p = load_profile(name, _Path(pd))
                profile_dict = {
                    "name": p.name,
                    "description": p.description,
                    "runner_type": p.runner_type,
                    "system_prompt": p.system_prompt,
                    "mcp_servers": list(p.mcp_servers),
                    "skills": list(p.skills),
                    "orchestration_tools": p.orchestration_tools,
                    "file_path": p.file_path,
                    "file_hash": p.file_hash,
                }
        except FileNotFoundError as e:
            logger.warning("get_profile: file missing for %s: %s", name, e)
        except Exception as e:
            logger.exception("get_profile: failed to load %s", name)
            profile_dict = None
            return JSONResponse(
                {
                    "registry": registry_row,
                    "profile": None,
                    "error": f"failed to parse profile: {e}",
                },
                status_code=200,
            )

        return JSONResponse({"registry": registry_row, "profile": profile_dict})

    async def get_profile_sessions(request: Request) -> JSONResponse:
        """``GET /profiles/{name}/sessions`` — recent sessions of this Profile.

        Query params: ``limit`` (default 10, max 100).
        Sorted newest first via :meth:`AgentStore.list_sessions_paginated`.
        """
        name = request.path_params["name"]
        try:
            limit = min(int(request.query_params.get("limit", 10)), 100)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "limit must be an integer"}, status_code=400
            )
        s = await _resolve(store)
        rows, total = await s.list_sessions_paginated(
            profile_name=name,
            limit=limit,
            offset=0,
        )
        return JSONResponse(
            {"sessions": rows, "total": total, "profile_name": name}
        )

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
            ``ticket`` (ticket_id), ``channel_id`` (e.g. ``telegram:<chat>``),
            ``limit`` (default 50, max 500), ``offset`` (default 0).

        Channel-adapter callers (Phase 4 Telegram bot) use the
        ``channel_id`` filter to look up the active human-channel session
        for an incoming message before deciding whether to spawn a new one.
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
        channel_id = request.query_params.get("channel_id") or None

        s = await _resolve(store)
        try:
            rows, total = await s.list_sessions_paginated(
                status=status,
                profile_name=profile,
                ticket_id=ticket_id,
                channel_id=channel_id,
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

    # ── Ticket endpoints (Task #20 — UI rework) ───────────────────────────
    #
    # Read paths proxy SQLiteTaskClient (which is the daemon's existing
    # Leantime-shaped client over ``.agents-tasks.db``). Write path (PATCH)
    # delegates to the same client and additionally fires the orchestration
    # TPM hooks so the HTTP path matches the MCP-tool path's behaviour.

    async def _resolve_workspaces_index() -> dict[int, dict]:
        """Build a {workspace_id: workspace_row} cache for one request."""
        c = await _resolve(task_client)
        if c is None:
            return {}
        try:
            ws_rows = await c.list_workspaces()
        except Exception:
            logger.exception("list_workspaces failed during ticket resolve")
            return {}
        return {int(w["id"]): w for w in ws_rows if w.get("id") is not None}

    def _summarize_ticket(
        row: dict,
        workspaces_index: dict[int, dict],
    ) -> dict:
        """Augment a ticket dict with workspace_name (project_name optional).

        Tickets store ``workspace_id`` directly. ``projectId`` points to a
        Leantime project (which lives in the ``tickets`` table itself with
        ``type='project'``); we surface only the id here and let the
        client (or :func:`_get_project_name`) resolve when needed.
        """
        out = dict(row) if isinstance(row, dict) else dict(row)
        ws_id = out.get("workspace_id")
        if ws_id is not None:
            ws = workspaces_index.get(int(ws_id))
            out["workspace_name"] = ws.get("name") if ws else None
        else:
            out["workspace_name"] = None
        return out

    async def _get_project_name(project_id: int | None) -> str | None:
        """Look up a project's headline by id (projects ARE tickets in Leantime)."""
        if project_id is None:
            return None
        c = await _resolve(task_client)
        if c is None:
            return None
        try:
            row = await c.get_ticket(int(project_id), prune=True)
        except Exception:
            logger.debug("get_ticket failed for project %s", project_id)
            return None
        if not row:
            return None
        return row.get("headline")

    async def list_tickets(request: Request) -> JSONResponse:
        """``GET /tickets`` — list with optional filters.

        Query params: ``workspace`` (id), ``project`` (id), ``status``
        (single int code or comma-separated, or 'all'), ``limit``
        (default 200, max 500), ``offset`` (default 0).

        Returns each ticket with ``workspace_name`` resolved and a
        ``dependencies`` summary giving counts of ``depends_on`` and
        ``dependents`` rows in :func:`AgentStore.ticket_dependencies`.
        """
        c = await _resolve(task_client)
        if c is None:
            return JSONResponse(
                {"error": "task_client not configured"}, status_code=500
            )
        try:
            limit = min(int(request.query_params.get("limit", 200)), 500)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "limit/offset must be integers"}, status_code=400
            )

        ws_q = request.query_params.get("workspace")
        workspace_id: Optional[int]
        if ws_q:
            try:
                workspace_id = int(ws_q)
            except ValueError:
                return JSONResponse(
                    {"error": "workspace must be an integer"}, status_code=400
                )
        else:
            workspace_id = None

        project_q = request.query_params.get("project")
        project_id: Optional[int]
        if project_q:
            try:
                project_id = int(project_q)
            except ValueError:
                return JSONResponse(
                    {"error": "project must be an integer"}, status_code=400
                )
        else:
            project_id = None

        status = request.query_params.get("status") or None  # 'all' / '1,3,4' / None

        try:
            payload = await c.list_tickets(
                project_id=project_id,
                status=status,
                workspace_id=workspace_id,
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            logger.exception("list_tickets failed")
            return JSONResponse(
                {"error": "list_tickets failed", "detail": str(e)},
                status_code=500,
            )

        tickets = payload.get("tickets") or []
        ws_index = await _resolve_workspaces_index()
        s = await _resolve(store)
        out_rows: list[dict] = []
        for t in tickets:
            row = _summarize_ticket(t, ws_index)
            tid = row.get("id")
            if tid is not None and s is not None:
                try:
                    deps = await s.get_dependencies(int(tid))
                    dependents = await s.get_dependents(int(tid))
                    row["dependencies"] = {
                        "depends_on_count": len(deps),
                        "dependents_count": len(dependents),
                    }
                except Exception:
                    row["dependencies"] = {
                        "depends_on_count": 0,
                        "dependents_count": 0,
                    }
            else:
                row["dependencies"] = {
                    "depends_on_count": 0,
                    "dependents_count": 0,
                }
            out_rows.append(row)

        return JSONResponse(
            {
                "tickets": out_rows,
                "total": payload.get("total", len(out_rows)),
                "limit": limit,
                "offset": offset,
            }
        )

    async def get_ticket(request: Request) -> JSONResponse:
        """``GET /tickets/{id}`` — single ticket with workspace + project + deps."""
        c = await _resolve(task_client)
        if c is None:
            return JSONResponse(
                {"error": "task_client not configured"}, status_code=500
            )
        try:
            ticket_id = int(request.path_params["id"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse(
                {"error": "ticket id must be an integer"}, status_code=400
            )
        try:
            row = await c.get_ticket(ticket_id, prune=False)
        except Exception as e:
            logger.exception("get_ticket failed for %s", ticket_id)
            return JSONResponse(
                {"error": "get_ticket failed", "detail": str(e)},
                status_code=500,
            )
        if not row:
            return JSONResponse(
                {"error": f"ticket not found: {ticket_id}"}, status_code=404
            )

        ws_index = await _resolve_workspaces_index()
        out = _summarize_ticket(row, ws_index)

        project_id = out.get("projectId")
        out["project_name"] = await _get_project_name(project_id)

        s = await _resolve(store)
        if s is not None:
            try:
                depends_on = await s.get_dependencies(ticket_id)
                dependents = await s.get_dependents(ticket_id)
            except Exception:
                depends_on, dependents = [], []
        else:
            depends_on, dependents = [], []

        # Resolve dependency headlines for friendlier UI rendering. Best-effort.
        async def _resolve_headline(tid: int) -> dict:
            try:
                trow = await c.get_ticket(int(tid), prune=True)
            except Exception:
                trow = None
            return {
                "id": int(tid),
                "headline": (trow or {}).get("headline"),
                "status": (trow or {}).get("status"),
            }

        depends_on_full = [await _resolve_headline(t) for t in depends_on]
        dependents_full = [await _resolve_headline(t) for t in dependents]
        out["dependencies"] = {
            "depends_on": depends_on_full,
            "dependents": dependents_full,
        }
        return JSONResponse(out)

    async def get_ticket_comments(request: Request) -> JSONResponse:
        """``GET /tickets/{id}/comments`` — comments list (read-only)."""
        c = await _resolve(task_client)
        if c is None:
            return JSONResponse(
                {"error": "task_client not configured"}, status_code=500
            )
        try:
            ticket_id = int(request.path_params["id"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse(
                {"error": "ticket id must be an integer"}, status_code=400
            )
        try:
            limit = min(int(request.query_params.get("limit", 200)), 500)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "limit must be an integer"}, status_code=400
            )
        try:
            payload = await c.get_comments("ticket", ticket_id, limit=limit, offset=0)
        except Exception as e:
            logger.exception("get_comments failed for %s", ticket_id)
            return JSONResponse(
                {"error": "get_comments failed", "detail": str(e)},
                status_code=500,
            )
        return JSONResponse(payload)

    async def get_ticket_sessions(request: Request) -> JSONResponse:
        """``GET /tickets/{id}/sessions`` — sessions bound to this ticket."""
        try:
            ticket_id = int(request.path_params["id"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse(
                {"error": "ticket id must be an integer"}, status_code=400
            )
        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "limit/offset must be integers"}, status_code=400
            )
        s = await _resolve(store)
        if s is None:
            return JSONResponse(
                {"sessions": [], "total": 0, "limit": limit, "offset": offset}
            )
        rows, total = await s.list_sessions_paginated(
            ticket_id=ticket_id, limit=limit, offset=offset
        )
        return JSONResponse(
            {
                "sessions": rows,
                "total": total,
                "limit": limit,
                "offset": offset,
                "ticket_id": ticket_id,
            }
        )

    async def patch_ticket(request: Request) -> JSONResponse:
        """``PATCH /tickets/{id}`` — minimal status / priority / headline edit.

        After delegating to the task client, fires the orchestration TPM
        hooks (auto-spawn on 3→4, auto-close on terminal) when status
        changes — same code path as the MCP ``update_ticket`` tool.
        """
        c = await _resolve(task_client)
        if c is None:
            return JSONResponse(
                {"error": "task_client not configured"}, status_code=500
            )
        try:
            ticket_id = int(request.path_params["id"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse(
                {"error": "ticket id must be an integer"}, status_code=400
            )
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

        kwargs: dict[str, Any] = {}
        if "status" in body and body["status"] is not None:
            try:
                kwargs["status"] = int(body["status"])
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": "status must be an integer"}, status_code=400
                )
        if "priority" in body and body["priority"] is not None:
            if not isinstance(body["priority"], str):
                return JSONResponse(
                    {"error": "priority must be a string"}, status_code=400
                )
            kwargs["priority"] = body["priority"]
        if "headline" in body and body["headline"] is not None:
            if not isinstance(body["headline"], str):
                return JSONResponse(
                    {"error": "headline must be a string"}, status_code=400
                )
            kwargs["headline"] = body["headline"]

        if not kwargs:
            return JSONResponse(
                {"error": "no editable fields supplied (status/priority/headline)"},
                status_code=400,
            )

        # Capture old_status before update (matches server.py:update_ticket).
        old_status: Optional[int] = None
        if "status" in kwargs:
            try:
                existing = await c.get_ticket(ticket_id, prune=True)
                if existing:
                    old_status = (
                        int(existing["status"])
                        if existing.get("status") is not None
                        else None
                    )
            except Exception:
                logger.debug(
                    "patch_ticket: pre-fetch of #%s failed; skipping TPM dispatch",
                    ticket_id,
                )

        try:
            await c.update_ticket(ticket_id, **kwargs)
        except Exception as e:
            logger.exception("patch_ticket: update_ticket failed for %s", ticket_id)
            return JSONResponse(
                {"error": "update failed", "detail": str(e)}, status_code=500
            )

        # TPM dispatch hooks — best effort, mirrors MCP update_ticket path.
        if (
            "status" in kwargs
            and old_status is not None
            and old_status != kwargs["status"]
        ):
            sm = await _resolve(session_manager)
            s = await _resolve(store)
            if sm is not None and s is not None:
                try:
                    from ..orchestration_tpm_dispatch import (
                        maybe_close_tpm_for_status_change,
                        maybe_spawn_tpm_for_status_change,
                    )

                    await maybe_spawn_tpm_for_status_change(
                        sm,
                        s,
                        ticket_id=ticket_id,
                        old_status=old_status,
                        new_status=int(kwargs["status"]),
                    )
                    await maybe_close_tpm_for_status_change(
                        s,
                        ticket_id=ticket_id,
                        new_status=int(kwargs["status"]),
                    )
                except Exception:
                    logger.exception(
                        "TPM dispatch hook failed for ticket %s "
                        "(PATCH endpoint)",
                        ticket_id,
                    )

        # Re-fetch and return the updated row so the UI doesn't have to
        # round-trip a separate GET.
        try:
            row = await c.get_ticket(ticket_id, prune=False)
        except Exception:
            row = None
        if not row:
            return JSONResponse({"ok": True, "ticket": None})
        ws_index = await _resolve_workspaces_index()
        return JSONResponse({"ok": True, "ticket": _summarize_ticket(row, ws_index)})

    async def create_ticket_endpoint(request: Request) -> JSONResponse:
        """``POST /tickets`` — create a new task ticket.

        Body fields:
            ``headline`` (str, required): ticket title.
            ``description`` (str, optional): long-form body.
            ``assignee`` (str, optional): agent name (e.g. ``"dev"``); written
                to both the native ``assignee`` column and the
                ``agent:<name>`` tag for backward compatibility.
            ``tags`` (str | list[str], optional): tag string. List forms are
                joined with ``,`` to match the SQLite column shape.
            ``priority`` (str | int, optional): priority label. Coerced to
                string for the underlying TEXT column.
            ``parent_id`` (int, optional): parent ticket id (becomes the
                ``dependingTicketId``). 404 if the parent doesn't exist.

        Returns the newly inserted ticket row (with workspace_name resolved)
        and HTTP 201 on success.
        """
        c = await _resolve(task_client)
        if c is None:
            return JSONResponse(
                {"error": "task_client not configured"}, status_code=500
            )
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

        headline = body.get("headline")
        if not headline or not isinstance(headline, str):
            return JSONResponse(
                {"error": "headline (non-empty string) is required"},
                status_code=400,
            )

        kwargs: dict[str, Any] = {}
        if "description" in body and body["description"] is not None:
            if not isinstance(body["description"], str):
                return JSONResponse(
                    {"error": "description must be a string"}, status_code=400
                )
            kwargs["description"] = body["description"]
        if "priority" in body and body["priority"] is not None:
            # Coerce int / str → str (the column is TEXT; the brief allowed int).
            if isinstance(body["priority"], (str, int)):
                kwargs["priority"] = str(body["priority"])
            else:
                return JSONResponse(
                    {"error": "priority must be a string or integer"},
                    status_code=400,
                )

        # tags can be a list[str] (per brief) or a raw comma-joined string.
        tags: Optional[str] = None
        if "tags" in body and body["tags"] is not None:
            raw_tags = body["tags"]
            if isinstance(raw_tags, list):
                if not all(isinstance(t, str) for t in raw_tags):
                    return JSONResponse(
                        {"error": "tags list must contain strings only"},
                        status_code=400,
                    )
                tags = ",".join(raw_tags)
            elif isinstance(raw_tags, str):
                tags = raw_tags
            else:
                return JSONResponse(
                    {"error": "tags must be a string or list of strings"},
                    status_code=400,
                )

        assignee: Optional[str] = None
        if "assignee" in body and body["assignee"] is not None:
            if not isinstance(body["assignee"], str):
                return JSONResponse(
                    {"error": "assignee must be a string"}, status_code=400
                )
            assignee = body["assignee"]

        # parent_id → dependingTicketId. Validate existence to give a
        # meaningful 404 instead of an opaque foreign-key surprise later.
        if "parent_id" in body and body["parent_id"] is not None:
            try:
                parent_id = int(body["parent_id"])
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": "parent_id must be an integer"}, status_code=400
                )
            try:
                parent_row = await c.get_ticket(parent_id, prune=True)
            except Exception:
                logger.exception(
                    "create_ticket: parent lookup failed for #%s", parent_id
                )
                parent_row = None
            if not parent_row:
                return JSONResponse(
                    {"error": f"parent ticket not found: {parent_id}"},
                    status_code=404,
                )
            kwargs["dependingTicketId"] = parent_id

        try:
            new_id = await c.create_ticket(
                headline=headline,
                tags=tags,
                assignee=assignee,
                **kwargs,
            )
        except Exception as e:
            logger.exception("create_ticket: insert failed")
            return JSONResponse(
                {"error": "create_ticket failed", "detail": str(e)},
                status_code=500,
            )

        # Re-fetch so the response mirrors GET /tickets/{id} shape (incl. id).
        try:
            row = await c.get_ticket(int(new_id), prune=False)
        except Exception:
            row = None
        if not row:
            # Last-ditch: at least return the id so callers can recover.
            return JSONResponse({"id": int(new_id)}, status_code=201)

        ws_index = await _resolve_workspaces_index()
        return JSONResponse(
            _summarize_ticket(row, ws_index), status_code=201
        )

    async def create_comment_endpoint(request: Request) -> JSONResponse:
        """``POST /tickets/{id}/comments`` — append a comment to a ticket.

        Body fields:
            ``body`` (str, required): the comment text.
            ``author`` (str, optional): agent id of the comment author
                (e.g. ``"dev"``). Empty / missing means Human-authored.

        Mirrors the MCP ``add_comment`` tool: after insert, fires the
        orchestration v1 TPM comment-dispatch hook so an active TPM session
        for the ticket sees the new comment, identical to the MCP path.
        Returns the newly inserted comment row + HTTP 201.

        404 if the ticket does not exist.
        """
        c = await _resolve(task_client)
        if c is None:
            return JSONResponse(
                {"error": "task_client not configured"}, status_code=500
            )
        try:
            ticket_id = int(request.path_params["id"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse(
                {"error": "ticket id must be an integer"}, status_code=400
            )
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "request body must be valid JSON"}, status_code=400
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": "request body must be a JSON object"}, status_code=400
            )

        comment_body = payload.get("body")
        if not comment_body or not isinstance(comment_body, str):
            return JSONResponse(
                {"error": "body (non-empty string) is required"},
                status_code=400,
            )

        author: Optional[str] = None
        if "author" in payload and payload["author"] is not None:
            if not isinstance(payload["author"], str):
                return JSONResponse(
                    {"error": "author must be a string"}, status_code=400
                )
            author = payload["author"]

        # 404 cleanly when the ticket doesn't exist, instead of inserting a
        # comment that points at nothing.
        try:
            existing = await c.get_ticket(ticket_id, prune=True)
        except Exception:
            logger.exception(
                "create_comment: ticket lookup failed for #%s", ticket_id
            )
            existing = None
        if not existing:
            return JSONResponse(
                {"error": f"ticket not found: {ticket_id}"}, status_code=404
            )

        try:
            comment_id = await c.add_comment(
                "ticket", ticket_id, comment_body, author=author
            )
        except Exception as e:
            logger.exception(
                "create_comment: add_comment failed for #%s", ticket_id
            )
            return JSONResponse(
                {"error": "add_comment failed", "detail": str(e)},
                status_code=500,
            )

        # Mirror MCP add_comment: forward to active TPM session if any.
        # Best effort — never fail the HTTP response on dispatch error.
        sm = await _resolve(session_manager)
        s = await _resolve(store)
        if sm is not None and s is not None:
            try:
                from ..orchestration_comment_dispatch import (
                    dispatch_comment_to_tpm,
                )

                cid = (
                    int(comment_id)
                    if isinstance(comment_id, int)
                    else (
                        int(comment_id.get("id", 0))
                        if isinstance(comment_id, dict)
                        else 0
                    )
                )
                await dispatch_comment_to_tpm(
                    sm,
                    s,
                    ticket_id=ticket_id,
                    comment_id=cid,
                    comment_body=comment_body,
                    author_session_id=None,
                )
            except Exception:
                logger.exception(
                    "TPM comment dispatch failed for ticket %s "
                    "(POST endpoint)",
                    ticket_id,
                )

        # Compose the response. Re-fetch via get_comments so we return the
        # row exactly as it lives in storage (including any default fields
        # SQLite filled in like ``date``).
        new_id = (
            int(comment_id)
            if isinstance(comment_id, int)
            else (
                int(comment_id.get("id", 0))
                if isinstance(comment_id, dict)
                else 0
            )
        )
        try:
            comments_payload = await c.get_comments(
                "ticket", ticket_id, limit=0, offset=0
            )
            new_row = next(
                (
                    cm
                    for cm in (comments_payload.get("comments") or [])
                    if int(cm.get("id") or -1) == new_id
                ),
                None,
            )
        except Exception:
            new_row = None

        if new_row is None:
            # Fall back to a synthesized row so callers always see {id, body}.
            new_row = {
                "id": new_id,
                "ticket_id": ticket_id,
                "moduleId": ticket_id,
                "body": comment_body,
                "text": comment_body,
                "author": author or "",
            }
        return JSONResponse(new_row, status_code=201)

    async def get_ticket_tree(request: Request) -> JSONResponse:
        """``GET /tickets/tree`` — Workspace > Project > umbrella > children.

        Returns a hierarchical structure for the List view:

            [
              { "workspace": {id, name, kind},
                "projects": [
                  { "project": {id, name},
                    "tickets": [
                      { "ticket": {...}, "children": [...] }
                    ]
                  }
                ]
              }
            ]

        Children are immediate dependents resolved via
        :func:`AgentStore.get_dependents` (i.e. tickets that depend on this
        ticket). One level deep — agents drill into a ticket's detail page
        for deeper nesting.

        Query params: ``workspace`` (id) — when given, restrict to one
        workspace; otherwise return all.

        Sort order within a (workspace, project) bucket: by status
        (4 → 3 → 1 → 0 → -1), then by ticket id desc. Closed/archived
        children are still listed under their parent.
        """
        c = await _resolve(task_client)
        if c is None:
            return JSONResponse(
                {"error": "task_client not configured"}, status_code=500
            )
        s = await _resolve(store)

        ws_q = request.query_params.get("workspace")
        workspace_id: Optional[int]
        if ws_q:
            try:
                workspace_id = int(ws_q)
            except ValueError:
                return JSONResponse(
                    {"error": "workspace must be an integer"}, status_code=400
                )
        else:
            workspace_id = None

        # Pull all active+done tickets so the tree includes recently-closed
        # leaves. Use 'all' status; the type filter excludes Leantime
        # 'project' rows from the leaf set (they become parents below).
        try:
            payload = await c.list_tickets(
                status="all",
                ticket_type="task",
                workspace_id=workspace_id,
                limit=0,
            )
        except Exception as e:
            logger.exception("get_ticket_tree: list_tickets failed")
            return JSONResponse(
                {"error": "list_tickets failed", "detail": str(e)},
                status_code=500,
            )

        ws_rows: list[dict]
        try:
            ws_rows = await c.list_workspaces()
        except Exception:
            ws_rows = []

        if workspace_id is not None:
            ws_rows = [w for w in ws_rows if int(w.get("id") or 0) == workspace_id]

        # Group tickets by (workspace_id, projectId).
        tickets = list(payload.get("tickets") or [])

        # Status sort key — 4 (WIP) first, then 3 (New), 1 (Blocked), 0 (Done), -1 (Archived).
        _status_order = {4: 0, 3: 1, 1: 2, 0: 3, -1: 4}

        def _sort_key(t: dict) -> tuple[int, int]:
            return (
                _status_order.get(int(t.get("status") or 0), 99),
                -int(t.get("id") or 0),
            )

        # Build a {ticket_id: ticket} lookup for child resolution.
        by_id = {int(t["id"]): t for t in tickets if t.get("id") is not None}

        # Resolve dependents for every ticket in one batch (best-effort).
        children_map: dict[int, list[int]] = {}
        if s is not None:
            for tid in by_id:
                try:
                    children_map[tid] = await s.get_dependents(tid)
                except Exception:
                    children_map[tid] = []

        # A ticket is a "child of another ticket in the same project" if
        # one of its dependencies (parents) is itself a ticket in by_id.
        # We compute this so the list view can render only umbrellas at
        # top-level and surface children nested.
        parents_map: dict[int, list[int]] = {}
        if s is not None:
            for tid in by_id:
                try:
                    parents_map[tid] = await s.get_dependencies(tid)
                except Exception:
                    parents_map[tid] = []

        def _is_child_of_visible_parent(tid: int) -> bool:
            for parent_tid in parents_map.get(tid, []):
                if int(parent_tid) in by_id:
                    return True
            return False

        # Group leaf tickets by (workspace_id, projectId).
        groups: dict[tuple[int | None, int | None], list[dict]] = {}
        for t in tickets:
            wsid = t.get("workspace_id")
            pid = t.get("projectId")
            key = (
                int(wsid) if wsid is not None else None,
                int(pid) if pid is not None else None,
            )
            groups.setdefault(key, []).append(t)

        # Resolve project headlines once.
        project_ids = {pid for (_, pid) in groups.keys() if pid is not None}
        project_names: dict[int, str] = {}
        for pid in project_ids:
            name = await _get_project_name(pid)
            if name:
                project_names[pid] = name

        # Build the response tree.
        result: list[dict] = []
        # Stable workspace ordering by id.
        ws_index_order = sorted(
            [int(w["id"]) for w in ws_rows if w.get("id") is not None]
        )
        seen_ws: set[int | None] = set()

        def _ws_block(wsid: int | None) -> dict:
            if wsid is None:
                return {
                    "workspace": {"id": None, "name": "Unassigned", "kind": None},
                    "projects": [],
                }
            ws_row = next(
                (w for w in ws_rows if int(w.get("id") or -1) == wsid), None
            )
            return {
                "workspace": {
                    "id": wsid,
                    "name": (ws_row or {}).get("name", f"workspace #{wsid}"),
                    "kind": (ws_row or {}).get("kind"),
                },
                "projects": [],
            }

        # Make sure every workspace shows up even if it has no tickets in
        # the result set (gives the UI stable navigation).
        ordered_ws_ids: list[int | None] = list(ws_index_order)
        # Plus any workspace_ids that appeared on tickets but weren't in ws_rows.
        for (wsid, _pid) in groups.keys():
            if wsid not in ordered_ws_ids and wsid not in seen_ws:
                ordered_ws_ids.append(wsid)

        for wsid in ordered_ws_ids:
            block = _ws_block(wsid)
            # All groups with this workspace.
            ws_groups = [
                (pid, lst)
                for ((g_wsid, pid), lst) in groups.items()
                if g_wsid == wsid
            ]
            ws_groups.sort(key=lambda x: (x[0] is None, x[0] or 0))
            for pid, lst in ws_groups:
                # Top-level umbrellas + standalone tickets within this project:
                # everything that's not a child of another visible ticket.
                top = [t for t in lst if not _is_child_of_visible_parent(int(t["id"]))]
                top.sort(key=_sort_key)
                project_block = {
                    "project": {
                        "id": pid,
                        "name": project_names.get(pid) if pid is not None else None,
                    },
                    "tickets": [],
                }
                for t in top:
                    tid = int(t["id"])
                    raw_children = children_map.get(tid, [])
                    child_rows = [
                        by_id[int(cid)] for cid in raw_children if int(cid) in by_id
                    ]
                    child_rows.sort(key=_sort_key)
                    project_block["tickets"].append(
                        {
                            "ticket": t,
                            "children": child_rows,
                        }
                    )
                block["projects"].append(project_block)
            result.append(block)

        return JSONResponse({"workspaces": result})

    routes = [
        Route("/profiles", list_profiles, methods=["GET"]),
        Route("/profiles/{name}", get_profile, methods=["GET"]),
        Route(
            "/profiles/{name}/sessions",
            get_profile_sessions,
            methods=["GET"],
        ),
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
        # Tickets — /tickets/tree must come BEFORE /tickets/{id} so the
        # literal "tree" path doesn't get matched as id.
        Route("/tickets/tree", get_ticket_tree, methods=["GET"]),
        Route("/tickets", list_tickets, methods=["GET"]),
        Route("/tickets", create_ticket_endpoint, methods=["POST"]),
        Route(
            "/tickets/{id}/comments",
            get_ticket_comments,
            methods=["GET"],
        ),
        Route(
            "/tickets/{id}/comments",
            create_comment_endpoint,
            methods=["POST"],
        ),
        Route("/tickets/{id}/sessions", get_ticket_sessions, methods=["GET"]),
        Route("/tickets/{id}", get_ticket, methods=["GET"]),
        Route("/tickets/{id}", patch_ticket, methods=["PATCH"]),
    ]
    return routes


__all__ = ["create_orchestration_router"]
