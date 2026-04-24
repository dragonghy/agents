"""Tests for agents_mcp.pr_monitor.

Covers:
- `extract_ticket_ids`: parsing PR title/body for `#NNN` refs.
- `ProcessedPRStore`: persistence of already-reconciled PRs.
- `process_merged_pr`: end-to-end reconciliation against a real SQLite DB.
- `pr_monitor_cycle`: top-level orchestration with a mocked `gh` fetch.
"""

from __future__ import annotations

import asyncio
import json
import os
import pytest

from agents_mcp.pr_monitor import (
    ProcessedPRStore,
    extract_ticket_ids,
    pr_monitor_cycle,
    process_merged_pr,
)
from agents_mcp.sqlite_task_client import SQLiteTaskClient


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-tasks.db")


@pytest.fixture
def state_path(tmp_path):
    return str(tmp_path / "state" / "processed.json")


# ─────────────────────────────────────────────────────────────────────────────
# extract_ticket_ids
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractTicketIds:
    def test_closes_keyword_in_body(self):
        body = "## Summary\nDoes stuff.\n\nCloses #483\n"
        assert extract_ticket_ids(
            "feat: ticket hierarchy", body, pr_number=12
        ) == [483]

    def test_fixes_ticket_in_body(self):
        title = "fix(pickleball): robust click (#485)"
        body = "Fixes ticket #485. The 12:00 PT cron..."
        # Both `#485` occurrences dedupe to one entry.
        assert extract_ticket_ids(title, body, pr_number=13) == [485]

    def test_excludes_pr_own_number(self):
        title = "feat: something #7"
        body = "Closes #100\nSee also #7 for earlier context."
        assert extract_ticket_ids(title, body, pr_number=7) == [100]

    def test_multiple_refs(self):
        body = "Closes #100\nRelated: #200, #300"
        assert extract_ticket_ids("feat", body, pr_number=1) == [100, 200, 300]

    def test_no_refs(self):
        assert extract_ticket_ids("chore: bump deps", "", pr_number=1) == []
        assert extract_ticket_ids(
            "chore: bump deps", "nothing here", pr_number=1
        ) == []

    def test_empty_body_none_safe(self):
        assert extract_ticket_ids("title #5", None, pr_number=999) == [5]

    def test_ignores_non_numbers(self):
        # `#abc` isn't a ticket ref; neither is `version-#-1`.
        body = "tag:#abc, ref #12x not closing, real #12 here"
        # `#12` should match (regex uses \b word boundary after digits).
        assert extract_ticket_ids("t", body, pr_number=999) == [12]

    def test_six_digit_cap(self):
        # 7+ digits is likely a commit-ish or date — reject.
        assert extract_ticket_ids(
            "t", "closes #1234567 and #12", pr_number=999
        ) == [12]


# ─────────────────────────────────────────────────────────────────────────────
# ProcessedPRStore
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessedPRStore:
    def test_empty_on_missing_file(self, state_path):
        store = ProcessedPRStore(state_path)
        assert not store.has("dragonghy/agents", 1)

    def test_mark_and_reload(self, state_path):
        store = ProcessedPRStore(state_path)
        store.mark("dragonghy/agents", 12, action="closed", ticket_ids=[483])
        assert store.has("dragonghy/agents", 12)

        # Reload from disk.
        store2 = ProcessedPRStore(state_path)
        assert store2.has("dragonghy/agents", 12)
        assert not store2.has("dragonghy/agents", 13)
        assert not store2.has("other/repo", 12)

    def test_seed_existing_skips_already_marked(self, state_path):
        store = ProcessedPRStore(state_path)
        prs = [{"number": 1}, {"number": 2}, {"number": 3}]
        assert store.seed_existing(prs, "r") == 3

        # Second call should not re-seed.
        assert store.seed_existing(prs, "r") == 0

    def test_tmp_and_replace_atomic(self, state_path):
        store = ProcessedPRStore(state_path)
        store.mark("r", 1, action="closed", ticket_ids=[100])
        # File should exist, tmp file should not linger.
        assert os.path.exists(state_path)
        assert not os.path.exists(state_path + ".tmp")


# ─────────────────────────────────────────────────────────────────────────────
# process_merged_pr — integrated with SQLiteTaskClient
# ─────────────────────────────────────────────────────────────────────────────


def _make_pr(number=42, ticket_id=100, title=None, body=None):
    return {
        "number": number,
        "title": title or f"feat: stuff #{ticket_id}",
        "body": body or f"Closes #{ticket_id}",
        "mergedAt": "2026-04-23T14:03:07Z",
        "url": f"https://github.com/dragonghy/agents/pull/{number}",
        "authorLogin": "dragonghy",
    }


