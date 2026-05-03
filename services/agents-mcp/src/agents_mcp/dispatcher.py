"""Tmux pane introspection helpers retained from the legacy v1/v2 model.

Historically this module hosted the v1 dispatch loop (poll idle agents and
push them tasks). The v2 ephemeral-tmux-window dispatcher (`dispatcher_v2.py`
+ `session_manager.py`) and `templates/v2/` were retired in the 2026-05-03
v1 infrastructure cleanup. The functions left here are the small set of
tmux/process probes still consumed by ``server.py`` (``get_agent_tmux_status``,
surfaced through the legacy ``/api/agents/...`` endpoints).
"""

import logging
import re
import subprocess
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = 10  # seconds; prevent tmux hangs from blocking the event loop


def _tmux_window_exists(tmux_session: str, agent: str) -> bool:
    try:
        out = subprocess.check_output(
            ["tmux", "list-windows", "-t", tmux_session, "-F", "#{window_name}"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        return agent in out.strip().split("\n")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _is_idle(tmux_session: str, agent: str) -> bool:
    """Check if an agent is idle (waiting for input at the ❯ prompt).

    Claude Code v2.1+ shows the ❯ prompt at the bottom even while working
    (users can type ahead). The reliable busy/idle signal is the status bar:
      - "esc to interrupt" appears ONLY when Claude is actively processing.
      - When idle, the status bar shows other info but NOT "esc to interrupt".

    Idle = ❯ prompt present AND "esc to interrupt" NOT in status bar.
    """
    try:
        out = subprocess.check_output(
            ["tmux", "capture-pane", "-t", f"{tmux_session}:{agent}", "-p"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        lines = [l for l in out.split("\n") if l.strip()]
        tail_lines = lines[-10:]

        # The ❯ prompt must be present (Claude Code is running).
        has_prompt = any(l.startswith("❯") for l in tail_lines)
        if not has_prompt:
            return False

        # "esc to interrupt" in the status bar = Claude is actively working.
        # Old spinners (✶ Crunched, etc.) may linger on screen after completion,
        # so we ONLY use the status bar as the busy signal.
        tail_text = "\n".join(tail_lines)
        if "esc to interrupt" in tail_text:
            return False

        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _capture_pane(tmux_session: str, agent: str, lines: int = 0) -> str:
    """Capture tmux pane content. Returns empty string on failure.

    Args:
        lines: If > 0, return only the last N non-empty lines.
               If 0 (default), return full visible pane content.
    """
    try:
        out = subprocess.check_output(
            ["tmux", "capture-pane", "-t", f"{tmux_session}:{agent}", "-p"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if lines > 0:
            non_empty = [l for l in out.split("\n") if l.strip()]
            return "\n".join(non_empty[-lines:])
        return out
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _parse_reset_time(text: str) -> Optional[float]:
    """Parse rate limit reset time from text like 'resets 12am (America/Los_Angeles)'.

    Returns Unix timestamp of the reset time, or None if unparseable / stale.
    """
    match = re.search(
        r'resets?\s+(\d{1,2})\s*(am|pm)\s*\(([^)]+)\)', text, re.IGNORECASE
    )
    if not match:
        return None

    hour = int(match.group(1))
    ampm = match.group(2).lower()
    tz_name = match.group(3).strip()

    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        logger.warning(f"Unknown timezone '{tz_name}', defaulting to 1h pause")
        return time.time() + 3600

    now = datetime.now(tz)
    reset_dt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if reset_dt <= now:
        # Reset time is in the past — this is stale rate limit text, ignore it
        return None

    return reset_dt.timestamp()


def _check_rate_limited(tmux_session: str, agent: str) -> Optional[float]:
    """Check if an agent's terminal shows a rate limit message.

    Only checks the last 5 lines to avoid false positives from stale
    rate limit text still visible in terminal scrollback.

    Returns the reset timestamp if rate limited, None otherwise.
    Returns None for stale rate limit text (reset time in the past).
    """
    out = _capture_pane(tmux_session, agent, lines=5)
    if not out:
        return None

    lower = out.lower()
    if "hit your limit" not in lower and "rate limit" not in lower:
        return None

    return _parse_reset_time(out)


def _is_agent_process_alive(tmux_session: str, agent: str) -> bool:
    """Check if the Claude Code process is still running in the agent's tmux pane.

    Each agent runs in a tmux pane with zsh as the base shell.
    When Claude Code is running, it's a child process of that zsh.
    If Claude crashes or exits, zsh has no children.
    """
    try:
        pane_pid = subprocess.check_output(
            ["tmux", "list-panes", "-t", f"{tmux_session}:{agent}",
             "-F", "#{pane_pid}"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        ).strip()
        if not pane_pid:
            return False
        # Check if the pane's shell has any child processes
        children = subprocess.check_output(
            ["pgrep", "-P", pane_pid],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        ).strip()
        return bool(children)
    except subprocess.CalledProcessError:
        # pgrep returns exit code 1 if no processes found
        return False
    except subprocess.TimeoutExpired:
        return True  # Assume alive if we can't check


def get_agent_tmux_status(tmux_session: str, agent: str) -> str:
    """Get agent's tmux status: 'idle', 'busy', 'rate_limited', 'crashed', 'no_window', or 'unknown'."""
    if not _tmux_window_exists(tmux_session, agent):
        return "no_window"

    # Check if Claude process is still running
    if not _is_agent_process_alive(tmux_session, agent):
        return "crashed"

    if _is_idle(tmux_session, agent):
        # Check if idle due to rate limit — must verify reset time is in the future
        # (stale rate limit text persists on screen long after the limit expires)
        reset_ts = _check_rate_limited(tmux_session, agent)
        if reset_ts is not None:
            return "rate_limited"
        return "idle"

    # _is_idle returned False → "esc to interrupt" is present → agent is busy.
    # No need to check for specific spinner text; the status bar signal is
    # the single source of truth for busy/idle.
    return "busy"
