"""Send iMessages by driving Messages.app via osascript.

We avoid `Messages` Apple Events when running headless because the
service has to be running. The send tool *will* nudge the user (Messages.app
opens if not already running) — that's expected behaviour.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    ok: bool
    handle: str
    body: str
    stderr: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "handle": self.handle,
            "body": self.body,
            "stderr": self.stderr,
        }


def _escape_for_applescript(s: str) -> str:
    """Escape `"` and `\\` for inclusion in an AppleScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _build_script(handle: str, body: str, service: str = "iMessage") -> str:
    """Render the AppleScript that sends `body` to `handle` via `service`.

    `service` should be 'iMessage' or 'SMS'. SMS only works if the recipient
    is reachable via Continuity (iPhone connected to this Mac).
    """
    safe_handle = _escape_for_applescript(handle)
    safe_body = _escape_for_applescript(body)
    return (
        'tell application "Messages"\n'
        f'  set targetService to 1st service whose service type = {service}\n'
        f'  set targetBuddy to buddy "{safe_handle}" of targetService\n'
        f'  send "{safe_body}" to targetBuddy\n'
        "end tell\n"
    )


def send_imessage(
    handle: str,
    body: str,
    service: str = "iMessage",
    timeout: float = 10.0,
    runner: str | None = None,
) -> SendResult:
    """Send `body` to `handle` via Messages.app.

    `runner` lets tests inject a fake `osascript` binary path.
    """
    if not handle:
        return SendResult(ok=False, handle=handle, body=body, stderr="empty handle")
    if not body:
        return SendResult(ok=False, handle=handle, body=body, stderr="empty body")

    osascript = runner or shutil.which("osascript")
    if not osascript:
        return SendResult(
            ok=False, handle=handle, body=body,
            stderr="osascript not found (not running on macOS?)",
        )

    script = _build_script(handle, body, service=service)
    try:
        proc = subprocess.run(
            [osascript, "-"],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return SendResult(
            ok=False, handle=handle, body=body,
            stderr=f"osascript timed out after {timeout}s",
        )

    if proc.returncode != 0:
        return SendResult(
            ok=False, handle=handle, body=body,
            stderr=(proc.stderr or proc.stdout or "").strip(),
        )
    return SendResult(ok=True, handle=handle, body=body, stderr="")
