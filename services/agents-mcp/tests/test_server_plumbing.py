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


async def _drain_background_tasks():
    """Wait for any fire-and-forget tasks spawned via ``_spawn_background``.

    After PR #33 (decouple add_comment from event dispatch), the TPM
    dispatch + subscriber notification side effects run as background
    tasks so the primary tool return path doesn't pay their latency.
    Tests that assert on those side effects must drain the tasks first
    or they'd race with loop teardown.
    """
    pending = list(srv._BACKGROUND_TASKS)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


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
                await _drain_background_tasks()

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
                await _drain_background_tasks()

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
                await _drain_background_tasks()

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
                await _drain_background_tasks()

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
                await _drain_background_tasks()

            assert dispatch_mock.await_count == 0
            assert mock_client.add_comment.await_count == 1

        run(_t())


# ── add_comment latency: dispatch must NOT block the caller ───────────


class TestAddCommentNonBlocking:
    """Regression: ticket #33.

    Before the fix, ``add_comment`` awaited
    :func:`dispatch_comment_to_tpm` synchronously. That function calls
    ``SessionManager.append_message``, which spawns an LLM turn — easily
    >30s, the configured timeout. The caller saw "timed out" while the
    SDK subprocess kept running invisibly and the comment was already
    persisted. Bad UX: caller can't tell whether to retry.

    Post-fix: dispatch + subscriber notification are scheduled with
    ``asyncio.create_task``. The caller returns as soon as the SQLite
    write completes. We assert the response time is sub-second even
    when the dispatch hook would block for 60s.
    """

    def test_returns_fast_when_dispatch_blocks(self):
        """add_comment must return in <1s even if TPM dispatch hangs 60s."""
        async def _t():
            import time

            mock_client = MagicMock()
            mock_client.add_comment = AsyncMock(return_value=999)

            mock_store = MagicMock()
            mock_sm = MagicMock(name="session_manager")

            # Simulate a slow LLM turn inside the dispatch hook.
            slow_dispatch = AsyncMock(
                side_effect=lambda *a, **kw: asyncio.sleep(60),
            )
            slow_notify = AsyncMock(
                side_effect=lambda *a, **kw: asyncio.sleep(60),
            )

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=mock_sm), \
                 patch(
                    "agents_mcp.orchestration_comment_dispatch."
                    "dispatch_comment_to_tpm",
                    slow_dispatch,
                 ), \
                 patch.object(srv, "_notify_subscribers", slow_notify):
                t0 = time.monotonic()
                result = await _raw(srv.add_comment)(
                    module="ticket",
                    module_id=33,
                    comment="this should return fast",
                    author="dev-emma",
                    author_session_id="sess_emma",
                )
                elapsed = time.monotonic() - t0

            # Must be far below the 30s tool timeout AND below the 60s
            # we made the dispatch sleep. If the dispatch still blocks
            # the caller, this would be ~60s.
            assert elapsed < 1.0, (
                f"add_comment took {elapsed:.2f}s, "
                f"expected <1s (dispatch should be backgrounded)"
            )
            # Comment id from the client still flows back through.
            assert "999" in result
            # Cancel the still-pending background tasks so we don't
            # leak them across tests. ``gather(return_exceptions=True)``
            # awaits the cancellation so the loop teardown that follows
            # doesn't see pending tasks.
            pending = list(srv._BACKGROUND_TASKS)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        run(_t())

    def test_dispatch_runs_in_background(self):
        """The dispatch hook fires from a backgrounded task, not the
        caller's coroutine.

        Originally this test asserted ``dispatch_mock.await_count == 0``
        right after the caller returned, but that's racy — ``add_comment``
        ``await``s ``get_store()`` etc. during normal flow, and the event
        loop can advance the create_task'd coroutine during those awaits
        when the dispatch is a zero-cost ``AsyncMock``. We now assert the
        right invariant: the dispatch coroutine runs in a *separate task*
        (different from the caller's task), which is the actual
        guarantee provided by ``asyncio.create_task`` regardless of
        scheduling timing. Also keeps the post-drain count check.
        """
        async def _t():
            mock_client = MagicMock()
            mock_client.add_comment = AsyncMock(return_value=42)

            mock_store = MagicMock()
            mock_sm = MagicMock(name="session_manager")

            caller_task = asyncio.current_task()
            captured_dispatch_task: list[asyncio.Task] = []

            async def _capturing_dispatch(*args, **kwargs):
                captured_dispatch_task.append(asyncio.current_task())
                return "sess_tpm"

            dispatch_mock = AsyncMock(side_effect=_capturing_dispatch)

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
                    module_id=33,
                    comment="async dispatch",
                    author="dev-emma",
                    author_session_id="sess_emma",
                )
                await _drain_background_tasks()

            assert dispatch_mock.await_count == 1
            assert dispatch_mock.call_args.kwargs["ticket_id"] == 33
            assert dispatch_mock.call_args.kwargs["comment_id"] == 42
            # The actual contract: dispatch ran in a different task than
            # the caller. If add_comment had awaited the dispatch inline,
            # they'd be the same task — that's the regression we're
            # guarding against.
            assert len(captured_dispatch_task) == 1
            assert captured_dispatch_task[0] is not caller_task

        run(_t())

    def test_dispatch_exception_in_background_does_not_propagate(self):
        """Even if the backgrounded dispatch raises, the caller never sees it."""
        async def _t():
            mock_client = MagicMock()
            mock_client.add_comment = AsyncMock(return_value=7)

            mock_store = MagicMock()
            mock_sm = MagicMock()

            dispatch_mock = AsyncMock(side_effect=RuntimeError("background boom"))

            with patch.object(srv, "get_client", return_value=mock_client), \
                 patch.object(srv, "get_store", AsyncMock(return_value=mock_store)), \
                 patch.object(srv, "_get_session_manager", return_value=mock_sm), \
                 patch(
                    "agents_mcp.orchestration_comment_dispatch."
                    "dispatch_comment_to_tpm",
                    dispatch_mock,
                 ), \
                 patch.object(srv, "_notify_subscribers", AsyncMock()):
                # No raise — caller doesn't even await the failing task.
                result = await _raw(srv.add_comment)(
                    module="ticket", module_id=8, comment="will background-explode"
                )
                # Drain to let the task's exception fire its done-callback
                # (which logs but does not propagate).
                await _drain_background_tasks()

            assert "7" in result
            assert dispatch_mock.await_count == 1

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
