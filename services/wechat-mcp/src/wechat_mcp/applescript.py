"""Low-level helpers for invoking osascript and escaping strings into AppleScript literals.

All UI automation in this package runs through ``run_osascript``. Tests
inject a fake runner via the ``runner`` parameter so we can validate
script templates without spawning ``osascript`` (which would fail in CI).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScriptResult:
    """Outcome of running an AppleScript via ``osascript``."""

    ok: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
        }


def escape_applescript_string(value: str) -> str:
    """Escape ``"`` and ``\\`` for inclusion inside an AppleScript string literal.

    AppleScript strings only require escaping these two characters. Newlines
    pass through unchanged inside the literal — useful when sending multi-line
    message bodies.

    >>> escape_applescript_string('hi "there"')
    'hi \\\\"there\\\\"'
    >>> escape_applescript_string('a\\\\b')
    'a\\\\\\\\b'
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def run_osascript(
    script: str,
    timeout: float = 15.0,
    runner: str | None = None,
) -> ScriptResult:
    """Run ``script`` through ``osascript`` and return the result.

    Args:
        script: The AppleScript source to execute.
        timeout: Hard timeout in seconds. WeChat UI calls can be slow; the
            default leaves headroom for activate + window-render delays.
        runner: Override path to the ``osascript`` binary. Tests pass a
            fake binary; production code passes ``None`` to look it up
            via ``shutil.which``.

    The script is fed via stdin (``osascript -``) so callers don't have to
    worry about command-line escaping.
    """
    osascript = runner or shutil.which("osascript")
    if not osascript:
        return ScriptResult(
            ok=False,
            stderr="osascript not found (not running on macOS?)",
            returncode=-1,
        )

    try:
        proc = subprocess.run(
            [osascript, "-"],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ScriptResult(
            ok=False,
            stderr=f"osascript timed out after {timeout}s",
            returncode=-1,
        )

    return ScriptResult(
        ok=proc.returncode == 0,
        stdout=(proc.stdout or "").strip(),
        stderr=(proc.stderr or "").strip(),
        returncode=proc.returncode,
    )


# ---------------------------------------------------------------------------
# Diagnostic / permission probing
# ---------------------------------------------------------------------------

WECHAT_PROCESS_NAME = "WeChat"
WECHAT_BUNDLE_ID = "com.tencent.xinWeChat"


def probe_wechat_running(runner: str | None = None) -> ScriptResult:
    """Return whether the WeChat process is currently visible to System Events.

    Distinct from "is the app installed" — this asks "is it actually running
    so we can drive its UI". Used by ``--check`` to surface a clear actionable
    error when WeChat isn't launched yet.

    The script returns "yes" or "no" on stdout.
    """
    script = (
        'tell application "System Events"\n'
        f'  if (name of processes) contains "{WECHAT_PROCESS_NAME}" then\n'
        '    return "yes"\n'
        '  else\n'
        '    return "no"\n'
        '  end if\n'
        'end tell\n'
    )
    return run_osascript(script, timeout=5.0, runner=runner)


def probe_accessibility(runner: str | None = None) -> ScriptResult:
    """Probe whether the host process has Accessibility (assistive access).

    The probe asks System Events for a UI element of the WeChat process. If
    Accessibility isn't granted, the call errors with "is not allowed
    assistive access" or similar; if WeChat isn't running we get a different
    error. Callers interpret ``stderr`` to give the user a precise next step.

    Returns ScriptResult — ``ok=True`` means assistive access is working AND
    WeChat is running; otherwise inspect ``stderr``.
    """
    script = (
        f'tell application "{WECHAT_PROCESS_NAME}" to activate\n'
        'delay 0.5\n'
        'tell application "System Events"\n'
        f'  tell process "{WECHAT_PROCESS_NAME}"\n'
        '    return name of front window\n'
        '  end tell\n'
        'end tell\n'
    )
    return run_osascript(script, timeout=10.0, runner=runner)
