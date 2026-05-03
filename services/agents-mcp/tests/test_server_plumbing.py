"""Tests for orchestration v1 plumbing in server.py MCP tool handlers.

These tests exercise the dispatch hooks wired into ``update_ticket`` and
``add_comment`` in :mod:`agents_mcp.server`. The Leantime client + the
dispatch helpers are mocked so we can verify the wiring (correct args
forwarded, failures swallowed) without spinning up the daemon, hitting
SQLite, or doing real Leantime CRUD.

Style mirrors the rest of the orchestration v1 tests: sync test methods
wrapping async coroutines via a local ``run()`` helper, no
pytest-asyncio dep.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Both MCP tools are wrapped by FastMCP's ``@app.tool()`` decorator AND
# our local ``@_with_timeout`` decorator, which means the imported name
# is a Tool wrapper, not the raw async function. We grab the underlying
# coroutine via ``.fn`` (FastMCP convention) so we can call it directly
# in tests without the MCP request/response plumbing.

from agents_mcp import server as srv


def _raw(tool):
    """Return the raw async function behind a FastMCP tool wrapper.

    FastMCP exposes the original function as ``.fn``. If that attribute
    is missing (older / newer SDK versions) we fall back to assuming the
    object is itself callable and awaitable.
    """
    return getattr(tool, "fn", tool)


# ── update_ticket → maybe_spawn_tpm_for_status_change wiring ─────────────


class TestUpdateTicketDispatch:
    def test_update_ticket_3_to_4_spawns_tpm(self):
        """status 3 → 4 transition should call maybe_spawn_tpm_for_status_change
        with the right (ticket_id, old_status, new_status)."""
        async def _t():
            mock_client = MagicMock()
            mock_client.get_ticket = AsyncMock(return_value={"id": 42, "status": 3})
            mock_client.update_ticket = AsyncMock(return_value={"ok": True})

            mock_store = MagicMock()
            mock_store.subscribe = AsyncMock(return_value=True)

            mock_sm = MagicMock(name="session_manager")

            spawn_mock = AsyncMock(return_value="sess_new")
            close_mock = AsyncMock(return_value=False)

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=mock_sm), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_spawn_tpm_for_status_change",
                    spawn_mock,
                 ), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_close_tpm_for_status_change",
                    close_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                await _raw(srv.update_ticket)(ticket_id=42, status=4)

            assert spawn_mock.await_count == 1
            kwargs = spawn_mock.call_args.kwargs
            assert kwargs["ticket_id"] == 42
            assert kwargs["old_status"] == 3
            assert kwargs["new_status"] == 4
            # Close hook is also called (idempotent no-op for non-terminal).
            assert close_mock.await_count == 1
            assert close_mock.call_args.kwargs["new_status"] == 4

        run(_t())

    def test_update_ticket_no_status_change_no_dispatch(self):
        """If status is not provided, the spawn/close hooks must not fire."""
        async def _t():
            mock_client = MagicMock()
            mock_client.get_ticket = AsyncMock(return_value={"id": 7, "status": 4})
            mock_client.update_ticket = AsyncMock(return_value={"ok": True})

            mock_store = MagicMock()
            mock_store.subscribe = AsyncMock(return_value=True)

            spawn_mock = AsyncMock()
            close_mock = AsyncMock()

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=MagicMock()), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_spawn_tpm_for_status_change",
                    spawn_mock,
                 ), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_close_tpm_for_status_change",
                    close_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                await _raw(srv.update_ticket)(ticket_id=7, headline="changed")

            assert spawn_mock.await_count == 0
            assert close_mock.await_count == 0
            # And we should NOT have pre-fetched the ticket (no status change).
            assert mock_client.get_ticket.await_count == 0

        run(_t())

    def test_update_ticket_status_unchanged_no_dispatch(self):
        """If new status equals old status, no dispatch fires."""
        async def _t():
            mock_client = MagicMock()
            mock_client.get_ticket = AsyncMock(return_value={"id": 7, "status": 4})
            mock_client.update_ticket = AsyncMock(return_value={"ok": True})

            mock_store = MagicMock()
            mock_store.subscribe = AsyncMock(return_value=True)

            spawn_mock = AsyncMock()
            close_mock = AsyncMock()

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=MagicMock()), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_spawn_tpm_for_status_change",
                    spawn_mock,
                 ), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_close_tpm_for_status_change",
                    close_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                await _raw(srv.update_ticket)(ticket_id=7, status=4)

            assert spawn_mock.await_count == 0
            assert close_mock.await_count == 0

        run(_t())

    def test_update_ticket_4_to_0_calls_close_tpm(self):
        """status 4 → 0 (Done) should call maybe_close_tpm_for_status_change."""
        async def _t():
            mock_client = MagicMock()
            mock_client.get_ticket = AsyncMock(return_value={"id": 99, "status": 4})
            mock_client.update_ticket = AsyncMock(return_value={"ok": True})

            mock_store = MagicMock()
            mock_store.subscribe = AsyncMock(return_value=True)

            spawn_mock = AsyncMock(return_value=None)
            close_mock = AsyncMock(return_value=True)

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=MagicMock()), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_spawn_tpm_for_status_change",
                    spawn_mock,
                 ), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_close_tpm_for_status_change",
                    close_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                await _raw(srv.update_ticket)(ticket_id=99, status=0)

            assert close_mock.await_count == 1
            kwargs = close_mock.call_args.kwargs
            assert kwargs["ticket_id"] == 99
            assert kwargs["new_status"] == 0
            # Spawn is also called (no-op for non-3→4) but called once.
            assert spawn_mock.await_count == 1

        run(_t())

    def test_update_ticket_session_manager_unavailable_skips_dispatch(self):
        """If SessionManager is None (orchestration not booted), the
        primary update path still works and dispatch is silently skipped.
        """
        async def _t():
            mock_client = MagicMock()
            mock_client.get_ticket = AsyncMock(return_value={"id": 1, "status": 3})
            mock_client.update_ticket = AsyncMock(return_value={"ok": True})

            mock_store = MagicMock()
            mock_store.subscribe = AsyncMock(return_value=True)

            spawn_mock = AsyncMock()
            close_mock = AsyncMock()

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=None), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_spawn_tpm_for_status_change",
                    spawn_mock,
                 ), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_close_tpm_for_status_change",
                    close_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                result = await _raw(srv.update_ticket)(ticket_id=1, status=4)

            assert spawn_mock.await_count == 0
            assert close_mock.await_count == 0
            assert mock_client.update_ticket.await_count == 1
            # Result still serialised JSON of the client's return value.
            assert "ok" in result

        run(_t())


# ── add_comment → dispatch_comment_to_tpm wiring ─────────────────────────


class TestAddCommentDispatch:
    def test_add_comment_to_ticket_dispatches_to_tpm(self):
        """A new ticket comment should call dispatch_comment_to_tpm with
        the comment_id, body, and author_session_id forwarded through."""
        async def _t():
            mock_client = MagicMock()
            mock_client.add_comment = AsyncMock(return_value=12345)

            mock_store = MagicMock()
            mock_sm = MagicMock(name="session_manager")

            dispatch_mock = AsyncMock(return_value="sess_tpm")

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=mock_sm), \
                 patch(
                    "agents_mcp.orchestration_comment_dispatch."
                    "dispatch_comment_to_tpm",
                    dispatch_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                await _raw(srv.add_comment)(
                    module="ticket",
                    module_id=42,
                    comment="hello tpm",
                    author="dev-alex",
                    author_session_id="sess_alex",
                )

            assert dispatch_mock.await_count == 1
            kwargs = dispatch_mock.call_args.kwargs
            assert kwargs["ticket_id"] == 42
            assert kwargs["comment_id"] == 12345
            assert kwargs["comment_body"] == "hello tpm"
            assert kwargs["author_session_id"] == "sess_alex"

        run(_t())

    def test_add_comment_human_author_passes_none_session_id(self):
        """When no author_session_id is provided (Human via UI), the
        dispatch helper receives ``None``."""
        async def _t():
            mock_client = MagicMock()
            mock_client.add_comment = AsyncMock(return_value=2)

            mock_store = MagicMock()
            mock_sm = MagicMock()

            dispatch_mock = AsyncMock(return_value=None)

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=mock_sm), \
                 patch(
                    "agents_mcp.orchestration_comment_dispatch."
                    "dispatch_comment_to_tpm",
                    dispatch_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                await _raw(srv.add_comment)(
                    module="ticket", module_id=5, comment="from human"
                )

            assert dispatch_mock.await_count == 1
            assert dispatch_mock.call_args.kwargs["author_session_id"] is None

        run(_t())

    def test_add_comment_non_ticket_module_no_dispatch(self):
        """Comments on non-ticket modules (e.g. milestone) should not
        trigger TPM dispatch — TPMs are bound to tickets only."""
        async def _t():
            mock_client = MagicMock()
            mock_client.add_comment = AsyncMock(return_value=99)

            mock_store = MagicMock()
            dispatch_mock = AsyncMock()

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=MagicMock()), \
                 patch(
                    "agents_mcp.orchestration_comment_dispatch."
                    "dispatch_comment_to_tpm",
                    dispatch_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                await _raw(srv.add_comment)(
                    module="milestone", module_id=1, comment="not a ticket"
                )

            assert dispatch_mock.await_count == 0

        run(_t())

    def test_add_comment_failure_does_not_break_primary(self):
        """If dispatch_comment_to_tpm raises, add_comment must still
        return success — orchestration is best-effort."""
        async def _t():
            mock_client = MagicMock()
            mock_client.add_comment = AsyncMock(return_value=77)

            mock_store = MagicMock()
            mock_sm = MagicMock()

            dispatch_mock = AsyncMock(side_effect=RuntimeError("boom"))

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=mock_sm), \
                 patch(
                    "agents_mcp.orchestration_comment_dispatch."
                    "dispatch_comment_to_tpm",
                    dispatch_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                # Should not raise — exceptions inside the dispatch hook
                # are caught and logged.
                result = await _raw(srv.add_comment)(
                    module="ticket", module_id=11, comment="will explode dispatch"
                )

            assert dispatch_mock.await_count == 1
            # Primary path still returned the comment id from the client.
            assert "77" in result

        run(_t())

    def test_add_comment_session_manager_unavailable_skips_dispatch(self):
        async def _t():
            mock_client = MagicMock()
            mock_client.add_comment = AsyncMock(return_value=3)

            mock_store = MagicMock()
            dispatch_mock = AsyncMock()

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=None), \
                 patch(
                    "agents_mcp.orchestration_comment_dispatch."
                    "dispatch_comment_to_tpm",
                    dispatch_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                await _raw(srv.add_comment)(
                    module="ticket", module_id=4, comment="no orchestration"
                )

            assert dispatch_mock.await_count == 0
            assert mock_client.add_comment.await_count == 1

        run(_t())


# ── update_ticket dispatch failure swallowed ────────────────────────────


class TestUpdateTicketDispatchFailure:
    def test_dispatch_exception_does_not_break_update(self):
        """If maybe_spawn_tpm_for_status_change raises, update_ticket
        still returns success — orchestration is best-effort."""
        async def _t():
            mock_client = MagicMock()
            mock_client.get_ticket = AsyncMock(return_value={"id": 5, "status": 3})
            mock_client.update_ticket = AsyncMock(return_value={"ok": True})

            mock_store = MagicMock()
            mock_store.subscribe = AsyncMock(return_value=True)
            mock_sm = MagicMock()

            spawn_mock = AsyncMock(side_effect=RuntimeError("kaboom"))
            close_mock = AsyncMock(return_value=False)

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=mock_sm), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_spawn_tpm_for_status_change",
                    spawn_mock,
                 ), \
                 patch(
                    "agents_mcp.orchestration_tpm_dispatch."
                    "maybe_close_tpm_for_status_change",
                    close_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                result = await _raw(srv.update_ticket)(ticket_id=5, status=4)

            assert mock_client.update_ticket.await_count == 1
            assert "ok" in result
