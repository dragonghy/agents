"""Tests for orchestration v1 session + profile_registry tables in store.py.

These cover the new schema and CRUD added on `feat/orchestration-v1`. They
do NOT exercise the SDK or any external service — purely DB-level.

Follows the existing test_ticket_dependencies.py pattern: sync test
functions using a `run()` helper to drive async code under
`asyncio.run_until_complete`. We intentionally avoid pytest-asyncio /
pytest-anyio dependencies because the rest of the suite doesn't use them.
"""
from __future__ import annotations

import asyncio

import pytest

from agents_mcp.store import AgentStore


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-orchestration.db")


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


# ── Session table ──


class TestSessionCRUD:
    def test_create_session_returns_dict(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            sess = await s.create_session(
                session_id="sess_test_1",
                profile_name="tpm",
                binding_kind="ticket-subagent",
                runner_type="claude-sonnet-4.6",
                ticket_id=123,
            )
            assert sess["id"] == "sess_test_1"
            assert sess["profile_name"] == "tpm"
            assert sess["binding_kind"] == "ticket-subagent"
            assert sess["runner_type"] == "claude-sonnet-4.6"
            assert sess["ticket_id"] == 123
            assert sess["status"] == "active"
            assert sess["cost_tokens_in"] == 0
            assert sess["cost_tokens_out"] == 0
            assert sess["channel_id"] is None
            assert sess["parent_session_id"] is None
            assert sess["native_handle"] is None
            await s.close()

        run(_t())

    def test_create_session_with_all_fields(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            sess = await s.create_session(
                session_id="sess_test_2",
                profile_name="developer",
                binding_kind="ticket-subagent",
                runner_type="claude-sonnet-4.6",
                ticket_id=456,
                parent_session_id="sess_test_1",
                native_handle="claude_internal_abcdef",
            )
            assert sess["parent_session_id"] == "sess_test_1"
            assert sess["native_handle"] == "claude_internal_abcdef"
            await s.close()

        run(_t())

    def test_create_session_human_channel_no_ticket(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            sess = await s.create_session(
                session_id="sess_tg_1",
                profile_name="secretary",
                binding_kind="human-channel",
                runner_type="claude-sonnet-4.6",
                channel_id="telegram:123456",
            )
            assert sess["ticket_id"] is None
            assert sess["channel_id"] == "telegram:123456"
            await s.close()

        run(_t())

    def test_invalid_binding_kind_rejected(self, db_path):
        import aiosqlite

        async def _t():
            s = await _make_store(db_path)
            with pytest.raises(aiosqlite.IntegrityError):
                await s.create_session(
                    session_id="sess_bad",
                    profile_name="tpm",
                    binding_kind="not-a-real-kind",
                    runner_type="claude-sonnet-4.6",
                )
            await s.close()

        run(_t())

    def test_get_session_missing_returns_none(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            assert await s.get_session("nonexistent") is None
            await s.close()

        run(_t())

    def test_list_sessions_invalid_status_filter(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            with pytest.raises(ValueError):
                await s.list_sessions(status="paused")
            await s.close()

        run(_t())


class TestSessionMutations:
    def test_update_native_handle(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            await s.create_session(
                session_id="sess_h",
                profile_name="developer",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.6",
            )
            assert (await s.get_session("sess_h"))["native_handle"] is None

            assert await s.update_session_native_handle("sess_h", "claude_xyz") is True
            assert (await s.get_session("sess_h"))["native_handle"] == "claude_xyz"

            # Updating a missing session is a no-op (returns False)
            assert await s.update_session_native_handle("missing", "x") is False
            await s.close()

        run(_t())

    def test_add_session_cost_accumulates(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            await s.create_session(
                session_id="sess_cost",
                profile_name="developer",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.6",
            )
            await s.add_session_cost("sess_cost", tokens_in=100, tokens_out=50)
            await s.add_session_cost("sess_cost", tokens_in=200, tokens_out=80)
            sess = await s.get_session("sess_cost")
            assert sess["cost_tokens_in"] == 300
            assert sess["cost_tokens_out"] == 130
            await s.close()

        run(_t())

    def test_close_session_idempotent(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            await s.create_session(
                session_id="sess_close",
                profile_name="developer",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.6",
            )
            # First close: returns True
            assert await s.close_session("sess_close") is True
            sess = await s.get_session("sess_close")
            assert sess["status"] == "closed"
            assert sess["closed_at"] is not None

            # Second close: returns False (already closed; idempotent)
            assert await s.close_session("sess_close") is False

            # Closing nonexistent: returns False
            assert await s.close_session("nonexistent") is False
            await s.close()

        run(_t())


class TestSessionQueries:
    def test_list_sessions_filters(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            # 4 sessions across 2 tickets + 1 channel
            await s.create_session("s1", "tpm", "ticket-subagent", "claude-sonnet-4.6", ticket_id=100)
            await s.create_session(
                "s2", "developer", "ticket-subagent", "claude-sonnet-4.6",
                ticket_id=100, parent_session_id="s1",
            )
            await s.create_session("s3", "tpm", "ticket-subagent", "claude-sonnet-4.6", ticket_id=200)
            await s.create_session(
                "s4", "secretary", "human-channel", "claude-sonnet-4.6", channel_id="telegram:abc"
            )

            all_ = await s.list_sessions()
            assert len(all_) == 4

            t100 = await s.list_sessions(ticket_id=100)
            assert {x["id"] for x in t100} == {"s1", "s2"}

            devs = await s.list_sessions(profile_name="developer")
            assert {x["id"] for x in devs} == {"s2"}

            tg = await s.list_sessions(channel_id="telegram:abc")
            assert {x["id"] for x in tg} == {"s4"}

            await s.close_session("s1")
            active = await s.list_sessions(status="active")
            assert {x["id"] for x in active} == {"s2", "s3", "s4"}
            closed = await s.list_sessions(status="closed")
            assert {x["id"] for x in closed} == {"s1"}
            await s.close()

        run(_t())

    def test_get_active_tpm_for_ticket(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            assert await s.get_active_tpm_for_ticket(100) is None

            await s.create_session(
                "tpm1", "tpm", "ticket-subagent", "claude-sonnet-4.6", ticket_id=100
            )
            tpm = await s.get_active_tpm_for_ticket(100)
            assert tpm is not None and tpm["id"] == "tpm1"

            # Subagent under TPM should NOT be returned
            await s.create_session(
                "dev1", "developer", "ticket-subagent", "claude-sonnet-4.6",
                ticket_id=100, parent_session_id="tpm1",
            )
            tpm = await s.get_active_tpm_for_ticket(100)
            assert tpm["id"] == "tpm1"

            # Closing the TPM means no active TPM
            await s.close_session("tpm1")
            assert await s.get_active_tpm_for_ticket(100) is None
            await s.close()

        run(_t())


# ── Profile registry table ──


class TestProfileRegistry:
    def test_upsert_inserts(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            p = await s.upsert_profile_registry(
                name="developer",
                description="Implements code changes, tests, opens PRs",
                runner_type="claude-sonnet-4.6",
                file_path="/abs/profiles/developer/profile.md",
                file_hash="hash_v1",
            )
            assert p["name"] == "developer"
            assert p["description"].startswith("Implements")
            assert p["file_hash"] == "hash_v1"
            assert p["loaded_at"] is not None
            assert p["last_used_at"] is None
            await s.close()

        run(_t())

    def test_upsert_updates_existing(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            await s.upsert_profile_registry(
                name="developer",
                description="v1 desc",
                runner_type="claude-sonnet-4.6",
                file_path="/abs/profiles/developer/profile.md",
                file_hash="hash_v1",
            )
            p = await s.upsert_profile_registry(
                name="developer",
                description="v2 desc",
                runner_type="claude-opus-4.6",
                file_path="/abs/profiles/developer/profile.md",
                file_hash="hash_v2",
            )
            assert p["description"] == "v2 desc"
            assert p["runner_type"] == "claude-opus-4.6"
            assert p["file_hash"] == "hash_v2"
            await s.close()

        run(_t())

    def test_list_ordered_by_name(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            for n in ("tpm", "developer", "secretary", "housekeeper"):
                await s.upsert_profile_registry(
                    name=n,
                    description=f"{n} desc",
                    runner_type="claude-sonnet-4.6",
                    file_path=f"/abs/profiles/{n}/profile.md",
                    file_hash="h",
                )
            listing = await s.list_profile_registry()
            names = [p["name"] for p in listing]
            assert names == sorted(names) == ["developer", "housekeeper", "secretary", "tpm"]
            await s.close()

        run(_t())

    def test_touch_profile_used_sets_timestamp(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            await s.upsert_profile_registry(
                name="tpm",
                description="d",
                runner_type="claude-sonnet-4.6",
                file_path="/abs",
                file_hash="h",
            )
            assert (await s.get_profile_registry("tpm"))["last_used_at"] is None

            await s.touch_profile_used("tpm")
            assert (await s.get_profile_registry("tpm"))["last_used_at"] is not None
            await s.close()

        run(_t())

    def test_touch_profile_used_unregistered_is_noop(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            # Should not raise
            await s.touch_profile_used("never_registered")
            assert await s.get_profile_registry("never_registered") is None
            await s.close()

        run(_t())


# ── Cost rollup methods (Task #18 Part A) ──


class TestCostRollups:
    def test_paginated_empty(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            rows, total = await s.list_sessions_paginated()
            assert rows == []
            assert total == 0
            await s.close()

        run(_t())

    def test_paginated_with_data(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            for i in range(3):
                await s.create_session(
                    session_id=f"sess_{i}",
                    profile_name="tpm" if i < 2 else "developer",
                    binding_kind="ticket-subagent",
                    runner_type="claude-sonnet-4.7",
                    ticket_id=100 + i,
                )
            rows, total = await s.list_sessions_paginated(limit=2, offset=0)
            assert total == 3
            assert len(rows) == 2

            # filter by profile
            rows, total = await s.list_sessions_paginated(profile_name="tpm")
            assert total == 2
            assert all(r["profile_name"] == "tpm" for r in rows)

            # filter by ticket
            rows, total = await s.list_sessions_paginated(ticket_id=101)
            assert total == 1
            assert rows[0]["ticket_id"] == 101

            await s.close()

        run(_t())

    def test_paginated_invalid_status_raises(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            with pytest.raises(ValueError):
                await s.list_sessions_paginated(status="bogus")
            await s.close()

        run(_t())

    def test_cost_by_profile(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            # Two TPM sessions, one developer; record cost on each.
            await s.create_session(
                session_id="t1",
                profile_name="tpm",
                binding_kind="ticket-subagent",
                runner_type="claude-sonnet-4.7",
            )
            await s.add_session_cost("t1", 1000, 200)
            await s.create_session(
                session_id="t2",
                profile_name="tpm",
                binding_kind="ticket-subagent",
                runner_type="claude-sonnet-4.7",
            )
            await s.add_session_cost("t2", 500, 100)
            await s.create_session(
                session_id="d1",
                profile_name="developer",
                binding_kind="ticket-subagent",
                runner_type="claude-sonnet-4.7",
            )
            await s.add_session_cost("d1", 2000, 50)

            rollup = await s.cost_by_profile()
            by_name = {r["profile_name"]: r for r in rollup}
            assert by_name["tpm"]["sessions_count"] == 2
            assert by_name["tpm"]["total_tokens_in"] == 1500
            assert by_name["tpm"]["total_tokens_out"] == 300
            assert by_name["developer"]["sessions_count"] == 1
            assert by_name["developer"]["total_tokens_in"] == 2000
            await s.close()

        run(_t())

    def test_cost_by_ticket_excludes_null(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            await s.create_session(
                session_id="t1",
                profile_name="tpm",
                binding_kind="ticket-subagent",
                runner_type="claude-sonnet-4.7",
                ticket_id=42,
            )
            await s.add_session_cost("t1", 100, 10)
            await s.create_session(
                session_id="s1",
                profile_name="secretary",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.7",
                # no ticket_id — should be excluded
            )
            await s.add_session_cost("s1", 9999, 9999)

            rollup = await s.cost_by_ticket()
            assert len(rollup) == 1
            assert rollup[0]["ticket_id"] == 42
            assert rollup[0]["total_tokens_in"] == 100
            await s.close()

        run(_t())

    def test_cost_totals_includes_today_and_lifetime(self, db_path):
        async def _t():
            s = await _make_store(db_path)
            await s.create_session(
                session_id="t1",
                profile_name="tpm",
                binding_kind="ticket-subagent",
                runner_type="claude-sonnet-4.7",
            )
            await s.add_session_cost("t1", 1234, 567)

            totals = await s.cost_totals()
            assert totals["today"]["tokens_in"] == 1234
            assert totals["today"]["tokens_out"] == 567
            assert totals["today"]["sessions_count"] == 1
            assert totals["week"]["tokens_in"] == 1234
            assert totals["lifetime"]["tokens_in"] == 1234
            assert totals["lifetime"]["sessions_count"] == 1
            await s.close()

        run(_t())
