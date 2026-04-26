"""Entry point: `python -m imessage_mcp` or `imessage-mcp`.

Supports a `--check` flag for diagnosing Full Disk Access permissions
without launching the MCP loop.
"""
from __future__ import annotations

import sys

from .db import ChatDbUnavailableError, default_chat_db_path, open_readonly
from .server import main as run_server


def check_permissions() -> int:
    path = default_chat_db_path()
    print(f"chat.db path: {path}")
    if not path.exists():
        print("FAIL: chat.db not found. Open Messages.app once to create it.")
        return 2
    try:
        with open_readonly() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM message"
            ).fetchone()
            print(f"OK: chat.db opened read-only, {row['n']} message rows visible.")
            return 0
    except ChatDbUnavailableError as e:
        print(f"FAIL: {e}")
        print(
            "\nTo grant Full Disk Access:\n"
            "  System Settings → Privacy & Security → Full Disk Access\n"
            "  Add the *terminal application* hosting this MCP (Terminal.app,\n"
            "  iTerm.app, or Claude Desktop). Restart that app afterwards."
        )
        return 1


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("--check", "--check-permissions"):
        sys.exit(check_permissions())
    run_server()


if __name__ == "__main__":
    main()
