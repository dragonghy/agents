"""Tests for the soft-dependency DAG (ticket_dependencies).

Covers:
    - Schema: ticket_dependencies table + indices created
    - add_dependency: insert, idempotency, self-loop rejection,
      direct cycle (A->B then B->A), 3-cycle (A->B->C->A)
    - remove_dependency: returns True/False appropriately
    - get_dependencies / get_dependents: one-hop reads
    - get_descendants / get_ancestors: BFS transitive close, max_depth
    - backfill_ticket_dependencies: seeds rows from dependingTicketId
      and milestoneid columns
    - update_depends_on (MCP tool) mirrors edges into ticket_dependencies
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents_mcp.store import AgentStore


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-deps.db")


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Schema ──


class TestSchema:
    def test_table_and_indices_created(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            cur = await store._db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='ticket_dependencies'"
            )
            row = await cur.fetchone()
            assert row is not None, "ticket_dependencies table should exist"

            cur = await store._db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' "
                "AND name IN ('idx_tdep_ticket','idx_tdep_dep')"
            )
            rows = await cur.fetchall()
            names = sorted(r["name"] for r in rows)
            assert names == ["idx_tdep_dep", "idx_tdep_ticket"]

            await store.close()

        run(_test())


# ── add_dependency ──


class TestAddDependency:
    def test_creates_row(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            result = await store.add_dependency(10, 20)
            assert result["ok"] is True

            cur = await store._db.execute(
                "SELECT ticket_id, depends_on_ticket_id "
                "FROM ticket_dependencies"
            )
            rows = await cur.fetchall()
            assert len(rows) == 1
            assert dict(rows[0]) == {
                "ticket_id": 10,
                "depends_on_ticket_id": 20,
            }
            await store.close()

        run(_test())

    def test_idempotent(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            r1 = await store.add_dependency(10, 20)
            r2 = await store.add_dependency(10, 20)
            assert r1["ok"] is True
            assert r2["ok"] is True

            cur = await store._db.execute(
                "SELECT COUNT(*) AS c FROM ticket_dependencies"
            )
            row = await cur.fetchone()
            assert row["c"] == 1
            await store.close()

        run(_test())

    def test_self_loop_rejected(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            result = await store.add_dependency(10, 10)
            assert result["ok"] is False
            assert result["cycle"] is True

            cur = await store._db.execute(
                "SELECT COUNT(*) AS c FROM ticket_dependencies"
            )
            row = await cur.fetchone()
            assert row["c"] == 0
            await store.close()

        run(_test())

    def test_direct_cycle_rejected(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            r1 = await store.add_dependency(1, 2)
            assert r1["ok"] is True

            r2 = await store.add_dependency(2, 1)
            assert r2["ok"] is False
            assert r2["cycle"] is True

            cur = await store._db.execute(
                "SELECT COUNT(*) AS c FROM ticket_dependencies"
            )
            row = await cur.fetchone()
            assert row["c"] == 1  # only the first edge inserted
            await store.close()

        run(_test())

    def test_three_cycle_rejected(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            assert (await store.add_dependency(1, 2))["ok"] is True
            assert (await store.add_dependency(2, 3))["ok"] is True
            r = await store.add_dependency(3, 1)
            assert r["ok"] is False
            assert r["cycle"] is True

            cur = await store._db.execute(
                "SELECT COUNT(*) AS c FROM ticket_dependencies"
            )
            row = await cur.fetchone()
            assert row["c"] == 2
            await store.close()

        run(_test())

    def test_diamond_is_allowed(self, db_path):
        """A->B, A->C, B->D, C->D is a DAG, not a cycle."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            for ticket, dep in [(1, 2), (1, 3), (2, 4), (3, 4)]:
                r = await store.add_dependency(ticket, dep)
                assert r["ok"] is True, f"({ticket},{dep}) should be allowed"
            await store.close()

        run(_test())


# ── remove_dependency ──


