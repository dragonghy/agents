"""Entry point: ``python -m wechat_mcp`` or ``wechat-mcp``.

The ``--check`` flag verifies that the local environment can drive WeChat
without spinning up the MCP loop. Use it after granting Accessibility to
diagnose "is the permission really applied?" — TCC permissions are read
at process spawn, so this command must be re-run from a freshly-launched
terminal after granting.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .applescript import (
    WECHAT_BUNDLE_ID,
    probe_accessibility,
    probe_wechat_running,
)
from .server import main as run_server


WECHAT_APP_PATH = Path("/Applications/WeChat.app")


def check_environment() -> int:
    """Print a step-by-step diagnostic. Return 0 if everything is OK.

    Steps:
      1. WeChat.app installed?
      2. osascript on PATH?
      3. WeChat process running?
      4. Accessibility granted (System Events can read WeChat's window)?

    Each failed step prints the exact remediation.
    """
    # 1. Install check.
    if not WECHAT_APP_PATH.exists():
        print(f"FAIL: {WECHAT_APP_PATH} not found.")
        print(
            "  Install WeChat for Mac from the Mac App Store or "
            "https://mac.weixin.qq.com, then sign in once."
        )
        return 2
    print(f"OK: WeChat.app found at {WECHAT_APP_PATH}")

    # 2. osascript on PATH (we can't drive UI without it).
    osascript = shutil.which("osascript")
    if not osascript:
        print("FAIL: osascript not found on PATH.")
        print("  This MCP requires macOS; osascript ships with the OS.")
        return 2
    print(f"OK: osascript at {osascript}")

    # 3. WeChat process running?
    running = probe_wechat_running()
    if not running.ok:
        print(f"FAIL: could not query System Events: {running.stderr}")
        print(
            "  Most likely cause: this terminal hasn't been granted "
            "Automation/Accessibility permission yet. See step 4."
        )
        return 1
    if running.stdout.strip() != "yes":
        print("FAIL: WeChat is not currently running.")
        print("  Open WeChat and sign in, then re-run --check.")
        return 1
    print("OK: WeChat process is running")

    # 4. Accessibility — can we actually drive the UI?
    accessible = probe_accessibility()
    if not accessible.ok:
        print(f"FAIL: Accessibility probe failed: {accessible.stderr}")
        print()
        print("To grant Accessibility:")
        print("  1. System Settings → Privacy & Security → Accessibility")
        print("  2. Click `+` and add the *terminal application* hosting this MCP")
        print("     (Terminal.app, iTerm2.app, or Claude Desktop).")
        print("  3. Quit and relaunch that terminal app — TCC permissions are")
        print("     read at process spawn time.")
        print()
        print("If Accessibility looks granted but the probe still fails, also")
        print("check Privacy & Security → Automation, and ensure the terminal")
        print("is allowed to control 'WeChat' and 'System Events'.")
        return 1
    print(f"OK: Accessibility working — front window: {accessible.stdout}")

    print()
    print(f"All checks passed. Bundle: {WECHAT_BUNDLE_ID}")
    return 0


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("--check", "--check-permissions"):
        sys.exit(check_environment())
    run_server()


if __name__ == "__main__":
    main()
