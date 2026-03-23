"""Lightweight MCP proxy: stdio <-> SSE daemon bridge.

Each Claude Code agent spawns this as its MCP process.
All tool calls are forwarded to the central agents-mcp daemon via SSE.

Auto-recovery: if the SSE connection to the daemon breaks, the proxy
process exits with code 1. Claude Code detects this and restarts the
MCP server, establishing a fresh SSE connection.

Startup retry: if the daemon isn't reachable at startup, the proxy
retries a few times before giving up (exit 1 → Claude Code restarts).

Timeout protection: every tool call is wrapped with asyncio.wait_for
to prevent agents from being blocked indefinitely.
"""

import asyncio
import logging
import os
import signal
import sys
import time

import httpx
from fastmcp.server import create_proxy

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [proxy] %(message)s",
)

# Default timeout for MCP tool calls (seconds).
_DEFAULT_TIMEOUT = 120

# SSE keepalive: if no data received for this long, assume connection dead.
_KEEPALIVE_TIMEOUT = int(os.environ.get("MCP_KEEPALIVE_TIMEOUT", "90"))

# Startup retry settings
_STARTUP_RETRIES = int(os.environ.get("MCP_STARTUP_RETRIES", "3"))
_STARTUP_RETRY_DELAY = int(os.environ.get("MCP_STARTUP_RETRY_DELAY", "5"))


def _install_timeout_wrapper():
    """Monkey-patch ProxyTool.run to add timeout protection.

    This must be called BEFORE create_proxy() so that all ProxyTool
    instances created by the proxy inherit the patched method.

    On connection errors (not timeouts), exit the process so Claude Code
    restarts us with a fresh SSE connection.
    """
    from fastmcp.server.providers.proxy import ProxyTool
    from fastmcp.exceptions import ToolError

    timeout = int(os.environ.get("MCP_TOOL_TIMEOUT", str(_DEFAULT_TIMEOUT)))

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
        except (httpx.ConnectError, httpx.RemoteProtocolError,
                ConnectionError, OSError) as e:
            logger.error("SSE connection lost during tool call: %s", e)
            logger.error("Exiting proxy so Claude Code restarts the MCP server.")
            _exit_proxy(1)

    ProxyTool.run = run_with_timeout


def _check_daemon_reachable(daemon_url: str) -> bool:
    """Check if the daemon's SSE endpoint is reachable."""
    # SSE URL is like http://host:port/sse — check the base URL health
    base_url = daemon_url.rsplit("/", 1)[0]  # strip /sse
    try:
        resp = httpx.get(f"{base_url}/api/v1/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _exit_proxy(code: int = 1):
    """Exit the proxy process. Claude Code will restart it."""
    logger.info("Proxy exiting with code %d", code)
    # Force exit — don't wait for async cleanup which may hang
    os._exit(code)


def _install_keepalive_watchdog(daemon_url: str):
    """Start a background thread that monitors daemon availability.

    If the daemon becomes unreachable for KEEPALIVE_TIMEOUT seconds,
    the proxy exits so Claude Code restarts it.
    """
    import threading

    def watchdog():
        consecutive_failures = 0
        check_interval = 30  # check every 30s
        max_failures = _KEEPALIVE_TIMEOUT // check_interval

        while True:
            time.sleep(check_interval)
            if _check_daemon_reachable(daemon_url):
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.warning(
                    "Daemon unreachable (%d/%d checks)",
                    consecutive_failures, max_failures,
                )
                if consecutive_failures >= max_failures:
                    logger.error(
                        "Daemon unreachable for %ds — exiting proxy",
                        consecutive_failures * check_interval,
                    )
                    _exit_proxy(1)

    t = threading.Thread(target=watchdog, daemon=True, name="keepalive-watchdog")
    t.start()
    logger.info("Keepalive watchdog started (timeout=%ds)", _KEEPALIVE_TIMEOUT)


def main():
    daemon_url = os.environ.get("AGENTS_DAEMON_URL")
    if not daemon_url:
        print(
            "Error: AGENTS_DAEMON_URL env var must be set "
            "(e.g. http://127.0.0.1:8765/sse)",
            file=sys.stderr,
        )
        sys.exit(1)

    # Startup retry: wait for daemon to be available
    for attempt in range(1, _STARTUP_RETRIES + 1):
        if _check_daemon_reachable(daemon_url):
            logger.info("Daemon reachable at %s", daemon_url)
            break
        logger.warning(
            "Daemon not reachable (attempt %d/%d), retrying in %ds...",
            attempt, _STARTUP_RETRIES, _STARTUP_RETRY_DELAY,
        )
        if attempt == _STARTUP_RETRIES:
            logger.error("Daemon not reachable after %d attempts — exiting", _STARTUP_RETRIES)
            sys.exit(1)
        time.sleep(_STARTUP_RETRY_DELAY)

    # Install timeout + connection-error wrapper
    _install_timeout_wrapper()

    # Start keepalive watchdog
    _install_keepalive_watchdog(daemon_url)

    logger.info("Starting proxy: stdio <-> %s", daemon_url)
    proxy = create_proxy(daemon_url)
    proxy.run(transport="stdio")


if __name__ == "__main__":
    main()