class TestRemoveDependency:
    def test_remove_existing(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            await store.add_dependency(1, 2)
            removed = await store.remove_dependency(1, 2)
            assert removed is True

            cur = await store._db.execute(
                "SELECT COUNT(*) AS c FROM ticket_dependencies"
            )
            row = await cur.fetchone()
            assert row["c"] == 0
            await store.close()

        run(_test())

    def test_remove_missing(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()
            removed = await store.remove_dependency(999, 1000)
            assert removed is False
            await store.close()

        run(_test())


# ── get_dependencies / get_dependents ──


class TestOneHop:
    def test_get_dependencies(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()
            await store.add_dependency(10, 20)
            await store.add_dependency(10, 30)
            await store.add_dependency(11, 30)

            deps = await store.get_dependencies(10)
            assert sorted(deps) == [20, 30]

            deps11 = await store.get_dependencies(11)
            assert deps11 == [30]

            deps_empty = await store.get_dependencies(999)
            assert deps_empty == []
            await store.close()

        run(_test())

    def test_get_dependents(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()
            await store.add_dependency(10, 20)
            await store.add_dependency(11, 20)
            await store.add_dependency(12, 30)

            d20 = await store.get_dependents(20)
            assert sorted(d20) == [10, 11]

            d30 = await store.get_dependents(30)
            assert d30 == [12]

            d_empty = await store.get_dependents(999)
            assert d_empty == []
            await store.close()

        run(_test())


# ── get_descendants / get_ancestors (BFS) ──


class TestTransitiveClose:
    def test_descendants_chain(self, db_path):
        """1 -> 2 -> 3 -> 4. descendants(1) = [2,3,4]."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()
            await store.add_dependency(1, 2)
            await store.add_dependency(2, 3)
            await store.add_dependency(3, 4)

            desc = await store.get_descendants(1)
            assert sorted(desc) == [2, 3, 4]

            desc2 = await store.get_descendants(2)
            assert sorted(desc2) == [3, 4]

            await store.close()

        run(_test())

    def test_descendants_max_depth_one(self, db_path):
        """max_depth=1 returns only direct dependencies."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()
            await store.add_dependency(1, 2)
            await store.add_dependency(2, 3)
            await store.add_dependency(3, 4)

            depth1 = await store.get_descendants(1, max_depth=1)
            assert sorted(depth1) == [2]

            depth2 = await store.get_descendants(1, max_depth=2)
            assert sorted(depth2) == [2, 3]
            await store.close()

        run(_test())

    def test_ancestors_chain(self, db_path):
        """1 -> 2 -> 3. ancestors(3) = [1,2]."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()
            await store.add_dependency(1, 2)
            await store.add_dependency(2, 3)
            await store.add_dependency(3, 4)

            anc4 = await store.get_ancestors(4)
            assert sorted(anc4) == [1, 2, 3]

            anc3 = await store.get_ancestors(3)
            assert sorted(anc3) == [1, 2]
            await store.close()

        run(_test())

    def test_ancestors_max_depth_one(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()
            await store.add_dependency(1, 2)
            await store.add_dependency(2, 3)

            depth1 = await store.get_ancestors(3, max_depth=1)
            assert sorted(depth1) == [2]
            await store.close()

        run(_test())

    def test_descendants_diamond(self, db_path):
        """Diamond: 1->2, 1->3, 2->4, 3->4. descendants(1) dedup = [2,3,4]."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()
            for a, b in [(1, 2), (1, 3), (2, 4), (3, 4)]:
                await store.add_dependency(a, b)

            desc = await store.get_descendants(1)
            assert sorted(desc) == [2, 3, 4]
            await store.close()

        run(_test())


# ── backfill ──


class TestBackfill:
    def test_backfill_inserts_rows(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            tickets = [
                {"id": 100, "dependingTicketId": 0, "milestoneid": 0},
                {"id": 101, "dependingTicketId": 100, "milestoneid": 0},
                {"id": 102, "dependingTicketId": 100, "milestoneid": 50},
                # Self-reference should be skipped
                {"id": 103, "dependingTicketId": 103, "milestoneid": 0},
                # None / missing values handled
                {"id": 104, "dependingTicketId": None, "milestoneid": None},
            ]
            inserted = await store.backfill_ticket_dependencies(tickets)
            # 101->100, 102->100, 102->50 = 3 edges
            assert inserted == 3

            d101 = await store.get_dependencies(101)
            assert d101 == [100]

            d102 = await store.get_dependencies(102)
            assert sorted(d102) == [50, 100]

            d103 = await store.get_dependencies(103)
            assert d103 == []

            await store.close()

        run(_test())

    def test_backfill_idempotent(self, db_path):
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            tickets = [
                {"id": 101, "dependingTicketId": 100, "milestoneid": 0},
            ]
            first = await store.backfill_ticket_dependencies(tickets)
            second = await store.backfill_ticket_dependencies(tickets)
            assert first == 1
            assert second == 0  # nothing new inserted

            cur = await store._db.execute(
                "SELECT COUNT(*) AS c FROM ticket_dependencies"
            )
            row = await cur.fetchone()
            assert row["c"] == 1
            await store.close()

        run(_test())


# ── Old-API mirroring (server.py wrappers) ──


class TestUpdateDependsOnMirror:
    def test_update_depends_on_mirrors_into_dag(self, tmp_path):
        """Calling the MCP update_depends_on tool should also populate
        ticket_dependencies via the new join table."""
        async def _test():
            store = AgentStore(str(tmp_path / "mcp.db"))
            await store.initialize()

            from agents_mcp.server import update_depends_on

            mock_client = MagicMock()
            mock_client.update_depends_on = AsyncMock(return_value=True)

            fn = getattr(update_depends_on, "fn", update_depends_on)

            with patch(
                "agents_mcp.server.get_client", return_value=mock_client
            ), patch(
                "agents_mcp.server.get_store",
                new=AsyncMock(return_value=store),
            ):
                # First call: add edges to 20 and 30
                await fn(ticket_id=10, depends_on="20, 30")
                deps = await store.get_dependencies(10)
                assert sorted(deps) == [20, 30]

                # Second call: drop 20, keep 30, add 40
                await fn(ticket_id=10, depends_on="30,40")
                deps = await store.get_dependencies(10)
                assert sorted(deps) == [30, 40]

                # Empty string clears all DAG edges
                await fn(ticket_id=10, depends_on="")
                deps = await store.get_dependencies(10)
                assert deps == []

            await store.close()

        run(_test())

    def test_update_depends_on_skips_cycle_silently(self, tmp_path):
        """If update_depends_on receives an id that would create a cycle,
        the legacy update_ticket call still returns and the DAG stays intact."""
        async def _test():
            store = AgentStore(str(tmp_path / "mcp2.db"))
            await store.initialize()
            # Pre-existing edge 20 -> 10 (so adding 10 -> 20 closes a cycle).
            await store.add_dependency(20, 10)

            from agents_mcp.server import update_depends_on

            mock_client = MagicMock()
            mock_client.update_depends_on = AsyncMock(return_value=True)
            fn = getattr(update_depends_on, "fn", update_depends_on)

            with patch(
                "agents_mcp.server.get_client", return_value=mock_client
            ), patch(
                "agents_mcp.server.get_store",
                new=AsyncMock(return_value=store),
            ):
                # Should not raise even though the edge is rejected.
                result_str = await fn(ticket_id=10, depends_on="20")
                # Legacy path still claims success
                assert json.loads(result_str) is True

            # The cyclic edge was NOT inserted
            assert await store.get_dependencies(10) == []
            # The pre-existing edge is intact
            assert await store.get_dependents(10) == [20]
            await store.close()

        run(_test())
