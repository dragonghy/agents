"""Agent endpoints — read agents.yaml for definition + agent_profiles for runtime state."""

import os
import subprocess
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException

from app import db, repo

router = APIRouter(prefix="/agents", tags=["agents"])


def _load_agents_yaml() -> dict:
    """Load agents.yaml without resolving env vars (just need the structure)."""
    path = repo.agents_yaml_path()
    if not path.exists():
        return {}
    with open(path) as f:
        # PyYAML is fine with the ${VAR} placeholders as strings
        return yaml.safe_load(f) or {}


def _expand_agents(cfg: dict) -> dict[str, dict]:
    """Return a flat {agent_id: info} mapping including v1 (`agents:`) entries."""
    out: dict[str, dict] = {}
    for name, info in (cfg.get("agents") or {}).items():
        info = info or {}
        out[name] = {
            "id": name,
            "role": info.get("role", ""),
            "description": info.get("description", ""),
            "project": info.get("project", "agents"),
            "work_stream": info.get("work_stream", ""),
            "dispatchable": bool(info.get("dispatchable", True)),
            "agent_type": info.get("agent_type", "v1"),
        }
    # v2 agent types are templates, not instances; skip for now.
    return out


def _tmux_status(session: str, agent_id: str) -> str:
    """Check whether a tmux window for this agent exists and whether it's busy.

    We only shell out to `tmux list-windows`; never to `kill-window` or `new-window`.
    Returns one of: "active", "idle", "no_window", "unavailable".
    """
    try:
        # list-windows -F '#{window_name}'
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unavailable"

    if result.returncode != 0:
        return "no_window"

    windows = result.stdout.strip().splitlines()
    if agent_id not in windows:
        return "no_window"

    # Heuristic: if the pane has produced output in the last 60s, call it "active".
    # We use `display-message` to read pane_activity (epoch). If unavailable, default to "idle".
    try:
        result = subprocess.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                f"{session}:{agent_id}",
                "#{pane_activity}",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            import time
            age = time.time() - int(result.stdout.strip())
            return "active" if age < 60 else "idle"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "idle"


@router.get("")
async def list_agents():
    cfg = _load_agents_yaml()
    tmux_session = cfg.get("tmux_session", "agents")
    agents = _expand_agents(cfg)

    # Pull profiles
    profile_rows = await db.fetch_all(
        repo.mcp_db_path(),
        "SELECT agent_id, identity, current_context, expertise, updated_at FROM agent_profiles",
    )
    profiles = {r["agent_id"]: r for r in profile_rows}

    # Workload counts from tickets table (assignee column)
    workload_rows = await db.fetch_all(
        repo.tasks_db_path(),
        "SELECT assignee, status, COUNT(*) as n "
        "FROM tickets WHERE assignee != '' GROUP BY assignee, status",
    )
    workload: dict[str, dict] = {}
    for r in workload_rows:
        bucket = workload.setdefault(
            r["assignee"], {"in_progress": 0, "new": 0, "blocked": 0, "total_active": 0}
        )
        # Only count "active" tickets (in_progress / new / blocked); skip done/archived.
        if r["status"] == 4:
            bucket["in_progress"] = r["n"]
            bucket["total_active"] += r["n"]
        elif r["status"] == 3:
            bucket["new"] = r["n"]
            bucket["total_active"] += r["n"]
        elif r["status"] == 1:
            bucket["blocked"] = r["n"]
            bucket["total_active"] += r["n"]

    out = []
    for name, info in agents.items():
        entry = dict(info)
        entry["tmux_status"] = _tmux_status(tmux_session, name)
        entry["workload"] = workload.get(
            name, {"in_progress": 0, "new": 0, "blocked": 0, "total_active": 0}
        )
        if name in profiles:
            p = profiles[name]
            entry["profile"] = {
                "identity": p["identity"],
                "current_context": p["current_context"],
                "expertise": p["expertise"],
                "updated_at": p["updated_at"],
            }
        out.append(entry)
    return out


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    cfg = _load_agents_yaml()
    tmux_session = cfg.get("tmux_session", "agents")
    agents = _expand_agents(cfg)

    info = agents.get(agent_id)
    if not info:
        raise HTTPException(404, f"Agent {agent_id} not found")

    profile = await db.fetch_one(
        repo.mcp_db_path(),
        "SELECT identity, current_context, expertise, updated_at "
        "FROM agent_profiles WHERE agent_id = ?",
        (agent_id,),
    )

    workload_rows = await db.fetch_all(
        repo.tasks_db_path(),
        "SELECT status, COUNT(*) as n FROM tickets WHERE assignee = ? GROUP BY status",
        (agent_id,),
    )
    workload = {"in_progress": 0, "new": 0, "blocked": 0, "total_active": 0}
    for r in workload_rows:
        if r["status"] == 4:
            workload["in_progress"] = r["n"]
            workload["total_active"] += r["n"]
        elif r["status"] == 3:
            workload["new"] = r["n"]
            workload["total_active"] += r["n"]
        elif r["status"] == 1:
            workload["blocked"] = r["n"]
            workload["total_active"] += r["n"]

    out = dict(info)
    out["tmux_status"] = _tmux_status(tmux_session, agent_id)
    out["workload"] = workload
    if profile:
        out["profile"] = profile
    return out


@router.get("/{agent_id}/tickets")
async def agent_tickets(agent_id: str, status: Optional[int] = None):
    where = ["assignee = ?"]
    params: list = [agent_id]
    if status is not None:
        where.append("status = ?")
        params.append(status)
    sql = (
        "SELECT id, headline, status, priority, tags, workspace_id, date "
        f"FROM tickets WHERE {' AND '.join(where)} "
        "ORDER BY status ASC, id DESC"
    )
    rows = await db.fetch_all(repo.tasks_db_path(), sql, tuple(params))
    return {"tickets": rows, "total": len(rows)}


@router.get("/{agent_id}/inbox")
async def agent_inbox(agent_id: str, limit: int = 20):
    """Recent unread P2P messages addressed to the agent."""
    rows = await db.fetch_all(
        repo.mcp_db_path(),
        "SELECT id, from_agent, to_agent, body, created_at, read_at "
        "FROM messages WHERE to_agent = ? "
        "ORDER BY id DESC LIMIT ?",
        (agent_id, limit),
    )
    return {"messages": rows, "total": len(rows)}


@router.get("/{agent_id}/sent")
async def agent_sent(agent_id: str, limit: int = 20):
    """Recent messages sent BY this agent."""
    rows = await db.fetch_all(
        repo.mcp_db_path(),
        "SELECT id, from_agent, to_agent, body, created_at, read_at "
        "FROM messages WHERE from_agent = ? "
        "ORDER BY id DESC LIMIT ?",
        (agent_id, limit),
    )
    return {"messages": rows, "total": len(rows)}
