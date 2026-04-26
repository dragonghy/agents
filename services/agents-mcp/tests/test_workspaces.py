"""Tests for the Workspace hierarchy (ticket #490).

Covers:
    - Schema: workspaces table created, workspace_id column on tickets
    - Seeding: Work + Personal seeded automatically
    - CRUD: create_workspace, list_workspaces, get_workspace, update_workspace
    - Validation: kind allow-list, unique name, empty name
    - Auto-derivation: tickets inherit workspace_id from parent project
    - list_tickets workspace_id filter
    - search_tickets workspace_id filter
    - Multi-level parent chain (project → milestone → task)
    - Backward compat: list_tickets with no workspace filter returns everything
"""

import asyncio

import pytest

from agents_mcp.sqlite_task_client import (
    DEFAULT_PERSONAL_WORKSPACE_ID,
    DEFAULT_WORK_WORKSPACE_ID,
    SQLiteTaskClient,
    WORKSPACE_KINDS,
)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-tasks.db")


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Schema + seeding ──


class TestSchemaAndSeeding:
    def test_workspaces_table_created(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            cur = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workspaces'"
            )
            row = await cur.fetchone()
            assert row is not None, "workspaces table should be created"
            await client.close()

        run(_test())

    def test_workspace_id_column_on_tickets(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            cur = await db.execute("PRAGMA table_info(tickets)")
            cols = [row["name"] for row in await cur.fetchall()]
            assert "workspace_id" in cols
            await client.close()

        run(_test())

    def test_default_workspaces_seeded(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            ws_list = await client.list_workspaces()
            names = sorted(w["name"] for w in ws_list)
            assert "Work" in names
            assert "Personal" in names
            # IDs match the constants
            work = await client.get_workspace(DEFAULT_WORK_WORKSPACE_ID)
            personal = await client.get_workspace(DEFAULT_PERSONAL_WORKSPACE_ID)
            assert work["name"] == "Work"
            assert work["kind"] == "work"
            assert personal["name"] == "Personal"
            assert personal["kind"] == "personal"
            await client.close()

        run(_test())

    def test_seeding_idempotent(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client._get_db()  # first migration
            await client.close()

            client2 = SQLiteTaskClient(db_path)
            ws_list = await client2.list_workspaces()
            # Still exactly Work + Personal — no duplicates created
            names = [w["name"] for w in ws_list]
            assert names.count("Work") == 1
            assert names.count("Personal") == 1
            await client2.close()

        run(_test())


# ── CRUD ──


class TestWorkspaceCRUD:
    def test_create_and_get(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            ws_id = await client.create_workspace(
                name="Side Hustle", kind="other",
                description="My weekend project", default_assignee="dev-alex",
            )
            assert ws_id > 2  # Higher than seeded Work/Personal

            ws = await client.get_workspace(ws_id)
            assert ws["name"] == "Side Hustle"
            assert ws["kind"] == "other"
            assert ws["description"] == "My weekend project"
            assert ws["default_assignee"] == "dev-alex"
            await client.close()

        run(_test())

    def test_create_invalid_kind_raises(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            with pytest.raises(ValueError, match="Invalid kind"):
                await client.create_workspace(name="Bogus", kind="not-a-kind")
            await client.close()

        run(_test())

    def test_create_empty_name_raises(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            with pytest.raises(ValueError, match="non-empty"):
                await client.create_workspace(name="   ")
            await client.close()

        run(_test())

    def test_create_duplicate_name_raises(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            with pytest.raises(ValueError, match="already exists"):
                await client.create_workspace(name="Work")
            await client.close()

        run(_test())

    def test_update_workspace(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            ws_id = await client.create_workspace(name="Trial", kind="work")
            await client.update_workspace(
                ws_id, kind="personal", description="updated"
            )
            ws = await client.get_workspace(ws_id)
            assert ws["kind"] == "personal"
            assert ws["description"] == "updated"
            assert ws["name"] == "Trial"  # unchanged
            await client.close()

        run(_test())

    def test_update_invalid_kind_raises(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            with pytest.raises(ValueError, match="Invalid kind"):
                await client.update_workspace(DEFAULT_WORK_WORKSPACE_ID, kind="alien")
            await client.close()

        run(_test())

    def test_list_workspaces_filter_by_kind(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_workspace(name="Work2", kind="work")
            personal = await client.list_workspaces(kind="personal")
            assert all(w["kind"] == "personal" for w in personal)
            assert len(personal) == 1  # just the seed
            work = await client.list_workspaces(kind="work")
            assert {w["name"] for w in work} == {"Work", "Work2"}
            await client.close()

        run(_test())

    def test_workspace_kinds_allowlist(self):
        # Belt-and-suspenders: ensure the public allow-list contains exactly
        # what callers expect.
        assert set(WORKSPACE_KINDS) == {"work", "personal", "other"}


# ── Auto-derivation on create_ticket ──


class TestWorkspaceInheritance:
    def test_orphan_ticket_defaults_to_work(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket("Orphan task")
            ticket = await client.get_ticket(tid)
            assert ticket["workspace_id"] == DEFAULT_WORK_WORKSPACE_ID
            await client.close()

        run(_test())

    def test_explicit_workspace_id_honored(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            tid = await client.create_ticket(
                "Explicit personal", workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID,
            )
            ticket = await client.get_ticket(tid)
            assert ticket["workspace_id"] == DEFAULT_PERSONAL_WORKSPACE_ID
            await client.close()

        run(_test())

    def test_ticket_inherits_from_project_parent(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            # Create a Personal-workspace project
            project_id = await client.create_ticket(
                "Personal project", type="project",
                workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID,
            )

            # Create a task with that project as parent — should inherit Personal.
            task_id = await client.create_ticket(
                "Task under personal project",
                dependingTicketId=project_id,
            )
            task = await client.get_ticket(task_id)
            assert task["workspace_id"] == DEFAULT_PERSONAL_WORKSPACE_ID
            await client.close()

        run(_test())

    def test_grandchild_ticket_walks_chain(self, db_path):
        """Project → Milestone → Task — task should inherit project's workspace."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            project_id = await client.create_ticket(
                "Root project", type="project",
                workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID,
            )
            milestone_id = await client.create_ticket(
                "Milestone", type="milestone",
                dependingTicketId=project_id,
            )
            task_id = await client.create_ticket(
                "Deep task", dependingTicketId=milestone_id,
            )
            task = await client.get_ticket(task_id)
            assert task["workspace_id"] == DEFAULT_PERSONAL_WORKSPACE_ID
            await client.close()

        run(_test())

    def test_get_workspace_for_ticket_resolves_chain(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            project_id = await client.create_ticket(
                "Project", type="project",
                workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID,
            )
            milestone_id = await client.create_ticket(
                "Milestone", type="milestone", dependingTicketId=project_id,
            )
            # Manually unset workspace_id on the milestone to simulate a ticket
            # created before workspace_id was inherited (legacy data).
            db = await client._get_db()
            await db.execute(
                "UPDATE tickets SET workspace_id = 0 WHERE id = ?", (milestone_id,)
            )
            await db.commit()

            ws = await client.get_workspace_for_ticket(milestone_id)
            assert ws == DEFAULT_PERSONAL_WORKSPACE_ID
            await client.close()

        run(_test())


# ── list_tickets / search_tickets workspace filter ──


class TestListTicketsWorkspaceFilter:
    def test_list_tickets_workspace_filter(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            work_id = await client.create_ticket(
                "Work task", workspace_id=DEFAULT_WORK_WORKSPACE_ID,
            )
            personal_id = await client.create_ticket(
                "Personal task", workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID,
            )

            # Filter to Work
            r = await client.list_tickets(workspace_id=DEFAULT_WORK_WORKSPACE_ID)
            ids = [t["id"] for t in r["tickets"]]
            assert work_id in ids
            assert personal_id not in ids

            # Filter to Personal
            r = await client.list_tickets(workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID)
            ids = [t["id"] for t in r["tickets"]]
            assert personal_id in ids
            assert work_id not in ids

            # No filter: both visible (backward compat)
            r = await client.list_tickets(workspace_id=None)
            ids = [t["id"] for t in r["tickets"]]
            assert work_id in ids
            assert personal_id in ids
            await client.close()

        run(_test())

    def test_list_tickets_no_workspace_unchanged(self, db_path):
        """Existing callers (no workspace_id arg) keep seeing all tickets."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket("a", workspace_id=DEFAULT_WORK_WORKSPACE_ID)
            await client.create_ticket("b", workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID)
            r = await client.list_tickets()  # no kwarg
            assert r["total"] >= 2
            await client.close()

        run(_test())

    def test_search_tickets_workspace_filter(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            await client.create_ticket(
                "Buy birthday gift",
                description="for mom",
                workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID,
            )
            await client.create_ticket(
                "Buy office supplies",
                description="for the team",
                workspace_id=DEFAULT_WORK_WORKSPACE_ID,
            )
            r = await client.search_tickets(
                "Buy", workspace_id=DEFAULT_PERSONAL_WORKSPACE_ID,
            )
            headlines = [t["headline"] for t in r["tickets"]]
            assert any("birthday" in h for h in headlines)
            assert all("office supplies" not in h for h in headlines)
            await client.close()

        run(_test())


# ── Multi-level parent chain ──


class TestParentChain:
    def test_three_level_chain(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            project_id = await client.create_ticket(
                "Project", type="project",
            )
            milestone_id = await client.create_ticket(
                "Milestone", type="milestone", dependingTicketId=project_id,
            )
            task_id = await client.create_ticket(
                "Task", dependingTicketId=milestone_id,
            )

            chain = await client.get_parent_chain(task_id)
            assert len(chain) == 2, f"Expected 2 ancestors, got {len(chain)}"
            assert chain[0]["id"] == milestone_id
            assert chain[0]["type"] == "milestone"
            assert chain[1]["id"] == project_id
            assert chain[1]["type"] == "project"
            await client.close()

        run(_test())

    def test_get_children_returns_immediate_only(self, db_path):
        async def _test():
            client = SQLiteTaskClient(db_path)
            project_id = await client.create_ticket("Project", type="project")
            milestone_id = await client.create_ticket(
                "Milestone", type="milestone", dependingTicketId=project_id,
            )
            await client.create_ticket("Task", dependingTicketId=milestone_id)

            # Children of project = [milestone] — task is grandchild, not direct.
            children = await client.get_children(project_id)
            assert len(children) == 1
            assert children[0]["id"] == milestone_id

            children_filtered = await client.get_children(
                project_id, child_type="milestone"
            )
            assert len(children_filtered) == 1
            await client.close()

        run(_test())


# ── Backfill on existing data ──


class TestBackfillOnExistingDb:
    def test_existing_tickets_get_workspace_id(self, tmp_path):
        """Simulate an old DB without the workspaces table, then re-open with
        the new client and verify migration backfills workspace_id."""
        import sqlite3

        legacy_path = str(tmp_path / "legacy.db")
        # Create an old-style schema without workspace_id / workspaces.
        conn = sqlite3.connect(legacy_path)
        conn.execute("""
            CREATE TABLE tickets (
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
            )
        """)
        conn.execute("INSERT INTO tickets (headline) VALUES ('orphan-1')")
        conn.execute("INSERT INTO tickets (headline) VALUES ('orphan-2')")
        conn.commit()
        conn.close()

        async def _test():
            client = SQLiteTaskClient(legacy_path)
            # Trigger migration
            r = await client.list_tickets(status="all", limit=0)
            assert r["total"] == 2
            for t in r["tickets"]:
                assert t["workspace_id"] == DEFAULT_WORK_WORKSPACE_ID
            await client.close()

        run(_test())
