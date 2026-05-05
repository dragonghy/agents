"""Tests for orchestration v1 TPM auto-spawn / auto-close hooks.

Hermetic: builds a synthetic ``tpm`` profile.md in tmp_path and a fresh
:class:`AgentStore` on a tmp sqlite DB. We use the real
:class:`SessionManager` end-to-end here because spawn doesn't call the
Adapter — that means no LLM, no mocking required at the spawn boundary.

Style mirrors test_session_manager.py: sync test functions wrapping
async coroutines via a local ``run()`` helper. No pytest-asyncio dep.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agents_mcp.orchestration_session_manager import SessionManager
from agents_mcp.orchestration_tpm_dispatch import (
    maybe_close_tpm_for_status_change,
    maybe_spawn_tpm_for_new_ticket,
    maybe_spawn_tpm_for_status_change,
)
from agents_mcp.store import AgentStore


# ── Fixtures / helpers ─────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-tpm-dispatch.db")


@pytest.fixture
def profiles_dir(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    return d


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _make_store(db_path: str) -> AgentStore:
    s = AgentStore(db_path)
    await s.initialize()
    return s


def _write_tpm_profile(profiles_dir: Path) -> None:
    """Write a minimal but well-formed tpm profile.md."""
    d = profiles_dir / "tpm"
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.md").write_text(
        "---\n"
        "name: tpm\n"
        "description: TPM profile for tests.\n"
        "runner_type: claude-sonnet-4.6\n"
        "---\n\n"
        "You are the TPM. Coordinate the ticket.\n",
        encoding="utf-8",
    )


# ── maybe_spawn_tpm_for_status_change ──────────────────────────────────────


class TestMaybeSpawnTpm:
    def test_3_to_4_transition_spawns_tpm(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            session_id = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=42, old_status=3, new_status=4
            )
            assert session_id is not None
            assert session_id.startswith("sess_")

            row = await store.get_session(session_id)
            assert row is not None
            assert row["profile_name"] == "tpm"
            assert row["binding_kind"] == "ticket-subagent"
            assert row["ticket_id"] == 42
            assert row["parent_session_id"] is None
            assert row["status"] == "active"

            await store.close()

        run(_t())

    @pytest.mark.parametrize(
        "old_status,new_status",
        [
            (3, 1),    # New -> Blocked
            (3, 0),    # New -> Done (skipping work)
            (3, -1),   # New -> Archived
            (4, 1),    # In-Progress -> Blocked
            (4, 0),    # In-Progress -> Done
            (4, -1),   # In-Progress -> Archived
            (1, 4),    # Blocked -> In-Progress (rework — TPM persists)
            (1, 3),    # Blocked -> New (re-triage)
            (1, 0),    # Blocked -> Done
            (0, 4),    # Done -> reopened to In-Progress
            (4, 4),    # No-op same-status (defensive)
            (3, 3),    # No-op same-status
        ],
    )
    def test_other_transitions_are_no_ops(
        self, db_path, profiles_dir, old_status, new_status
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            result = await maybe_spawn_tpm_for_status_change(
                mgr,
                store,
                ticket_id=99,
                old_status=old_status,
                new_status=new_status,
            )
            assert result is None
            assert await store.list_sessions() == []
            await store.close()

        run(_t())

    def test_3_to_4_with_existing_tpm_is_idempotent_no_op(
        self, db_path, profiles_dir
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            first = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=7, old_status=3, new_status=4
            )
            assert first is not None

            # Second 3→4 hop (e.g. ticket bounced back to New and forward
            # again). A TPM is already active; we must NOT spawn another.
            second = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=7, old_status=3, new_status=4
            )
            assert second is None

            sessions = await store.list_sessions(ticket_id=7)
            assert len(sessions) == 1
            assert sessions[0]["id"] == first

            await store.close()

        run(_t())

    def test_3_to_4_after_previous_tpm_closed_spawns_fresh(
        self, db_path, profiles_dir
    ):
        """If the prior TPM was closed (e.g. ticket was Done then reopened),
        the next 3→4 transition should produce a new TPM. The 'idempotent'
        guard is on *active* TPMs only.
        """
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            first = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=12, old_status=3, new_status=4
            )
            assert first is not None
            await store.close_session(first)

            second = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=12, old_status=3, new_status=4
            )
            assert second is not None
            assert second != first

            sessions = await store.list_sessions(ticket_id=12)
            assert len(sessions) == 2
            statuses = {s["id"]: s["status"] for s in sessions}
            assert statuses[first] == "closed"
            assert statuses[second] == "active"

            await store.close()

        run(_t())


# ── maybe_spawn_tpm_for_new_ticket ─────────────────────────────────────────


class TestMaybeSpawnTpmForNewTicket:
    """Spawn-on-creation hook so newly-created tickets get triaged
    immediately (not just on the 3→4 transition).
    """

    def test_new_ticket_in_status_3_spawns(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            session_id = await maybe_spawn_tpm_for_new_ticket(
                mgr, store, ticket_id=100, status=3
            )
            assert session_id is not None
            assert session_id.startswith("sess_")
            row = await store.get_session(session_id)
            assert row["profile_name"] == "tpm"
            assert row["binding_kind"] == "ticket-subagent"
            assert row["ticket_id"] == 100
            await store.close()

        run(_t())

    def test_new_ticket_in_status_4_also_spawns(self, db_path, profiles_dir):
        """Tickets created directly in In-Progress (skipping the 3→4
        hop) still get a TPM. This was the production bug — ticket #557
        was created at status=4 and the old 3→4-only hook missed it.
        """
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            session_id = await maybe_spawn_tpm_for_new_ticket(
                mgr, store, ticket_id=557, status=4
            )
            assert session_id is not None
            await store.close()

        run(_t())

    @pytest.mark.parametrize("status", [0, -1])
    def test_terminal_status_no_op(self, db_path, profiles_dir, status):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            result = await maybe_spawn_tpm_for_new_ticket(
                mgr, store, ticket_id=200, status=status
            )
            assert result is None
            assert await store.list_sessions() == []
            await store.close()

        run(_t())

    def test_idempotent_on_existing_tpm(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            first = await maybe_spawn_tpm_for_new_ticket(
                mgr, store, ticket_id=300, status=3
            )
            assert first is not None
            second = await maybe_spawn_tpm_for_new_ticket(
                mgr, store, ticket_id=300, status=3
            )
            assert second is None  # idempotent
            assert (
                len([s for s in await store.list_sessions() if s["ticket_id"] == 300])
                == 1
            )
            await store.close()

        run(_t())


# ── maybe_close_tpm_for_status_change ──────────────────────────────────────


class TestMaybeCloseTpm:
    def test_close_tpm_on_done(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            session_id = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=5, old_status=3, new_status=4
            )
            assert session_id is not None

            closed = await maybe_close_tpm_for_status_change(
                store, ticket_id=5, new_status=0
            )
            assert closed is True

            row = await store.get_session(session_id)
            assert row["status"] == "closed"

            await store.close()

        run(_t())

    def test_close_tpm_on_archived(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            session_id = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=6, old_status=3, new_status=4
            )

            closed = await maybe_close_tpm_for_status_change(
                store, ticket_id=6, new_status=-1
            )
            assert closed is True
            assert (await store.get_session(session_id))["status"] == "closed"

            await store.close()

        run(_t())

    def test_close_tpm_no_op_if_no_active_tpm(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            # No TPM ever spawned — closing should be silently false.
            closed = await maybe_close_tpm_for_status_change(
                store, ticket_id=999, new_status=0
            )
            assert closed is False
            await store.close()

        run(_t())

    def test_close_tpm_no_op_when_tpm_already_closed(
        self, db_path, profiles_dir
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            session_id = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=8, old_status=3, new_status=4
            )
            await store.close_session(session_id)

            # get_active_tpm_for_ticket filters on status='active', so once
            # the TPM is closed the helper should report no active TPM and
            # return False without raising.
            result = await maybe_close_tpm_for_status_change(
                store, ticket_id=8, new_status=0
            )
            assert result is False
            await store.close()

        run(_t())

    @pytest.mark.parametrize(
        "non_terminal_status",
        [
            1,   # Blocked
            3,   # New
            4,   # In Progress
        ],
    )
    def test_close_tpm_no_op_on_non_terminal_status(
        self, db_path, profiles_dir, non_terminal_status
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            mgr = SessionManager(store, profiles_dir)

            session_id = await maybe_spawn_tpm_for_status_change(
                mgr, store, ticket_id=11, old_status=3, new_status=4
            )

            closed = await maybe_close_tpm_for_status_change(
                store, ticket_id=11, new_status=non_terminal_status
            )
            assert closed is False
            # TPM still active.
            row = await store.get_session(session_id)
            assert row["status"] == "active"

            await store.close()

        run(_t())