class TestProcessMergedPR:
    def test_auto_close_in_progress_ticket(self, db_path):
        client = SQLiteTaskClient(db_path=db_path, project_id=1)

        async def scenario():
            tid = await client.create_ticket(
                "Implement feature X",
                description="...",
                status=4,
            )
            pr = _make_pr(number=42, ticket_id=tid)
            result = await process_merged_pr(client, pr, "dragonghy/agents")

            # Reload ticket.
            t = await client.get_ticket(tid)
            comments = await client.get_comments("ticket", tid, limit=0)
            return result, t, comments["comments"]

        result, ticket, comments = run(scenario())
        assert result["action"] == "closed"
        assert ticket["status"] == 0
        assert any(
            "Auto-closed by PR merge" in (c.get("text") or "")
            for c in comments
        )

    def test_skip_already_done(self, db_path):
        client = SQLiteTaskClient(db_path=db_path, project_id=1)

        async def scenario():
            tid = await client.create_ticket("Already done", status=0)
            pr = _make_pr(number=43, ticket_id=tid)
            return await process_merged_pr(client, pr, "r"), tid

        result, tid = run(scenario())
        assert result["action"] == "noop"
        assert result["details"][0]["action"] == "skip"
        assert result["details"][0]["reason"] == "already done"

    def test_skip_unknown_ticket(self, db_path):
        client = SQLiteTaskClient(db_path=db_path, project_id=1)

        async def scenario():
            # Ticket 9999 does not exist.
            pr = _make_pr(number=44, ticket_id=9999)
            return await process_merged_pr(client, pr, "r")

        result = run(scenario())
        assert result["action"] == "noop"
        assert result["ticket_ids"] == []

    def test_flag_when_open_children(self, db_path):
        client = SQLiteTaskClient(db_path=db_path, project_id=1)

        async def scenario():
            parent = await client.create_ticket(
                "Parent task", status=4, type="task"
            )
            # Open child (status=4)
            child = await client.create_ticket(
                "Child subtask",
                status=4,
                type="subtask",
                dependingTicketId=parent,
            )
            pr = _make_pr(number=45, ticket_id=parent)
            result = await process_merged_pr(client, pr, "r")
            parent_after = await client.get_ticket(parent)
            comments = await client.get_comments(
                "ticket", parent, limit=0
            )
            return result, parent_after, comments["comments"], child

        result, parent, comments, child = run(scenario())
        assert result["action"] == "flagged"
        # Parent stayed status=4 (was NOT auto-closed).
        assert parent["status"] == 4
        assert any(
            "auto-close skipped" in (c.get("text") or "").lower()
            for c in comments
        )

    def test_done_children_do_not_block(self, db_path):
        client = SQLiteTaskClient(db_path=db_path, project_id=1)

        async def scenario():
            parent = await client.create_ticket(
                "Parent", status=4, type="task"
            )
            await client.create_ticket(
                "Finished child",
                status=0,
                type="subtask",
                dependingTicketId=parent,
            )
            pr = _make_pr(number=46, ticket_id=parent)
            result = await process_merged_pr(client, pr, "r")
            parent_after = await client.get_ticket(parent)
            return result, parent_after

        result, parent = run(scenario())
        assert result["action"] == "closed"
        assert parent["status"] == 0

    def test_pr_with_no_refs(self, db_path):
        client = SQLiteTaskClient(db_path=db_path, project_id=1)

        async def scenario():
            pr = {
                "number": 50,
                "title": "chore: bump deps",
                "body": "no tickets here",
                "mergedAt": "2026-04-23T14:03:07Z",
                "url": "https://...",
                "authorLogin": "x",
            }
            return await process_merged_pr(client, pr, "r")

        result = run(scenario())
        assert result["action"] == "noop"
        assert result["ticket_ids"] == []


# ─────────────────────────────────────────────────────────────────────────────
# pr_monitor_cycle — orchestration with mocked fetch
# ─────────────────────────────────────────────────────────────────────────────


class TestPRMonitorCycle:
    def test_cycle_processes_only_new_prs(self, db_path, state_path):
        client = SQLiteTaskClient(db_path=db_path, project_id=1)
        store = ProcessedPRStore(state_path)

        async def scenario():
            t1 = await client.create_ticket("feature A", status=4)
            t2 = await client.create_ticket("feature B", status=4)

            prs = [
                _make_pr(number=10, ticket_id=t1),
                _make_pr(number=11, ticket_id=t2),
            ]

            def fake_fetch(repo, since, **kwargs):
                assert repo == "r/one"
                return prs

            # First cycle: both processed.
            r1 = await pr_monitor_cycle(
                client, store, ["r/one"], _fetch=fake_fetch
            )
            # Second cycle: already in store, no work.
            r2 = await pr_monitor_cycle(
                client, store, ["r/one"], _fetch=fake_fetch
            )
            return r1, r2, t1, t2

        r1, r2, t1, t2 = run(scenario())
        assert r1["prs_processed"] == 2
        assert r1["tickets_closed"] == 2
        assert r2["prs_processed"] == 0

        assert store.has("r/one", 10)
        assert store.has("r/one", 11)

    def test_cycle_fetch_error_per_repo(self, db_path, state_path):
        client = SQLiteTaskClient(db_path=db_path, project_id=1)
        store = ProcessedPRStore(state_path)

        def fake_fetch(repo, since, **kwargs):
            if repo == "bad/repo":
                raise RuntimeError("gh not auth'd")
            return []

        async def scenario():
            return await pr_monitor_cycle(
                client, store, ["bad/repo", "good/repo"],
                _fetch=fake_fetch,
            )

        result = run(scenario())
        assert len(result["errors"]) == 1
        assert result["errors"][0]["repo"] == "bad/repo"
        assert result["prs_seen"] == 0
