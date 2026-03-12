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


# ── Long comment splitting tests ──


def test_short_comment_not_split():
    """Comments under COMMENT_MAX_LEN should be posted as-is, no splitting."""
    client = _make_client()
    client._call = AsyncMock(return_value=True)
    short = "x" * 3999

    asyncio.run(client.add_comment("ticket", 42, short))

    # Should be exactly 1 call (AgentsApi), text unchanged
    assert client._call.call_count == 1
    call_args = client._call.call_args
    assert call_args[0][1]["text"] == short
    print("PASS: short comment posted as-is without splitting")


def test_long_comment_splits_into_parts():
    """Comments over COMMENT_MAX_LEN should be split into multiple parts."""
    client = _make_client()
    client._call = AsyncMock(return_value=True)

    # Create a comment slightly over 2x the limit to get 3 parts
    long_text = "line\n" * 2500  # ~12500 chars, well over 4000

    asyncio.run(client.add_comment("ticket", 42, long_text))

    # Should have multiple AgentsApi calls (one per part)
    assert client._call.call_count >= 2, f"Expected multiple calls, got {client._call.call_count}"

    # All calls should have [Part X/N] headers
    for i, call in enumerate(client._call.call_args_list):
        text = call[0][1]["text"]
        assert text.startswith(f"[Part {i+1}/"), f"Part {i+1} missing header: {text[:50]}"

    print(f"PASS: long comment split into {client._call.call_count} parts")


def test_split_comment_preserves_all_content():
    """Splitting should preserve all original content (nothing lost)."""
    # Test the static method directly
    text = "A" * 3000 + "\n" + "B" * 3000 + "\n" + "C" * 3000
    parts = LeantimeClient._split_comment(text, 4000, 40)

    # Reconstruct original from parts (strip headers)
    reconstructed = ""
    for part in parts:
        if part.startswith("[Part"):
            # Remove header line
            body = part.split("\n", 1)[1] if "\n" in part else ""
        else:
            body = part
        reconstructed += body

    # All original characters should be present
    assert "A" * 3000 in reconstructed
    assert "B" * 3000 in reconstructed
    assert "C" * 3000 in reconstructed
    print(f"PASS: split into {len(parts)} parts, all content preserved")


def test_split_comment_respects_newline_boundaries():
    """Splitting should prefer breaking at newline boundaries."""
    # Create text with clear newline breaks
    lines = [f"Line {i}: " + "x" * 80 for i in range(50)]
    text = "\n".join(lines)  # ~4550 chars
    parts = LeantimeClient._split_comment(text, 4000, 40)

    assert len(parts) == 2, f"Expected 2 parts, got {len(parts)}"
    # First part body should end at a newline boundary (no partial lines)
    body = parts[0].split("\n", 1)[1]  # strip [Part 1/2] header
    # Each line should be complete (starts with "Line ")
    for line in body.strip().split("\n"):
        assert line.startswith("Line "), f"Unexpected partial line: {line[:30]}"
    print("PASS: split respects newline boundaries")


def test_split_comment_hard_cut_no_newlines():
    """When there are no newlines, should hard cut at max length."""
    text = "x" * 10000  # No newlines
    parts = LeantimeClient._split_comment(text, 4000, 40)

    assert len(parts) >= 3, f"Expected >=3 parts, got {len(parts)}"
    # Total content length should match original (minus headers)
    total_body = sum(
        len(p.split("\n", 1)[1]) if p.startswith("[Part") else len(p)
        for p in parts
    )
    assert total_body == 10000, f"Expected 10000 chars, got {total_body}"
    print(f"PASS: hard cut into {len(parts)} parts for text without newlines")


def test_single_chunk_no_header():
    """A single chunk (text fits) should NOT get a [Part] header."""
    parts = LeantimeClient._split_comment("short text", 4000, 40)
    assert len(parts) == 1
    assert not parts[0].startswith("[Part")
    assert parts[0] == "short text"
    print("PASS: single chunk has no Part header")


def test_long_comment_with_fallback():
    """Long comment splitting should work with -32601 fallback too."""
    client = _make_client()

    calls = []
    async def mock_call(method, params=None):
        calls.append((method, params))
        if "AgentsApi" in method:
            raise RuntimeError("Leantime API Error -32601: Method not found")
        return True

    client._call = mock_call

    # Create a long comment that needs splitting
    long_text = "test line\n" * 500  # ~5000 chars

    asyncio.run(client.add_comment("ticket", 42, long_text))

    # Each part should attempt AgentsApi then fallback
    agents_calls = [c for c in calls if "AgentsApi" in c[0]]
    native_calls = [c for c in calls if "Comments.addComment" in c[0]]
    assert len(agents_calls) >= 2, f"Expected >=2 AgentsApi attempts, got {len(agents_calls)}"
    assert len(native_calls) >= 2, f"Expected >=2 native fallback calls, got {len(native_calls)}"
    assert len(agents_calls) == len(native_calls), "Each part should have AgentsApi + fallback"
    print(f"PASS: long comment with fallback — {len(native_calls)} parts each with fallback")


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
    test_short_comment_not_split()
    test_long_comment_splits_into_parts()
    test_split_comment_preserves_all_content()
    test_split_comment_respects_newline_boundaries()
    test_split_comment_hard_cut_no_newlines()
    test_single_chunk_no_header()
    test_long_comment_with_fallback()
    print("\nAll fault tolerance tests passed!")
