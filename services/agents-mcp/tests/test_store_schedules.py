"""Tests for schedule seed/delete behavior in AgentStore."""

import asyncio
import pytest

from agents_mcp.store import AgentStore


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-store.db")


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestScheduleSeed:
    """Tests for seed_schedule not recreating deleted schedules."""

    def test_seed_creates_schedule(self, db_path):
        """seed_schedule should create a schedule for a new agent."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            result = await store.seed_schedule("agent-a", 24.0, "Do daily work")
            assert result is not None
            assert result["agent_id"] == "agent-a"
            assert result["interval_hours"] == 24.0

            schedules = await store.get_agent_schedules("agent-a")
            assert len(schedules) == 1
            await store.close()

        run(_test())

    def test_seed_skips_existing(self, db_path):
        """seed_schedule should skip if agent already has schedules."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            await store.create_schedule("agent-a", 24.0, "First schedule")
            result = await store.seed_schedule("agent-a", 12.0, "Second schedule")
            assert result is None

            schedules = await store.get_agent_schedules("agent-a")
            assert len(schedules) == 1
            assert schedules[0]["prompt"] == "First schedule"
            await store.close()

        run(_test())

    def test_deleted_schedule_not_recreated(self, db_path):
        """After deleting a schedule, seed_schedule should NOT recreate it."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            # Seed a schedule
            sched = await store.seed_schedule("user-sophia", 8.0, "Check inbox and tasks")
            assert sched is not None

            # Delete it
            deleted = await store.delete_schedule(sched["id"])
            assert deleted is True

            # Verify agent has no schedules
            schedules = await store.get_agent_schedules("user-sophia")
            assert len(schedules) == 0

            # Try to seed the same schedule again (simulates daemon restart)
            result = await store.seed_schedule("user-sophia", 8.0, "Check inbox and tasks")
            assert result is None  # Should NOT recreate

            # Still no schedules
            schedules = await store.get_agent_schedules("user-sophia")
            assert len(schedules) == 0
            await store.close()

        run(_test())

    def test_different_prompt_can_be_seeded_after_delete(self, db_path):
        """A different prompt should still be seedable after deleting a different one."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            # Seed and delete schedule A
            sched = await store.seed_schedule("agent-b", 24.0, "Prompt A")
            assert sched is not None
            await store.delete_schedule(sched["id"])

            # Seed schedule B (different prompt) - should succeed
            # But seed_schedule checks for ANY existing schedule first,
            # and since there are none, it checks deleted_schedules.
            # Prompt B has a different hash, so it should be allowed.
            result = await store.seed_schedule("agent-b", 24.0, "Prompt B")
            assert result is not None
            assert result["prompt"] == "Prompt B"
            await store.close()

        run(_test())

    def test_delete_records_in_deleted_schedules_table(self, db_path):
        """Deleting a schedule should record it in deleted_schedules table."""
        async def _test():
            store = AgentStore(db_path)
            await store.initialize()

            sched = await store.create_schedule("agent-c", 12.0, "Some prompt")
            await store.delete_schedule(sched["id"])

            # Check the deleted_schedules table directly
            async with store._db.execute(
                "SELECT * FROM deleted_schedules WHERE agent_id = ?",
                ("agent-c",),
            ) as cursor:
                rows = await cursor.fetchall()
            assert len(rows) == 1
            await store.close()

        run(_test())
