"""Tmux activity stream — read-only `capture-pane` for agent windows."""

import re
import subprocess

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/tmux", tags=["tmux"])

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
WINDOW_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


@router.get("/{session}/windows")
async def list_windows(session: str):
    if not WINDOW_NAME_RE.match(session):
        raise HTTPException(400, "Invalid session name")
    try:
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session, "-F", "#{window_name}\t#{window_active}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except FileNotFoundError:
        raise HTTPException(503, "tmux not installed")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "tmux call timed out")

    if result.returncode != 0:
        return {"session": session, "windows": [], "exists": False}

    windows = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            windows.append({"name": parts[0], "active": parts[1] == "1"})
    return {"session": session, "windows": windows, "exists": True}


@router.get("/{session}/{window}/capture")
async def capture_pane(
    session: str,
    window: str,
    lines: int = Query(50, le=500),
    raw: bool = Query(False, description="Return raw ANSI codes if true"),
):
    """Read-only capture-pane. NEVER writes to the pane.

    Returns the last `lines` lines of output. `raw=true` keeps ANSI escapes
    so the frontend can render colors; default strips them for plain text.
    """
    if not WINDOW_NAME_RE.match(session) or not WINDOW_NAME_RE.match(window):
        raise HTTPException(400, "Invalid session/window name")
    try:
        result = subprocess.run(
            [
                "tmux",
                "capture-pane",
                "-p",
                "-t",
                f"{session}:{window}",
                "-S",
                f"-{lines}",
            ]
            + (["-e"] if raw else []),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except FileNotFoundError:
        raise HTTPException(503, "tmux not installed")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "tmux call timed out")

    if result.returncode != 0:
        raise HTTPException(
            404,
            f"Window {session}:{window} not found or pane unavailable: {result.stderr.strip()}",
        )

    output = result.stdout
    if not raw:
        output = ANSI_RE.sub("", output)
    return {
        "session": session,
        "window": window,
        "lines_requested": lines,
        "raw": raw,
        "output": output,
    }
