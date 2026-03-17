"""Tests for SQLiteTaskClient."""

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

            # Both should have assignee (it's a native column now)
            assert "assignee" in pruned
            assert "assignee" in raw
            # Pruned should have depends_on (detail field)
            assert "depends_on" in pruned
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
                "INSERT INTO tickets (headline, status, tags, assignee, projectId, date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Old task", 4, "agent:dev-emma", "dev-emma", 3, "2020-01-01 00:00:00"),
            )
            await db.commit()

            stale = await client.get_stale_in_progress("dev-emma", threshold_minutes=30)
            assert len(stale) == 1
            assert stale[0]["headline"] == "Old task"
            await client.close()

        run(_test())

    def test_get_unattended_new_tickets(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, assignee, projectId, date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Old new task", 3, "agent:dev-alex", "dev-alex", 3, "2020-01-01 00:00:00"),
            )
            await db.commit()

            unattended = await client.get_unattended_new_tickets("dev-alex", threshold_minutes=30)
            assert len(unattended) == 1
            assert unattended[0]["headline"] == "Old new task"

            # Other agent should have none
            unattended = await client.get_unattended_new_tickets("dev-emma", threshold_minutes=30)
            assert len(unattended) == 0
            await client.close()

        run(_test())


# ── Schema upgrade tests ──


