"""Tests for MCP tool timeout protection.

Tests both proxy-side (ProxyTool.run wrapper) and daemon-side
(_with_timeout decorator) timeout mechanisms.
"""

import asyncio
import json
import functools
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


# ── Daemon-side _with_timeout decorator tests ──


def _make_timeout_decorator(timeouts=None, default=120):
    """Create a standalone _with_timeout decorator for testing."""
    _timeouts = timeouts or {}
    _default = default

    def _with_timeout(fn):
        timeout = _timeouts.get(fn.__name__, _default)

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
            except asyncio.TimeoutError:
                msg = (
                    f"Tool '{fn.__name__}' timed out after {timeout}s. "
                    f"The daemon may be overloaded. Please retry."
                )
                return json.dumps({"error": msg})

        return wrapper

    return _with_timeout


class TestWithTimeout:
    """Tests for the _with_timeout decorator."""

    def test_normal_call_succeeds(self):
        """Normal tool calls should complete without interference."""
        _with_timeout = _make_timeout_decorator(default=5)

        @_with_timeout
        async def fast_tool():
            return json.dumps({"result": "ok"})

        result = asyncio.run(fast_tool())
        assert json.loads(result) == {"result": "ok"}

    def test_slow_call_times_out(self):
        """A tool that takes longer than timeout should return error."""
        _with_timeout = _make_timeout_decorator(default=0.1)

        @_with_timeout
        async def slow_tool():
            await asyncio.sleep(10)
            return json.dumps({"result": "ok"})

        result = asyncio.run(slow_tool())
        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"]
        assert "slow_tool" in parsed["error"]
        assert "0.1s" in parsed["error"]

    def test_tiered_timeout_fast(self):
        """Fast tools should use the short timeout from the map."""
        _with_timeout = _make_timeout_decorator(
            timeouts={"fast_tool": 0.1, "slow_tool": 10},
            default=5,
        )

        @_with_timeout
        async def fast_tool():
            await asyncio.sleep(1)
            return json.dumps({"result": "ok"})

        result = asyncio.run(fast_tool())
        parsed = json.loads(result)
        assert "error" in parsed
        assert "0.1s" in parsed["error"]

    def test_tiered_timeout_slow(self):
        """Slow tools should use the long timeout from the map."""
        _with_timeout = _make_timeout_decorator(
            timeouts={"slow_tool": 2},
            default=0.1,
        )

        @_with_timeout
        async def slow_tool():
            await asyncio.sleep(0.05)
            return json.dumps({"result": "ok"})

        result = asyncio.run(slow_tool())
        # Should succeed because 0.05s < 2s timeout
        assert json.loads(result) == {"result": "ok"}

    def test_default_timeout_used_for_unknown_tools(self):
        """Tools not in the timeout map should use the default."""
        _with_timeout = _make_timeout_decorator(
            timeouts={"known_tool": 30},
            default=0.1,
        )

        @_with_timeout
        async def unknown_tool():
            await asyncio.sleep(1)
            return json.dumps({"result": "ok"})

        result = asyncio.run(unknown_tool())
        parsed = json.loads(result)
        assert "error" in parsed
        assert "0.1s" in parsed["error"]

    def test_preserves_function_name(self):
        """The wrapper should preserve the original function name."""
        _with_timeout = _make_timeout_decorator(default=5)

        @_with_timeout
        async def my_tool():
            return json.dumps({"result": "ok"})

        assert my_tool.__name__ == "my_tool"

    def test_passes_arguments_through(self):
        """Arguments should be forwarded correctly."""
        _with_timeout = _make_timeout_decorator(default=5)

        @_with_timeout
        async def add_tool(a: int, b: int) -> str:
            return json.dumps({"sum": a + b})

        result = asyncio.run(add_tool(3, 4))
        assert json.loads(result) == {"sum": 7}

    def test_passes_kwargs_through(self):
        """Keyword arguments should be forwarded correctly."""
        _with_timeout = _make_timeout_decorator(default=5)

        @_with_timeout
        async def tool_with_kwargs(name: str, value: int = 42) -> str:
            return json.dumps({"name": name, "value": value})

        result = asyncio.run(tool_with_kwargs("test", value=99))
        assert json.loads(result) == {"name": "test", "value": 99}

    def test_exception_propagates(self):
        """Non-timeout exceptions should still propagate normally."""
        _with_timeout = _make_timeout_decorator(default=5)

        @_with_timeout
        async def broken_tool():
            raise ValueError("something went wrong")

        with pytest.raises(ValueError, match="something went wrong"):
            asyncio.run(broken_tool())


