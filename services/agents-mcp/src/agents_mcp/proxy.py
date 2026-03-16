"""Lightweight MCP proxy: stdio <-> SSE daemon bridge.

Each Claude Code agent spawns this as its MCP process.
All tool calls are forwarded to the central agents-mcp daemon via SSE.

Timeout protection: every tool call is wrapped with asyncio.wait_for
to prevent agents from being blocked indefinitely when the daemon
restarts, the SSE connection breaks, or a tool hangs.
"""

import asyncio
import logging
import os
import sys

from fastmcp.server import create_proxy

logger = logging.getLogger(__name__)

# Default timeout for MCP tool calls (seconds).
# Override with MCP_TOOL_TIMEOUT env var.
_DEFAULT_TIMEOUT = 120


def _install_timeout_wrapper():
    """Monkey-patch ProxyTool.run to add timeout protection.

    This must be called BEFORE create_proxy() so that all ProxyTool
    instances created by the proxy inherit the patched method.
    """
    from fastmcp.server.providers.proxy import ProxyTool
    from fastmcp.exceptions import ToolError

    timeout = int(os.environ.get("MCP_TOOL_TIMEOUT", str(_DEFAULT_TIMEOUT)))

    # Save original run method
    _original_run = ProxyTool.run

    async def run_with_timeout(self, arguments, context=None):
        try:
            return await asyncio.wait_for(
                _original_run(self, arguments, context),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            tool_name = getattr(self, "_backend_name", None) or self.name
            msg = (
                f"Tool '{tool_name}' timed out after {timeout}s. "
                f"The daemon may be overloaded or restarting. Please retry."
            )
            logger.warning(msg)
            raise ToolError(msg)

    ProxyTool.run = run_with_timeout


def main():
    daemon_url = os.environ.get("AGENTS_DAEMON_URL")
    if not daemon_url:
        print(
            "Error: AGENTS_DAEMON_URL env var must be set "
            "(e.g. http://127.0.0.1:8765/sse)",
            file=sys.stderr,
        )
        sys.exit(1)

    # Install timeout wrapper before creating proxy
    _install_timeout_wrapper()

    proxy = create_proxy(daemon_url)
    proxy.run(transport="stdio")


if __name__ == "__main__":
    main()
