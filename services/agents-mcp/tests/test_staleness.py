"""Tests for staleness detection in dispatcher."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from agents_mcp.dispatcher import (
    _dispatch_agent_stale,
    dispatch_cycle,
)


def test_dispatch_agent_stale_message():
    """Test that _dispatch_agent_stale formats the message correctly."""
    stale_tickets = [
        {"id": 42, "headline": "Fix bug", "date": "2026-03-09 10:00:00"},
        {"id": 55, "headline": "Add feature", "date": "2026-03-09 09:00:00"},
    ]
    with patch("agents_mcp.dispatcher._send_tmux_message") as mock_send:
        _dispatch_agent_stale("agents", "dev-alex", stale_tickets)
        mock_send.assert_called_once()
        args = mock_send.call_args
        msg = args[0][2]
        assert "#42" in msg
        assert "#55" in msg
        assert "2 个" in msg
        assert "交付" in msg
        assert "agent:dev-alex" in msg
        print("PASS: _dispatch_agent_stale message format")


def _make_mock_client(tickets):
    """Create a mock task client with given ticket data."""
    client = MagicMock()
    client.has_pending_tasks = AsyncMock(return_value=bool(tickets))
    client.get_stale_in_progress = AsyncMock(return_value=[
        {"id": int(t["id"]), "headline": t["headline"], "date": t["date"]}
        for t in tickets
        if t.get("status") == 4
    ])
    client.get_unattended_new_tickets = AsyncMock(return_value=[])
    client.check_and_unblock_deps = AsyncMock(return_value=[])
    return client


def test_dispatch_cycle_stale_detection():
    """Test that dispatch_cycle uses stale message for stale tickets."""
    now = datetime.utcnow()
    old_date = (now - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

    mock_all_tickets = [
        {"id": "42", "headline": "Stuck task", "status": 4,
         "tags": "agent:dev-alex", "date": old_date},
    ]

    client = _make_mock_client(mock_all_tickets)

    mock_store = MagicMock()
    mock_store.get_unread_count = AsyncMock(return_value=0)
    mock_store.log_dispatch_event = AsyncMock()

    # Clear any cooldown from previous tests
    from agents_mcp.dispatcher import _stale_dispatch_cooldown
    _stale_dispatch_cooldown.pop("dev-alex", None)

    with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
         patch("agents_mcp.dispatcher._is_idle", return_value=True), \
         patch("agents_mcp.dispatcher._send_tmux_message") as mock_send:

        results = asyncio.run(
            dispatch_cycle(client, ["dev-alex"], "agents",
                          store=mock_store, staleness_threshold=30)
        )

        assert "dev-alex" in results
        assert results["dev-alex"].startswith("dispatched_stale")
        # Verify the stale message was sent (not generic)
        msg = mock_send.call_args[0][2]
        assert "#42" in msg
        assert "交付" in msg
        print(f"PASS: dispatch_cycle stale detection (result: {results['dev-alex']})")


def test_dispatch_cycle_normal_when_not_stale():
    """Test that dispatch_cycle uses normal message for fresh tasks."""
    mock_all_tickets = [
        {"id": "42", "headline": "Fresh task", "status": 3,
         "tags": "agent:dev-alex", "date": "2099-01-01 00:00:00"},
    ]

    client = _make_mock_client(mock_all_tickets)
    # Override: no stale tickets
    client.get_stale_in_progress = AsyncMock(return_value=[])

    mock_store = MagicMock()
    mock_store.get_unread_count = AsyncMock(return_value=0)
    mock_store.log_dispatch_event = AsyncMock()

    # Clear any cooldown from previous tests
    from agents_mcp.dispatcher import _stale_dispatch_cooldown
    _stale_dispatch_cooldown.pop("dev-alex", None)

    with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
         patch("agents_mcp.dispatcher._is_idle", return_value=True), \
         patch("agents_mcp.dispatcher._send_tmux_message") as mock_send:

        results = asyncio.run(
            dispatch_cycle(client, ["dev-alex"], "agents",
                          store=mock_store, staleness_threshold=30)
        )

        assert results["dev-alex"] == "dispatched_tasks"
        # Verify the generic message was sent (not stale)
        msg = mock_send.call_args[0][2]
        assert "待处理" in msg
        print(f"PASS: dispatch_cycle normal dispatch for fresh tasks")


def test_dispatch_cycle_staleness_disabled():
    """Test that staleness_threshold=0 disables staleness detection."""
    mock_all_tickets = [
        {"id": "42", "headline": "Old task", "status": 4,
         "tags": "agent:dev-alex", "date": "2020-01-01 00:00:00"},
    ]

    client = _make_mock_client(mock_all_tickets)

    mock_store = MagicMock()
    mock_store.get_unread_count = AsyncMock(return_value=0)
    mock_store.log_dispatch_event = AsyncMock()

    # Clear any cooldown from previous tests
    from agents_mcp.dispatcher import _stale_dispatch_cooldown
    _stale_dispatch_cooldown.pop("dev-alex", None)

    with patch("agents_mcp.dispatcher._tmux_window_exists", return_value=True), \
         patch("agents_mcp.dispatcher._is_idle", return_value=True), \
         patch("agents_mcp.dispatcher._send_tmux_message"):

        results = asyncio.run(
            dispatch_cycle(client, ["dev-alex"], "agents",
                          store=mock_store, staleness_threshold=0)
        )

        # With staleness disabled, should dispatch normally
        assert results["dev-alex"] == "dispatched_tasks"
        print("PASS: dispatch_cycle with staleness disabled")


if __name__ == "__main__":
    test_dispatch_agent_stale_message()
    test_dispatch_cycle_stale_detection()
    test_dispatch_cycle_normal_when_not_stale()
    test_dispatch_cycle_staleness_disabled()
    print("\nAll staleness tests passed!")
