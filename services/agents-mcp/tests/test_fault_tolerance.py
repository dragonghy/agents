"""Tests for reassign_ticket MCP tool fault tolerance."""

import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock


# ── reassign_ticket (MCP tool) fault tolerance tests ──


def test_reassign_mcp_comment_failure_does_not_block():
    """MCP reassign_ticket should succeed even if add_comment fails."""
    from agents_mcp.server import reassign_ticket

    mock_client = MagicMock()
    mock_client.add_comment = AsyncMock(
        side_effect=RuntimeError("Comment API unavailable")
    )
    mock_client.update_ticket = AsyncMock(return_value=True)

    # Get the actual function (FastMCP may wrap it)
    fn = getattr(reassign_ticket, "fn", reassign_ticket)

    with patch("agents_mcp.server.get_client", return_value=mock_client), \
         patch("agents_mcp.server.get_config", return_value={"tmux_session": "agents"}):

        result_str = asyncio.run(
            fn(ticket_id=42, from_agent="dev-alex",
               to_agent="qa-oliver", comment="test handoff")
        )

    result = json.loads(result_str)
    assert result["status"] == "reassigned"
    assert result["ticket_id"] == 42
    assert result["to"] == "qa-oliver"
    assert result["comment_added"] is False
    assert "comment_error" in result
    # update_ticket should still have been called
    mock_client.update_ticket.assert_called_once_with(42, assignee="qa-oliver", status=3)
    print("PASS: MCP reassign_ticket proceeds after comment failure")


def test_reassign_mcp_comment_success():
    """MCP reassign_ticket should report comment_added=True on success."""
    from agents_mcp.server import reassign_ticket

    mock_client = MagicMock()
    mock_client.add_comment = AsyncMock(return_value=True)
    mock_client.update_ticket = AsyncMock(return_value=True)

    fn = getattr(reassign_ticket, "fn", reassign_ticket)

    with patch("agents_mcp.server.get_client", return_value=mock_client), \
         patch("agents_mcp.server.get_config", return_value={"tmux_session": "agents"}):

        result_str = asyncio.run(
            fn(ticket_id=42, from_agent="dev-alex",
               to_agent="qa-oliver", comment="test handoff")
        )

    result = json.loads(result_str)
    assert result["status"] == "reassigned"
    assert result["comment_added"] is True
    assert "comment_error" not in result
    print("PASS: MCP reassign_ticket reports comment success")


def test_reassign_mcp_no_comment():
    """MCP reassign_ticket without comment should not attempt add_comment."""
    from agents_mcp.server import reassign_ticket

    mock_client = MagicMock()
    mock_client.add_comment = AsyncMock()
    mock_client.update_ticket = AsyncMock(return_value=True)

    fn = getattr(reassign_ticket, "fn", reassign_ticket)

    with patch("agents_mcp.server.get_client", return_value=mock_client), \
         patch("agents_mcp.server.get_config", return_value={"tmux_session": "agents"}):

        result_str = asyncio.run(
            fn(ticket_id=42, from_agent="dev-alex",
               to_agent="qa-oliver", comment=None)
        )

    result = json.loads(result_str)
    assert result["status"] == "reassigned"
    assert result["comment_added"] is True
    mock_client.add_comment.assert_not_called()
    print("PASS: MCP reassign_ticket skips comment when None")


if __name__ == "__main__":
    test_reassign_mcp_comment_failure_does_not_block()
    test_reassign_mcp_comment_success()
    test_reassign_mcp_no_comment()
    print("\nAll fault tolerance tests passed!")
