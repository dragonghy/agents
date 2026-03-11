"""Tests for add_comment fallback and reassign_ticket fault tolerance."""

import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

from agents_mcp.leantime_client import LeantimeClient


def _make_client():
    """Create a LeantimeClient with mocked _call."""
    client = LeantimeClient("http://localhost:9090", "test-key")
    return client


# ── add_comment fallback tests ──


def test_add_comment_agents_api_success():
    """When AgentsApi works, it should be used directly."""
    client = _make_client()
    client._call = AsyncMock(return_value=True)

    result = asyncio.run(client.add_comment("ticket", 42, "test comment"))

    assert result is True
    client._call.assert_called_once_with(
        "leantime.rpc.AgentsApi.addComment",
        {"text": "test comment", "module": "ticket", "entityId": 42},
    )
    print("PASS: add_comment uses AgentsApi when available")


def test_add_comment_fallback_on_32601():
    """When AgentsApi returns -32601, should fallback to native Comments API."""
    client = _make_client()

    call_count = 0
    async def mock_call(method, params=None):
        nonlocal call_count
        call_count += 1
        if "AgentsApi" in method:
            raise RuntimeError("Leantime API Error -32601: Method not found")
        return True

    client._call = mock_call

    result = asyncio.run(client.add_comment("ticket", 42, "test comment"))

    assert result is True
    assert call_count == 2, f"Expected 2 calls (AgentsApi + fallback), got {call_count}"
    print("PASS: add_comment falls back to native Comments API on -32601")


def test_add_comment_no_fallback_on_other_errors():
    """Non-32601 errors should NOT trigger fallback."""
    client = _make_client()
    client._call = AsyncMock(
        side_effect=RuntimeError("Leantime API Error -32000: Internal error")
    )

    try:
        asyncio.run(client.add_comment("ticket", 42, "test comment"))
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "-32000" in str(e)

    # Should only have called AgentsApi, not fallback
    assert client._call.call_count == 1
    print("PASS: add_comment does not fallback on non-32601 errors")


def test_add_comment_both_fail():
    """When both AgentsApi and native API fail, should raise the fallback error."""
    client = _make_client()

    call_count = 0
    async def mock_call(method, params=None):
        nonlocal call_count
        call_count += 1
        if "AgentsApi" in method:
            raise RuntimeError("Leantime API Error -32601: Method not found")
        raise RuntimeError("Leantime API Error -32000: Native API also failed")

    client._call = mock_call

    try:
        asyncio.run(client.add_comment("ticket", 42, "test comment"))
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "-32000" in str(e)
        assert "Native API also failed" in str(e)

    assert call_count == 2
    print("PASS: add_comment raises fallback error when both APIs fail")


def test_add_comment_normalizes_module():
    """Module name 'tickets' should be normalized to 'ticket'."""
    client = _make_client()
    client._call = AsyncMock(return_value=True)

    asyncio.run(client.add_comment("tickets", 42, "test"))

    client._call.assert_called_once_with(
        "leantime.rpc.AgentsApi.addComment",
        {"text": "test", "module": "ticket", "entityId": 42},
    )
    print("PASS: add_comment normalizes 'tickets' to 'ticket'")


def test_add_comment_fallback_params():
    """Verify the native Comments API gets correct parameter format."""
    client = _make_client()

    calls = []
    async def mock_call(method, params=None):
        calls.append((method, params))
        if "AgentsApi" in method:
            raise RuntimeError("Leantime API Error -32601: Method not found")
        return True

    client._call = mock_call

    asyncio.run(client.add_comment("ticket", 42, "test comment"))

    assert len(calls) == 2
    # Second call should be native API with correct params
    method, params = calls[1]
    assert method == "leantime.rpc.Comments.addComment"
    assert params == {
        "values": {
            "text": "test comment",
            "moduleId": 42,
            "module": "ticket",
        }
    }
    print("PASS: add_comment fallback uses correct native API parameters")


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
         patch("agents_mcp.server.get_config", return_value={"tmux_session": "agents"}), \
         patch("agents_mcp.dispatcher._tmux_window_exists", return_value=False):

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
         patch("agents_mcp.server.get_config", return_value={"tmux_session": "agents"}), \
         patch("agents_mcp.dispatcher._tmux_window_exists", return_value=False):

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
         patch("agents_mcp.server.get_config", return_value={"tmux_session": "agents"}), \
         patch("agents_mcp.dispatcher._tmux_window_exists", return_value=False):

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
    test_add_comment_agents_api_success()
    test_add_comment_fallback_on_32601()
    test_add_comment_no_fallback_on_other_errors()
    test_add_comment_both_fail()
    test_add_comment_normalizes_module()
    test_add_comment_fallback_params()
    test_reassign_mcp_comment_failure_does_not_block()
    test_reassign_mcp_comment_success()
    test_reassign_mcp_no_comment()
    print("\nAll fault tolerance tests passed!")
