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

    def test_transitive_cycle_rejected(self, db_path):
        """If B already transitively depends on A (B -> X -> A), then
        adding A -> B must be rejected: it would close the cycle
        A -> B -> X -> A.

        Re-verifies the BFS direction in `_would_create_cycle` after the
        edge-orientation flip. The BFS walks forward from `B` following
        (ticket_id -> depends_on_ticket_id) edges; if it reaches `A`,
        the candidate edge (A, B) would close a cycle.
        """
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            # Build B -> X -> A (B depends on X, X depends on A).
            assert (await store.add_dependency(2, 99))["ok"] is True   # B=2, X=99
            assert (await store.add_dependency(99, 1))["ok"] is True   # X=99, A=1

            # Now A -> B would close cycle A -> B -> X -> A.
            r = await store.add_dependency(1, 2)
            assert r["ok"] is False
            assert r["cycle"] is True

            # Existing edges intact, no cyclic edge inserted.
            cur = await store._db.execute(
                "SELECT COUNT(*) AS c FROM ticket_dependencies"
            )
            assert (await cur.fetchone())["c"] == 2
            assert await store.get_dependencies(1) == []
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
        """Edge orientation: parent depends on child. A row with
        dependingTicketId=100 means 100 is the parent, so the edge is
        (100, row.id)."""
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
            # Edges: (100,101), (100,102), (50,102) = 3 edges
            assert inserted == 3

            # 100 is parent of 101 and 102 → 100 depends on both.
            d100 = await store.get_dependencies(100)
            assert sorted(d100) == [101, 102]

            # 50 is the milestone-parent of 102 → 50 depends on 102.
            d50 = await store.get_dependencies(50)
            assert d50 == [102]

            # Children have no dependencies of their own (in this fixture).
            assert await store.get_dependencies(101) == []
            assert await store.get_dependencies(102) == []
            assert await store.get_dependencies(103) == []

            # 102 is depended on by both its parents.
            assert sorted(await store.get_dependents(102)) == [50, 100]

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

    def test_backfill_umbrella_scenario(self, db_path):
        """Regression for the edge-direction flip.

        Umbrella ticket #493 with sub-tickets #494 and #495. In Leantime,
        #494 and #495 carry dependingTicketId=493. Under the
        "parent depends on child" semantic, the resulting edges should be
        (493, 494) and (493, 495), so:
            - get_dependencies(493) == [494, 495]   (children, one hop)
            - get_dependents(494) == [493]          (parents, one hop)
            - get_descendants(493) == [494, 495]    (transitive children)
            - get_ancestors(494) == [493]           (transitive parents)
        """
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            tickets = [
                {"id": 493, "dependingTicketId": 0, "milestoneid": 0},
                {"id": 494, "dependingTicketId": 493, "milestoneid": 0},
                {"id": 495, "dependingTicketId": 493, "milestoneid": 0},
            ]
            inserted = await store.backfill_ticket_dependencies(tickets)
            assert inserted == 2  # (493,494), (493,495)

            assert sorted(await store.get_dependencies(493)) == [494, 495]
            assert await store.get_dependents(494) == [493]
            assert await store.get_dependents(495) == [493]
            assert sorted(await store.get_descendants(493)) == [494, 495]
            assert await store.get_ancestors(494) == [493]
            assert await store.get_ancestors(495) == [493]

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


class TestUpsertSubtaskMirror:
    def test_upsert_subtask_writes_parent_to_child_edge(self, tmp_path):
        """upsert_subtask(parent=P, ...) creates a subtask S and should
        record edge (P, S) in the DAG — parent depends on child."""
        async def _test():
            store = AgentStore(str(tmp_path / "mcp_subtask.db"))
            await store.initialize()

            from agents_mcp.server import upsert_subtask

            mock_client = MagicMock()
            # Leantime client returns the new subtask id directly (int).
            mock_client.upsert_subtask = AsyncMock(return_value=777)
            fn = getattr(upsert_subtask, "fn", upsert_subtask)

            with patch(
                "agents_mcp.server.get_client", return_value=mock_client
            ), patch(
                "agents_mcp.server.get_store",
                new=AsyncMock(return_value=store),
            ):
                await fn(parent_ticket=500, headline="some subtask")

            # Edge (500, 777): parent 500 depends on its new subtask 777.
            assert await store.get_dependencies(500) == [777]
            assert await store.get_dependents(777) == [500]
            await store.close()

        run(_test())
