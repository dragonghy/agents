"""Tests for SQLiteTaskClient — drop-in replacement for LeantimeClient."""

import asyncio
import os
import tempfile
import pytest

from agents_mcp.sqlite_task_client import (
    SQLiteTaskClient,
    extract_assignee,
    inject_assignee,
    tags_with_assignee,
)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-tasks.db")


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run(coro):
    """Run an async function in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Helper function tests ──


class TestHelpers:
    def test_extract_assignee(self):
        assert extract_assignee({"tags": "agent:dev-alex"}) == "dev-alex"
        assert extract_assignee({"tags": "feedback,agent:qa-lucy"}) == "qa-lucy"
        assert extract_assignee({"tags": "no-agent-here"}) is None
        assert extract_assignee({"tags": ""}) is None
        assert extract_assignee({}) is None

    def test_inject_assignee(self):
        result = inject_assignee({"id": 1, "tags": "agent:dev-emma"})
        assert result["assignee"] == "dev-emma"
        assert result["id"] == 1

    def test_tags_with_assignee(self):
        assert tags_with_assignee(None, "dev") == "agent:dev"
        assert tags_with_assignee("feedback", "qa") == "feedback,agent:qa"
        assert tags_with_assignee("agent:old,other", "new") == "other,agent:new"


# ── Client CRUD tests ──


class TestCreateAndGet:
    def test_create_ticket(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test ticket", assignee="dev-emma")
            assert isinstance(tid, int)
            assert tid > 0

            ticket = await client.get_ticket(tid)
            assert ticket["headline"] == "Test ticket"
            assert ticket["assignee"] == "dev-emma"
            assert "agent:dev-emma" in ticket["tags"]
            await client.close()

        run(_test())

    def test_create_ticket_with_kwargs(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket(
                "High priority", priority="high", status=4, description="Details here"
            )
            ticket = await client.get_ticket(tid)
            assert ticket["priority"] == "high"
            assert ticket["status"] == 4
            assert ticket["description"] == "Details here"
            await client.close()

        run(_test())

    def test_get_ticket_not_found(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            ticket = await client.get_ticket(9999)
            assert ticket == {}
            await client.close()

        run(_test())

    def test_get_ticket_prune(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Prune test")
            pruned = await client.get_ticket(tid, prune=True)
            raw = await client.get_ticket(tid, prune=False)

            # Pruned should have assignee, raw should not
            assert "assignee" in pruned
            assert "assignee" not in raw
            await client.close()

        run(_test())


class TestListTickets:
    def test_list_basic(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("T1", status=3, assignee="dev-alex")
            await client.create_ticket("T2", status=4, assignee="dev-emma")
            await client.create_ticket("T3", status=0, assignee="dev-alex")

            # Default: status 1,3,4
            result = await client.list_tickets()
            assert result["total"] == 2  # T1 (3) and T2 (4), not T3 (0)

            # All statuses
            result = await client.list_tickets(status="all")
            assert result["total"] == 3
            await client.close()

        run(_test())

    def test_list_by_assignee(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("T1", assignee="dev-alex")
            await client.create_ticket("T2", assignee="dev-emma")

            result = await client.list_tickets(assignee="dev-emma")
            assert result["total"] == 1
            assert result["tickets"][0]["assignee"] == "dev-emma"
            await client.close()

        run(_test())

    def test_list_pagination(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            for i in range(5):
                await client.create_ticket(f"T{i}")

            result = await client.list_tickets(limit=2, offset=1)
            assert len(result["tickets"]) == 2
            assert result["total"] == 5
            assert result["offset"] == 1
            await client.close()

        run(_test())

    def test_list_by_tags(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Feedback", tags="feedback,agent:dev-alex")
            await client.create_ticket("Normal", assignee="dev-alex")

            result = await client.list_tickets(tags="feedback")
            assert result["total"] == 1
            assert result["tickets"][0]["headline"] == "Feedback"
            await client.close()

        run(_test())


class TestUpdateTicket:
    def test_update_status(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("To update", status=3)
            await client.update_ticket(tid, status=4)

            ticket = await client.get_ticket(tid)
            assert ticket["status"] == 4
            await client.close()

        run(_test())

    def test_update_assignee(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Reassign", assignee="dev-alex")
            await client.update_ticket(tid, assignee="qa-lucy")

            ticket = await client.get_ticket(tid)
            assert ticket["assignee"] == "qa-lucy"
            assert "agent:qa-lucy" in ticket["tags"]
            await client.close()

        run(_test())


class TestComments:
    def test_add_and_get(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("With comments")

            cid = await client.add_comment("ticket", tid, "Hello world")
            assert isinstance(cid, int)

            comments = await client.get_comments("ticket", tid)
            assert len(comments) == 1
            assert comments[0]["text"] == "Hello world"
            assert comments[0]["moduleId"] == tid
            await client.close()

        run(_test())

    def test_module_normalization(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Module test")

            # Add with "tickets" (legacy), get with "ticket" (normalized)
            await client.add_comment("tickets", tid, "Legacy module")
            comments = await client.get_comments("ticket", tid)
            assert len(comments) == 1
            await client.close()

        run(_test())


class TestSubtasks:
    def test_subtask_lifecycle(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            parent_id = await client.create_ticket("Parent")

            sub_id = await client.upsert_subtask(parent_id, "Subtask 1")
            assert isinstance(sub_id, int)

            subtasks = await client.get_all_subtasks(parent_id)
            assert len(subtasks) == 1
            assert subtasks[0]["headline"] == "Subtask 1"
            assert subtasks[0]["type"] == "subtask"
            await client.close()

        run(_test())


class TestStatusLabels:
    def test_get_labels(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            labels = await client.get_status_labels()
            assert "3" in labels
            assert labels["3"] == "New"
            assert labels["4"] == "In Progress"
            await client.close()

        run(_test())


class TestDependencyChecking:
    def test_unblock_deps(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            # Create dep ticket (done)
            dep_id = await client.create_ticket("Dep ticket", status=0)
            # Create blocked ticket
            blocked_id = await client.create_ticket(
                "Blocked",
                status=1,
                description=f"DEPENDS_ON: #{dep_id}",
            )

            messages = await client.check_and_unblock_deps()
            assert len(messages) == 1
            assert f"#{blocked_id}" in messages[0]

            ticket = await client.get_ticket(blocked_id)
            assert ticket["status"] == 3  # Unblocked
            await client.close()

        run(_test())

    def test_no_unblock_when_dep_not_done(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            dep_id = await client.create_ticket("Dep ticket", status=4)
            await client.create_ticket(
                "Blocked",
                status=1,
                description=f"DEPENDS_ON: #{dep_id}",
            )

            messages = await client.check_and_unblock_deps()
            assert len(messages) == 0
            await client.close()

        run(_test())


class TestWorkload:
    def test_has_pending_tasks(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("New task", status=3, assignee="dev-emma")

            assert await client.has_pending_tasks("dev-emma") is True
            assert await client.has_pending_tasks("dev-alex") is False
            await client.close()

        run(_test())

    def test_get_agent_workload(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("In progress", status=4, assignee="dev-emma")
            await client.create_ticket("New", status=3, assignee="dev-emma")
            await client.create_ticket("Blocked", status=1, assignee="dev-emma")
            await client.create_ticket("Other agent", status=3, assignee="dev-alex")

            workloads = await client.get_agent_workload(["dev-emma", "dev-alex"])
            emma = workloads["dev-emma"]
            assert emma["in_progress"] == 1
            assert emma["new"] == 1
            assert emma["blocked"] == 1
            assert emma["total_active"] == 2

            alex = workloads["dev-alex"]
            assert alex["new"] == 1
            assert alex["total_active"] == 1
            await client.close()

        run(_test())

    def test_get_stale_in_progress(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            # Create a ticket with an old date
            db = await client._get_db()
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Old task", 4, "agent:dev-emma", 3, "2020-01-01 00:00:00"),
            )
            await db.commit()

            stale = await client.get_stale_in_progress("dev-emma", threshold_minutes=30)
            assert len(stale) == 1
            assert stale[0]["headline"] == "Old task"
            await client.close()

        run(_test())
