"""Lightweight MCP proxy: stdio ↔ SSE daemon bridge.

Each Claude Code agent spawns this as its MCP process.
All tool calls are forwarded to the central agents-mcp daemon via SSE.
"""

import os
import sys

from fastmcp.server import create_proxy


def main():
    daemon_url = os.environ.get("AGENTS_DAEMON_URL")
    if not daemon_url:
        print(
            "Error: AGENTS_DAEMON_URL env var must be set "
            "(e.g. http://127.0.0.1:8765/sse)",
            file=sys.stderr,
        )
        sys.exit(1)

    proxy = create_proxy(daemon_url)
    proxy.run(transport="stdio")


if __name__ == "__main__":
    main()