class TestNativeAssigneeColumn:
    """Tests for the native assignee column feature."""

    def test_create_sets_assignee_column(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test", assignee="dev-alex")
            ticket = await client.get_ticket(tid)
            assert ticket["assignee"] == "dev-alex"
            # Also check tags for backward compat
            assert "agent:dev-alex" in ticket["tags"]
            await client.close()

        run(_test())

    def test_update_sets_assignee_column(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test", assignee="dev-alex")
            await client.update_ticket(tid, assignee="qa-lucy")

            ticket = await client.get_ticket(tid)
            assert ticket["assignee"] == "qa-lucy"
            assert "agent:qa-lucy" in ticket["tags"]
            # Old agent tag should be removed
            assert "agent:dev-alex" not in ticket["tags"]
            await client.close()

        run(_test())

    def test_list_tickets_by_assignee_uses_column(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("T1", assignee="dev-alex")
            await client.create_ticket("T2", assignee="dev-emma")
            await client.create_ticket("T3", assignee="dev-alex")

            result = await client.list_tickets(assignee="dev-alex")
            assert result["total"] == 2
            for t in result["tickets"]:
                assert t["assignee"] == "dev-alex"
            await client.close()

        run(_test())

    def test_assignee_in_summary_fields(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test", assignee="dev-alex")
            result = await client.list_tickets()
            assert result["total"] == 1
            ticket = result["tickets"][0]
            assert "assignee" in ticket
            assert ticket["assignee"] == "dev-alex"
            await client.close()

        run(_test())


class TestMigration:
    """Tests for schema migration and backfill."""

    def test_backfill_assignee_from_tags(self, db_path):
        """Simulate an old DB with tags but no assignee column values."""
        async def _test():
            import aiosqlite

            # Create DB with old schema (no assignee column)
            old_schema = """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                headline TEXT NOT NULL DEFAULT '',
                description TEXT DEFAULT '',
                type TEXT DEFAULT 'task',
                status INTEGER DEFAULT 3,
                priority TEXT DEFAULT 'medium',
                tags TEXT DEFAULT '',
                projectId INTEGER DEFAULT 3,
                userId INTEGER DEFAULT 1,
                date TEXT DEFAULT '',
                dateToEdit TEXT DEFAULT '',
                editFrom TEXT DEFAULT '0000-00-00 00:00:00',
                editTo TEXT DEFAULT '0000-00-00 00:00:00',
                dependingTicketId INTEGER DEFAULT 0,
                milestoneid INTEGER DEFAULT 0,
                storypoints INTEGER DEFAULT 0,
                sprint INTEGER DEFAULT 0,
                acceptanceCriteria TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL DEFAULT '',
                module TEXT DEFAULT 'ticket',
                moduleId INTEGER NOT NULL,
                userId INTEGER DEFAULT 1,
                date TEXT DEFAULT ''
            );
            """
            # Pre-populate with old data (no assignee column)
            db = await aiosqlite.connect(db_path)
            await db.executescript(old_schema)
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Old ticket", 3, "agent:dev-emma,feedback", 3, "2025-01-01"),
            )
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("No agent", 3, "feedback", 3, "2025-01-01"),
            )
            await db.commit()
            await db.close()

            # Now open with SQLiteTaskClient — migration should add columns + backfill
            client = SQLiteTaskClient(db_path)
            # Trigger _get_db and migration
            ticket1 = await client.get_ticket(1)
            assert ticket1["assignee"] == "dev-emma"

            ticket2 = await client.get_ticket(2)
            # No agent tag, so assignee should remain empty/None
            assert not ticket2.get("assignee")

            # Verify native column queries work
            result = await client.list_tickets(assignee="dev-emma")
            assert result["total"] == 1
            assert result["tickets"][0]["headline"] == "Old ticket"
            await client.close()

        run(_test())


class TestCommentAuthor:
    """Tests for the comment author feature."""

    def test_add_comment_with_author(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test")
            cid = await client.add_comment("ticket", tid, "Hello", author="dev-alex")
            assert isinstance(cid, int)

            comments = await client.get_comments("ticket", tid)
            assert len(comments) == 1
            assert comments[0]["author"] == "dev-alex"
            assert comments[0]["text"] == "Hello"
            await client.close()

        run(_test())

    def test_add_comment_without_author(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test")
            await client.add_comment("ticket", tid, "No author")

            comments = await client.get_comments("ticket", tid)
            assert len(comments) == 1
            assert comments[0]["author"] == ""  # Default empty
            await client.close()

        run(_test())

    def test_author_in_comment_fields(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test")
            await client.add_comment("ticket", tid, "Test comment", author="qa-lucy")

            comments = await client.get_comments("ticket", tid)
            assert "author" in comments[0]
            await client.close()

        run(_test())


class TestDependsOn:
    """Tests for the native depends_on column."""

    def test_update_depends_on(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            t1 = await client.create_ticket("Dep 1")
            t2 = await client.create_ticket("Dep 2")
            t3 = await client.create_ticket("Blocked ticket")

            result = await client.update_depends_on(t3, f"{t1},{t2}")
            assert result is True

            ticket = await client.get_ticket(t3)
            assert ticket["depends_on"] == f"{t1},{t2}"
            await client.close()

        run(_test())

    def test_depends_on_auto_lock(self, db_path):
        """Status=3 ticket with unresolved depends_on should be auto-locked."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            dep_id = await client.create_ticket("Dependency", status=4)
            blocked_id = await client.create_ticket("Blocked")
            await client.update_depends_on(blocked_id, str(dep_id))

            messages = await client.check_and_unblock_deps()
            assert len(messages) == 1

            ticket = await client.get_ticket(blocked_id)
            assert ticket["status"] == 1  # Auto-locked
            await client.close()

        run(_test())

    def test_depends_on_auto_unlock(self, db_path):
        """Status=1 ticket whose depends_on are all done should be auto-unlocked."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            dep_id = await client.create_ticket("Dependency", status=0)  # Done
            blocked_id = await client.create_ticket("Blocked", status=1)
            await client.update_depends_on(blocked_id, str(dep_id))

            messages = await client.check_and_unblock_deps()
            assert len(messages) == 1

            ticket = await client.get_ticket(blocked_id)
            assert ticket["status"] == 3  # Unblocked
            await client.close()

        run(_test())

    def test_depends_on_merges_with_description(self, db_path):
        """depends_on column and description DEPENDS_ON should be merged."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            dep1 = await client.create_ticket("Dep 1", status=0)
            dep2 = await client.create_ticket("Dep 2", status=0)
            blocked = await client.create_ticket(
                "Blocked", status=1,
                description=f"DEPENDS_ON: #{dep1}",
            )
            # Also set native depends_on with dep2
            await client.update_depends_on(blocked, str(dep2))

            # Both deps are done, so should unblock
            messages = await client.check_and_unblock_deps()
            assert len(messages) == 1

            ticket = await client.get_ticket(blocked)
            assert ticket["status"] == 3
            await client.close()

        run(_test())

    def test_depends_on_in_detail_fields(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test")
            await client.update_depends_on(tid, "10,20")

            ticket = await client.get_ticket(tid)
            assert "depends_on" in ticket
            assert ticket["depends_on"] == "10,20"
            await client.close()

        run(_test())


class TestSubtaskAssignee:
    """Tests for subtask assignee handling."""

    def test_subtask_with_assignee(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            parent_id = await client.create_ticket("Parent")
            sub_id = await client.upsert_subtask(
                parent_id, "Subtask", assignee="dev-emma"
            )

            subtasks = await client.get_all_subtasks(parent_id)
            assert len(subtasks) == 1
            assert subtasks[0]["assignee"] == "dev-emma"
            assert "agent:dev-emma" in subtasks[0]["tags"]
            await client.close()

        run(_test())
