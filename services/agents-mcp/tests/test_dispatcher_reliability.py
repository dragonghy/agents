"""Tests for dispatcher reliability features:
- P0: Deferred dispatch retry in reassign_ticket
- P1: Enhanced staleness detection for status=3 tickets
- P2: Dispatch event logging
"""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents_mcp.sqlite_task_client import SQLiteTaskClient


def run(coro):
    """Run an async function in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-tasks.db")


@pytest.fixture
def store_db_path(tmp_path):
    return str(tmp_path / "test-store.db")


def _utcnow_str():
    """Get current UTC time as string, matching the format used in queries."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _old_utc_str(minutes_ago=60):
    """Get a UTC time string N minutes in the past."""
    return (datetime.utcnow() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


# ── P1: Enhanced staleness detection ──


class TestUnattendedNewTickets:
    """Test get_unattended_new_tickets in SQLiteTaskClient."""

    def test_detects_old_status3_tickets(self, db_path):
        """Old status=3 tickets should be detected as unattended."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Old unattended", 3, "agent:dev-emma", 3, _old_utc_str(60)),
            )
            await db.commit()

            unattended = await client.get_unattended_new_tickets("dev-emma", threshold_minutes=30)
            assert len(unattended) == 1
            assert unattended[0]["headline"] == "Old unattended"
            await client.close()

        run(_test())

    def test_ignores_recent_status3_tickets(self, db_path):
        """Recent status=3 tickets should not be considered unattended."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            # Insert with explicit recent UTC time (5 min ago)
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Recent new", 3, "agent:dev-emma", 3, _old_utc_str(5)),
            )
            await db.commit()

            unattended = await client.get_unattended_new_tickets("dev-emma", threshold_minutes=30)
            assert len(unattended) == 0
            await client.close()

        run(_test())

    def test_ignores_status4_tickets(self, db_path):
        """status=4 tickets should not be returned (they're in progress, not unattended)."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("In progress", 4, "agent:dev-emma", 3, _old_utc_str(60)),
            )
            await db.commit()

            unattended = await client.get_unattended_new_tickets("dev-emma", threshold_minutes=30)
            assert len(unattended) == 0
            await client.close()

        run(_test())

    def test_ignores_other_agents(self, db_path):
        """Tickets assigned to other agents should not be returned."""
        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Other agent ticket", 3, "agent:dev-alex", 3, _old_utc_str(60)),
            )
            await db.commit()

            unattended = await client.get_unattended_new_tickets("dev-emma", threshold_minutes=30)
            assert len(unattended) == 0
            await client.close()

        run(_test())


# ── P0: Deferred dispatch ──


class TestDeferredDispatch:
    """Test deferred_dispatch and schedule_deferred_dispatch."""

    def test_deferred_dispatch_dispatches_when_idle(self):
        """Deferred dispatch should dispatch when agent becomes idle."""
        from agents_mcp.dispatcher import deferred_dispatch

        call_count = 0

        def mock_is_idle(tmux_session, agent):
            nonlocal call_count
            call_count += 1
            # Busy on first check, idle on second
            return call_count >= 2

        with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
             patch("agents_mcp.dispatcher._is_idle", side_effect=mock_is_idle), \
             patch("agents_mcp.dispatcher._dispatch_agent") as mock_dispatch:

            result = run(deferred_dispatch(
                "agents", "qa-lucy", ticket_id=42,
                interval=1, max_wait=10,
            ))

            assert result == "dispatched"
            mock_dispatch.assert_called_once_with("agents", "qa-lucy")

    def test_deferred_dispatch_timeout(self):
        """Deferred dispatch should timeout if agent stays busy."""
        from agents_mcp.dispatcher import deferred_dispatch

        with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
             patch("agents_mcp.dispatcher._is_idle", return_value=False):

            result = run(deferred_dispatch(
                "agents", "qa-lucy", ticket_id=42,
                interval=1, max_wait=3,
            ))

            assert result == "timeout"

    def test_deferred_dispatch_no_window(self):
        """Deferred dispatch should give up if tmux window disappears."""
        from agents_mcp.dispatcher import deferred_dispatch

        with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=False):

            result = run(deferred_dispatch(
                "agents", "qa-lucy", ticket_id=42,
                interval=1, max_wait=10,
            ))

            assert result == "no_window"

    def test_schedule_deferred_dispatch_creates_task(self):
        """schedule_deferred_dispatch should create a background task."""
        from agents_mcp.dispatcher import (
            schedule_deferred_dispatch,
            _deferred_dispatch_tasks,
        )

        # Clean up any previous tasks
        done_agents = [a for a, t in _deferred_dispatch_tasks.items() if t.done()]
        for a in done_agents:
            del _deferred_dispatch_tasks[a]
        _deferred_dispatch_tasks.pop("test-agent", None)

        async def _test():
            with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
                 patch("agents_mcp.dispatcher._is_idle", return_value=False):
                result = schedule_deferred_dispatch("agents", "test-agent", 42)
                assert result == "scheduled"
                assert "test-agent" in _deferred_dispatch_tasks

                # Second call should be "already_pending"
                result2 = schedule_deferred_dispatch("agents", "test-agent", 43)
                assert result2 == "already_pending"

                # Cancel the task to clean up
                _deferred_dispatch_tasks["test-agent"].cancel()
                try:
                    await _deferred_dispatch_tasks["test-agent"]
                except asyncio.CancelledError:
                    pass
                del _deferred_dispatch_tasks["test-agent"]

        run(_test())


# ── P1: Dispatch cycle with unattended detection ──


class TestDispatchCycleUnattended:
    """Test dispatch_cycle with enhanced staleness detection for status=3."""

    def test_dispatch_unattended_new_tickets(self, db_path):
        """dispatch_cycle should dispatch unattended message for old status=3 tickets."""
        from agents_mcp.dispatcher import dispatch_cycle, _stale_dispatch_cooldown

        # Clear cooldown to ensure clean state
        _stale_dispatch_cooldown.pop("dev-emma", None)

        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            # Old status=3 ticket (1 hour ago in UTC)
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Old ticket", 3, "agent:dev-emma", 3, _old_utc_str(60)),
            )
            await db.commit()

            mock_store = MagicMock()
            mock_store.get_unread_count = AsyncMock(return_value=0)
            mock_store.get_all_schedules = AsyncMock(return_value=[])
            mock_store.log_dispatch_event = AsyncMock()

            with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
                 patch("agents_mcp.dispatcher._is_idle", return_value=True), \
                 patch("agents_mcp.dispatcher._check_rate_limited", return_value=None), \
                 patch("agents_mcp.dispatcher._send_tmux_message") as mock_send:

                results = await dispatch_cycle(
                    client, ["dev-emma"], "agents",
                    store=mock_store, staleness_threshold=30,
                )

                assert "dev-emma" in results
                assert results["dev-emma"].startswith("dispatched_unattended")
                # Check that the unattended message was sent
                msg = mock_send.call_args[0][2]
                assert "未处理" in msg
                assert "新 ticket" in msg

            await client.close()

        run(_test())

    def test_dispatch_normal_for_fresh_tickets(self, db_path):
        """dispatch_cycle should dispatch normally for recent tickets."""
        from agents_mcp.dispatcher import dispatch_cycle, _stale_dispatch_cooldown

        # Clear cooldown to ensure clean state
        _stale_dispatch_cooldown.pop("dev-emma", None)

        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            # Insert a recent ticket with explicit UTC time (5 min ago)
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Fresh task", 3, "agent:dev-emma", 3, _old_utc_str(5)),
            )
            await db.commit()

            mock_store = MagicMock()
            mock_store.get_unread_count = AsyncMock(return_value=0)
            mock_store.get_all_schedules = AsyncMock(return_value=[])
            mock_store.log_dispatch_event = AsyncMock()

            with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
                 patch("agents_mcp.dispatcher._is_idle", return_value=True), \
                 patch("agents_mcp.dispatcher._check_rate_limited", return_value=None), \
                 patch("agents_mcp.dispatcher._send_tmux_message") as mock_send:

                results = await dispatch_cycle(
                    client, ["dev-emma"], "agents",
                    store=mock_store, staleness_threshold=30,
                )

                assert results["dev-emma"] == "dispatched_tasks"
                msg = mock_send.call_args[0][2]
                assert "待处理" in msg

            await client.close()

        run(_test())


# ── P2: Dispatch event logging ──


class TestDispatchEventLogging:
    """Test dispatch event logging in AgentStore."""

    def test_log_and_get_events(self, store_db_path):
        """Should log and retrieve dispatch events."""
        from agents_mcp.store import AgentStore

        async def _test():
            store = AgentStore(store_db_path)
            await store.initialize()

            # Log some events
            await store.log_dispatch_event("dev-emma", "periodic", "Pending tasks found")
            await store.log_dispatch_event("dev-emma", "reassign", "Reassign #42 from dev-alex")
            await store.log_dispatch_event("qa-lucy", "deferred", "Deferred dispatch after 15s")

            # Get all events
            result = await store.get_dispatch_events()
            assert result["total"] == 3
            assert len(result["events"]) == 3

            # Get events for specific agent
            result = await store.get_dispatch_events(agent_id="dev-emma")
            assert result["total"] == 2
            assert all(e["agent_id"] == "dev-emma" for e in result["events"])

            # Check event fields (order-independent)
            trigger_types = {e["trigger_type"] for e in result["events"]}
            assert "periodic" in trigger_types
            assert "reassign" in trigger_types

            # All events should have created_at
            for event in result["events"]:
                assert "created_at" in event
                assert event["agent_id"] == "dev-emma"

            await store.close()

        run(_test())

    def test_event_pagination(self, store_db_path):
        """Should support pagination for dispatch events."""
        from agents_mcp.store import AgentStore

        async def _test():
            store = AgentStore(store_db_path)
            await store.initialize()

            for i in range(5):
                await store.log_dispatch_event("dev-emma", "periodic", f"Event {i}")

            result = await store.get_dispatch_events(agent_id="dev-emma", limit=2, offset=0)
            assert result["total"] == 5
            assert len(result["events"]) == 2

            result = await store.get_dispatch_events(agent_id="dev-emma", limit=2, offset=2)
            assert len(result["events"]) == 2

            await store.close()

        run(_test())

    def test_dispatch_cycle_logs_events(self, db_path, store_db_path):
        """dispatch_cycle should log events when dispatching."""
        from agents_mcp.dispatcher import dispatch_cycle, _stale_dispatch_cooldown
        from agents_mcp.store import AgentStore

        # Clear cooldown
        _stale_dispatch_cooldown.pop("dev-emma", None)

        async def _test():
            client = SQLiteTaskClient(db_path)
            db = await client._get_db()
            # Insert a recent ticket with explicit UTC time
            await db.execute(
                "INSERT INTO tickets (headline, status, tags, projectId, date) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Test task", 3, "agent:dev-emma", 3, _old_utc_str(5)),
            )
            await db.commit()

            store = AgentStore(store_db_path)
            await store.initialize()

            with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
                 patch("agents_mcp.dispatcher._is_idle", return_value=True), \
                 patch("agents_mcp.dispatcher._check_rate_limited", return_value=None), \
                 patch("agents_mcp.dispatcher._send_tmux_message"):

                await dispatch_cycle(
                    client, ["dev-emma"], "agents",
                    store=store, staleness_threshold=30,
                )

            events = await store.get_dispatch_events(agent_id="dev-emma")
            assert events["total"] >= 1
            assert any(e["trigger_type"] == "periodic" for e in events["events"])

            await client.close()
            await store.close()

        run(_test())


# ── Dispatch message format tests ──


class TestDispatchMessages:
    """Test new dispatch message helpers."""

    def test_unattended_message_format(self):
        """_dispatch_agent_unattended should format message correctly."""
        from agents_mcp.dispatcher import _dispatch_agent_unattended

        tickets = [
            {"id": 42, "headline": "Fix bug", "date": "2026-03-09 10:00:00"},
            {"id": 55, "headline": "Add feature", "date": "2026-03-09 09:00:00"},
        ]
        with patch("agents_mcp.dispatcher._send_tmux_message") as mock_send:
            _dispatch_agent_unattended("agents", "dev-emma", tickets)
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][2]
            assert "#42" in msg
            assert "#55" in msg
            assert "2 个" in msg
            assert "未处理" in msg
            assert "agent:dev-emma" in msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
