"""Tests for staleness detection in dispatcher and leantime_client."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from agents_mcp.leantime_client import LeantimeClient
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


def test_get_stale_in_progress():
    """Test LeantimeClient.get_stale_in_progress filtering."""
    now = datetime.utcnow()
    old_date = (now - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
    recent_date = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    mock_tickets = [
        # Stale in_progress ticket (60 min old, > 30 min threshold)
        {"id": "10", "headline": "Old task", "status": 4,
         "tags": "agent:dev-alex", "date": old_date},
        # Recent in_progress ticket (5 min old, < 30 min threshold)
        {"id": "11", "headline": "New task", "status": 4,
         "tags": "agent:dev-alex", "date": recent_date},
        # Stale but status=3 (not in_progress)
        {"id": "12", "headline": "New status task", "status": 3,
         "tags": "agent:dev-alex", "date": old_date},
        # Stale in_progress but different agent
        {"id": "13", "headline": "Other agent", "status": 4,
         "tags": "agent:qa-lucy", "date": old_date},
    ]

    client = LeantimeClient("http://localhost:9090", "test-key")
    client._call = AsyncMock(return_value=mock_tickets)

    result = asyncio.run(client.get_stale_in_progress("dev-alex", 30))

    assert len(result) == 1, f"Expected 1 stale ticket, got {len(result)}"
    assert result[0]["id"] == 10
    assert result[0]["headline"] == "Old task"
    print("PASS: get_stale_in_progress filtering")


def test_get_stale_in_progress_empty():
    """Test with no stale tickets."""
    now = datetime.utcnow()
    recent_date = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    mock_tickets = [
        {"id": "10", "headline": "Recent task", "status": 4,
         "tags": "agent:dev-alex", "date": recent_date},
    ]

    client = LeantimeClient("http://localhost:9090", "test-key")
    client._call = AsyncMock(return_value=mock_tickets)

    result = asyncio.run(client.get_stale_in_progress("dev-alex", 30))
    assert len(result) == 0
    print("PASS: get_stale_in_progress empty result")


def test_get_stale_in_progress_disabled():
    """Test that threshold=0 is handled (caller should not call, but be safe)."""
    client = LeantimeClient("http://localhost:9090", "test-key")
    client._call = AsyncMock(return_value=[])
    result = asyncio.run(client.get_stale_in_progress("dev-alex", 0))
    assert len(result) == 0
    print("PASS: get_stale_in_progress with threshold=0")


def test_dispatch_cycle_stale_detection():
    """Test that dispatch_cycle uses stale message for stale tickets."""
    now = datetime.utcnow()
    old_date = (now - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

    mock_all_tickets = [
        {"id": "42", "headline": "Stuck task", "status": 4,
         "tags": "agent:dev-alex", "date": old_date},
    ]

    client = LeantimeClient("http://localhost:9090", "test-key")
    # Mock all API calls
    client._call = AsyncMock(return_value=mock_all_tickets)

    mock_store = MagicMock()
    mock_store.get_unread_count = AsyncMock(return_value=0)

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
    now = datetime.utcnow()
    recent_date = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    mock_all_tickets = [
        {"id": "42", "headline": "Fresh task", "status": 3,
         "tags": "agent:dev-alex", "date": recent_date},
    ]

    client = LeantimeClient("http://localhost:9090", "test-key")
    client._call = AsyncMock(return_value=mock_all_tickets)

    mock_store = MagicMock()
    mock_store.get_unread_count = AsyncMock(return_value=0)

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
    now = datetime.utcnow()
    old_date = (now - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

    mock_all_tickets = [
        {"id": "42", "headline": "Old task", "status": 4,
         "tags": "agent:dev-alex", "date": old_date},
    ]

    client = LeantimeClient("http://localhost:9090", "test-key")
    client._call = AsyncMock(return_value=mock_all_tickets)

    mock_store = MagicMock()
    mock_store.get_unread_count = AsyncMock(return_value=0)

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
    test_get_stale_in_progress()
    test_get_stale_in_progress_empty()
    test_get_stale_in_progress_disabled()
    test_dispatch_cycle_stale_detection()
    test_dispatch_cycle_normal_when_not_stale()
    test_dispatch_cycle_staleness_disabled()
    print("\nAll staleness tests passed!")