# ── Proxy-side timeout wrapper tests ──


class TestProxyTimeout:
    """Tests for the proxy timeout wrapper logic."""

    def test_proxy_timeout_on_hang(self):
        """Simulate a hanging ProxyTool.run and verify timeout fires."""

        async def hanging_run(self, arguments, context=None):
            await asyncio.sleep(100)
            return {"result": "should never reach here"}

        timeout = 0.1

        async def run_with_timeout(self, arguments, context=None):
            try:
                return await asyncio.wait_for(
                    hanging_run(self, arguments, context),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                tool_name = getattr(self, "name", "unknown")
                return {"error": f"Tool '{tool_name}' timed out after {timeout}s"}

        # Create a mock tool
        mock_tool = MagicMock()
        mock_tool.name = "update_profile"

        result = asyncio.run(run_with_timeout(mock_tool, {"agent_id": "test"}))
        assert "error" in result
        assert "timed out" in result["error"]
        assert "update_profile" in result["error"]

    def test_proxy_normal_call_passes_through(self):
        """Normal calls through proxy should work fine."""

        async def fast_run(self, arguments, context=None):
            return {"result": "ok", "args": arguments}

        timeout = 5

        async def run_with_timeout(self, arguments, context=None):
            try:
                return await asyncio.wait_for(
                    fast_run(self, arguments, context),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return {"error": "timed out"}

        mock_tool = MagicMock()
        mock_tool.name = "get_inbox"

        result = asyncio.run(run_with_timeout(mock_tool, {"agent_id": "dev-emma"}))
        assert result == {"result": "ok", "args": {"agent_id": "dev-emma"}}


# ── Integration: verify server.py has correct timeout configuration ──


class TestTimeoutConfig:
    """Verify the timeout configuration in server.py is correct."""

    def test_all_tools_have_timeouts(self):
        """Every registered tool should have a timeout configured."""
        # Import the timeout map from server.py
        import sys
        import importlib.util
        import pathlib

        server_path = str(pathlib.Path(__file__).resolve().parent.parent / "src" / "agents_mcp" / "server.py")

        # Read _TOOL_TIMEOUTS directly from source (avoid full import)
        timeouts = {}
        with open(server_path) as f:
            content = f.read()

        # Extract tool names from @app.tool() + async def patterns
        import re
        tool_pattern = re.compile(r'@app\.tool\(\)\s+@_with_timeout\s+async def (\w+)\(')
        tool_names = tool_pattern.findall(content)
        assert len(tool_names) > 0, "No tools found in server.py"

        # Extract timeout map
        timeout_pattern = re.compile(r'"(\w+)":\s*(\d+)')
        timeout_section = content[content.index("_TOOL_TIMEOUTS"):content.index("_DEFAULT_TOOL_TIMEOUT")]
        configured_timeouts = {m.group(1): int(m.group(2)) for m in timeout_pattern.finditer(timeout_section)}

        # Every tool should be in the timeout map OR use default
        # At minimum, tools listed in the ticket must be configured
        expected_fast = {
            "list_tickets", "get_ticket", "get_comments", "add_comment",
            "get_status_labels", "get_all_subtasks", "update_profile",
            "get_profile", "list_agents", "get_inbox", "get_conversation",
            "send_message", "mark_messages_read",
        }
        for tool in expected_fast:
            assert tool in configured_timeouts, f"Fast tool '{tool}' not in timeout map"
            assert configured_timeouts[tool] == 30, f"'{tool}' should have 30s timeout, got {configured_timeouts[tool]}"

    def test_timeout_tiers_are_reasonable(self):
        """Timeout tiers should be 30s (fast), 120s (medium), 300s (slow)."""
        import pathlib
        server_path = str(pathlib.Path(__file__).resolve().parent.parent / "src" / "agents_mcp" / "server.py")
        with open(server_path) as f:
            content = f.read()

        import re
        timeout_pattern = re.compile(r'"(\w+)":\s*(\d+)')
        timeout_section = content[content.index("_TOOL_TIMEOUTS"):content.index("_DEFAULT_TOOL_TIMEOUT")]
        configured_timeouts = {m.group(1): int(m.group(2)) for m in timeout_pattern.finditer(timeout_section)}

        valid_tiers = {30, 120, 300}
        for tool, timeout in configured_timeouts.items():
            assert timeout in valid_tiers, f"Tool '{tool}' has unusual timeout {timeout}s (expected one of {valid_tiers})"
