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

            result = await client.get_comments("ticket", tid)
            assert isinstance(result, dict)
            assert result["total"] == 1
            comments = result["comments"]
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
            result = await client.get_comments("ticket", tid)
            assert result["total"] == 1
            assert len(result["comments"]) == 1
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

            result = await client.get_comments("ticket", tid)
            comments = result["comments"]
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

            result = await client.get_comments("ticket", tid)
            comments = result["comments"]
            assert len(comments) == 1
            assert comments[0]["author"] == ""  # Default empty
            await client.close()

        run(_test())

    def test_author_in_comment_fields(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Test")
            await client.add_comment("ticket", tid, "Test comment", author="qa-lucy")

            result = await client.get_comments("ticket", tid)
            assert "author" in result["comments"][0]
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


class TestTicketHierarchy:
    """Tests for Project → Milestone → Task hierarchy."""

    def test_create_project_and_milestone(self, db_path):
        """Create project and milestone with proper types and links."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            # Create project
            proj_id = await client.create_ticket(
                "Trading Project", type="project", status=4,
                description="Live trading strategy execution",
            )
            proj = await client.get_ticket(proj_id)
            assert proj["type"] == "project"
            assert proj["status"] == 4

            # Create milestone under project
            ms_id = await client.create_ticket(
                "Deploy Safeguards", type="milestone", status=4,
                dependingTicketId=proj_id,
                description="Set up paper trading safeguards",
            )
            ms = await client.get_ticket(ms_id)
            assert ms["type"] == "milestone"
            assert ms["dependingTicketId"] == proj_id

            # Create task under milestone
            task_id = await client.create_ticket(
                "Implement stop-loss", status=3,
                dependingTicketId=ms_id,
            )
            task = await client.get_ticket(task_id)
            assert task["type"] == "task"
            assert task["dependingTicketId"] == ms_id
            await client.close()

        run(_test())

    def test_get_parent_chain(self, db_path):
        """get_parent_chain should return [milestone, project] for a task."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            proj_id = await client.create_ticket(
                "Project", type="project", status=4,
                description="Project description",
            )
            ms_id = await client.create_ticket(
                "Milestone", type="milestone", status=4,
                dependingTicketId=proj_id,
                description="Milestone description",
            )
            task_id = await client.create_ticket(
                "Task", status=3, dependingTicketId=ms_id,
            )

            chain = await client.get_parent_chain(task_id)
            assert len(chain) == 2
            # First in chain is immediate parent (milestone)
            assert chain[0]["id"] == ms_id
            assert chain[0]["type"] == "milestone"
            assert chain[0]["description"] == "Milestone description"
            # Second is grandparent (project)
            assert chain[1]["id"] == proj_id
            assert chain[1]["type"] == "project"
            assert chain[1]["description"] == "Project description"
            await client.close()

        run(_test())

    def test_get_parent_chain_no_parent(self, db_path):
        """get_parent_chain returns [] for standalone tasks."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            task_id = await client.create_ticket("Standalone task")

            chain = await client.get_parent_chain(task_id)
            assert chain == []
            await client.close()

        run(_test())

    def test_get_parent_chain_single_level(self, db_path):
        """get_parent_chain works for task directly under project."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            proj_id = await client.create_ticket(
                "Project", type="project", status=4,
            )
            task_id = await client.create_ticket(
                "Task", status=3, dependingTicketId=proj_id,
            )

            chain = await client.get_parent_chain(task_id)
            assert len(chain) == 1
            assert chain[0]["id"] == proj_id
            await client.close()

        run(_test())

    def test_get_children(self, db_path):
        """get_children returns direct children of any type."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            proj_id = await client.create_ticket(
                "Project", type="project", status=4,
            )
            ms1 = await client.create_ticket(
                "Milestone 1", type="milestone", status=4,
                dependingTicketId=proj_id,
            )
            ms2 = await client.create_ticket(
                "Milestone 2", type="milestone", status=3,
                dependingTicketId=proj_id,
            )

            children = await client.get_children(proj_id)
            assert len(children) == 2
            assert {c["id"] for c in children} == {ms1, ms2}
            await client.close()

        run(_test())

    def test_get_children_with_type_filter(self, db_path):
        """get_children filters by child_type."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            ms_id = await client.create_ticket(
                "Milestone", type="milestone", status=4,
            )
            task1 = await client.create_ticket(
                "Task", status=3, dependingTicketId=ms_id,
            )
            sub1 = await client.upsert_subtask(ms_id, "Subtask")

            all_children = await client.get_children(ms_id)
            assert len(all_children) == 2

            tasks_only = await client.get_children(ms_id, child_type="task")
            assert len(tasks_only) == 1
            assert tasks_only[0]["id"] == task1

            subtasks_only = await client.get_children(ms_id, child_type="subtask")
            assert len(subtasks_only) == 1
            assert subtasks_only[0]["id"] == sub1
            await client.close()

        run(_test())

    def test_list_tickets_type_filter(self, db_path):
        """list_tickets with ticket_type filter excludes other types."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Project", type="project", status=4)
            await client.create_ticket("Milestone", type="milestone", status=4)
            await client.create_ticket("Task 1", status=3)
            await client.create_ticket("Task 2", status=4)

            # All types
            result = await client.list_tickets(status="all")
            assert result["total"] == 4

            # Only tasks
            result = await client.list_tickets(ticket_type="task", status="all")
            assert result["total"] == 2
            for t in result["tickets"]:
                assert t["type"] == "task"

            # Only projects
            result = await client.list_tickets(ticket_type="project", status="all")
            assert result["total"] == 1
            assert result["tickets"][0]["headline"] == "Project"
            await client.close()

        run(_test())

    def test_list_tickets_parent_filter(self, db_path):
        """list_tickets with parent_id filter returns children."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            proj_id = await client.create_ticket("Project", type="project", status=4)
            ms_id = await client.create_ticket(
                "Milestone", type="milestone", status=4,
                dependingTicketId=proj_id,
            )
            await client.create_ticket(
                "Task under milestone", status=3, dependingTicketId=ms_id,
            )
            await client.create_ticket("Standalone task", status=3)

            result = await client.list_tickets(parent_id=ms_id, status="all")
            assert result["total"] == 1
            assert result["tickets"][0]["headline"] == "Task under milestone"
            await client.close()

        run(_test())

    def test_projects_not_in_dispatch_query(self, db_path):
        """Projects and milestones should be excluded from dispatch queries."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Project", type="project", status=3)
            await client.create_ticket("Milestone", type="milestone", status=3)
            await client.create_ticket("Actionable task", status=3)

            # Dispatch query: type='task', status=3
            result = await client.list_tickets(status="3", ticket_type="task", limit=0)
            assert result["total"] == 1
            assert result["tickets"][0]["headline"] == "Actionable task"
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


# ── Pagination default tests ──


class TestPaginationDefault:
    """Tests for the default limit=20 pagination behavior."""

    def test_default_limit_is_20(self, db_path):
        """list_tickets should return at most 20 tickets by default."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            # Create 25 tickets
            for i in range(25):
                await client.create_ticket(f"Ticket {i}")

            result = await client.list_tickets()
            assert result["total"] == 25
            assert len(result["tickets"]) == 20
            assert result["limit"] == 20
            await client.close()

        run(_test())

    def test_limit_zero_returns_all(self, db_path):
        """limit=0 should return all tickets (backward compat)."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            for i in range(25):
                await client.create_ticket(f"Ticket {i}")

            result = await client.list_tickets(limit=0)
            assert result["total"] == 25
            assert len(result["tickets"]) == 25
            await client.close()

        run(_test())

    def test_custom_limit(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            for i in range(10):
                await client.create_ticket(f"Ticket {i}")

            result = await client.list_tickets(limit=5, offset=3)
            assert result["total"] == 10
            assert len(result["tickets"]) == 5
            assert result["offset"] == 3
            assert result["limit"] == 5
            await client.close()

        run(_test())


# ── FTS search tests ──


class TestSearchTickets:
    """Tests for FTS5 full-text search."""

    def test_basic_search(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Desktop scroll tool", description="Add scroll support to desktop module")
            await client.create_ticket("Browser navigation", description="Fix browser back button")
            await client.create_ticket("Desktop drag tool", description="Add drag support to desktop")

            result = await client.search_tickets("desktop")
            assert result["total"] == 2
            headlines = [t["headline"] for t in result["tickets"]]
            assert "Desktop scroll tool" in headlines
            assert "Desktop drag tool" in headlines
            await client.close()

        run(_test())

    def test_search_description(self, db_path):
        """Search should match description content too."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Generic title", description="Contains FTS5 keyword")
            await client.create_ticket("Another title", description="Nothing special here")

            result = await client.search_tickets("FTS5")
            assert result["total"] == 1
            assert result["tickets"][0]["headline"] == "Generic title"
            await client.close()

        run(_test())

    def test_search_with_status_filter(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Open task", status=3, description="agent hub feature")
            await client.create_ticket("Done task", status=0, description="agent hub bugfix")

            # Only status=3
            result = await client.search_tickets("agent hub", status="3")
            assert result["total"] == 1
            assert result["tickets"][0]["headline"] == "Open task"
            await client.close()

        run(_test())

    def test_search_with_assignee_filter(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Alex task", assignee="dev-alex", description="MCP optimization")
            await client.create_ticket("Emma task", assignee="dev-emma", description="MCP bugfix")

            result = await client.search_tickets("MCP", assignee="dev-alex")
            assert result["total"] == 1
            assert result["tickets"][0]["assignee"] == "dev-alex"
            await client.close()

        run(_test())

    def test_search_with_time_range(self, db_path):
        """time_range='7d' should only return recent tickets."""
        async def _test():
            import aiosqlite
            client = SQLiteTaskClient(db_path)

            # Recent ticket (via normal create)
            await client.create_ticket("Recent feature", description="New MCP search")

            # Old ticket (manually insert with old date)
            db = await client._get_db()
            await db.execute(
                "INSERT INTO tickets (headline, description, status, projectId, date, assignee) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Old feature", "Old MCP search", 3, 3, "2020-01-01 00:00:00", ""),
            )
            await db.commit()
            # Rebuild FTS to include the manually inserted ticket
            await client._migrate_fts(db)

            # Without time range: both
            result = await client.search_tickets("MCP search")
            assert result["total"] == 2

            # With time range: only recent
            result = await client.search_tickets("MCP search", time_range="7d")
            assert result["total"] == 1
            assert result["tickets"][0]["headline"] == "Recent feature"
            await client.close()

        run(_test())

    def test_search_empty_query(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Some ticket")

            result = await client.search_tickets("")
            assert result["total"] == 0
            assert result["tickets"] == []
            await client.close()

        run(_test())

    def test_search_no_results(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("Some ticket", description="Regular content")

            result = await client.search_tickets("nonexistent_keyword_xyz")
            assert result["total"] == 0
            await client.close()

        run(_test())

    def test_search_limit(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            for i in range(15):
                await client.create_ticket(f"Feature {i}", description="common keyword")

            result = await client.search_tickets("common keyword", limit=5)
            assert len(result["tickets"]) == 5
            await client.close()

        run(_test())

    def test_fts_syncs_on_create(self, db_path):
        """FTS should be updated when new tickets are created."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            # Create initial tickets
            await client.create_ticket("Initial", description="first ticket")
            result = await client.search_tickets("Initial")
            assert result["total"] == 1

            # Create another ticket (FTS should auto-sync)
            await client.create_ticket("Second ticket", description="added later")
            result = await client.search_tickets("Second")
            assert result["total"] == 1
            await client.close()

        run(_test())

    def test_fts_syncs_on_update(self, db_path):
        """FTS should be updated when tickets are modified."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Alpha headline", description="some content")

            # Update headline to something completely different
            await client.update_ticket(tid, headline="Beta headline")

            result = await client.search_tickets("Beta")
            assert result["total"] == 1

            # Old unique keyword should no longer match
            result = await client.search_tickets("Alpha")
            assert result["total"] == 0
            await client.close()

        run(_test())


# ── Comment pagination tests ──


class TestCommentPagination:
    """Tests for comment pagination (get_comments returns dict with pagination)."""

    def test_default_limit(self, db_path):
        """Default limit=10 should paginate comments."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Pagination test")

            # Create 15 comments
            for i in range(15):
                await client.add_comment("ticket", tid, f"Comment {i}")

            result = await client.get_comments("ticket", tid)
            assert result["total"] == 15
            assert len(result["comments"]) == 10
            assert result["limit"] == 10
            assert result["offset"] == 0
            await client.close()

        run(_test())

    def test_custom_limit_and_offset(self, db_path):
        """Custom limit and offset should work correctly."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Pagination test")

            for i in range(20):
                await client.add_comment("ticket", tid, f"Comment {i}")

            result = await client.get_comments("ticket", tid, limit=5, offset=10)
            assert result["total"] == 20
            assert len(result["comments"]) == 5
            assert result["limit"] == 5
            assert result["offset"] == 10
            # Comments are ordered by id, so offset=10 means starting from 11th
            assert result["comments"][0]["text"] == "Comment 10"
            await client.close()

        run(_test())

    def test_limit_zero_returns_all(self, db_path):
        """limit=0 should return all comments (backward compat)."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Pagination test")

            for i in range(15):
                await client.add_comment("ticket", tid, f"Comment {i}")

            result = await client.get_comments("ticket", tid, limit=0)
            assert result["total"] == 15
            assert len(result["comments"]) == 15
            await client.close()

        run(_test())

    def test_returns_dict_format(self, db_path):
        """get_comments should return a dict with comments, total, limit, offset."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Format test")
            await client.add_comment("ticket", tid, "One comment")

            result = await client.get_comments("ticket", tid)
            assert isinstance(result, dict)
            assert "comments" in result
            assert "total" in result
            assert "limit" in result
            assert "offset" in result
            assert isinstance(result["comments"], list)
            await client.close()

        run(_test())
