"""V2 Dispatcher: Task-driven, project-centric dispatch.

Replaces v1's agent-polling model with task-selection:
- Scans projects by priority for actionable tasks
- Selects appropriate agent type based on task requirements
- Spawns ephemeral sessions via SessionManager
- Monitors session completion and handles transitions

Runs alongside v1 dispatcher during migration. Activated via config flag.
"""

import asyncio
import logging
import time
from typing import Optional

from agents_mcp.sqlite_task_client import SQLiteTaskClient
from agents_mcp.session_manager import SessionManager
from agents_mcp.store import AgentStore

logger = logging.getLogger(__name__)

# Task phase → agent type mapping
_PHASE_AGENT_MAP = {
    "plan": "development",
    "implement": "development",
    "test": "development",
    "deliver": "development",
    "ops": "operations",
    "infra": "operations",
    "personal": "assistant",
    "research": "assistant",
}

# Default agent type when phase is not set
_DEFAULT_AGENT_TYPE = "development"


def _select_agent_type(task: dict) -> str:
    """Determine which agent type should handle a task.

    Uses task tags, phase, and type to select the appropriate agent type.
    """
    tags = task.get("tags", "")
    phase = ""

    # Extract phase from tags (e.g., "phase:implement")
    for tag in tags.split(","):
        tag = tag.strip()
        if tag.startswith("phase:"):
            phase = tag.split(":", 1)[1]
            break

    if phase and phase in _PHASE_AGENT_MAP:
        return _PHASE_AGENT_MAP[phase]

    # Infer from assignee pattern (backward compat)
    assignee = task.get("assignee", "")
    if assignee in ("ops", "admin", "inspector"):
        return "operations"
    if assignee == "assistant":
        return "assistant"

    # Check tags for hints
    if "ops" in tags or "infra" in tags:
        return "operations"
    if "personal" in tags or "assistant" in tags:
        return "assistant"

    return _DEFAULT_AGENT_TYPE


def _extract_project(task: dict) -> Optional[str]:
    """Extract project name from task tags."""
    tags = task.get("tags", "")
    for tag in tags.split(","):
        tag = tag.strip()
        if tag.startswith("project:"):
            return tag.split(":", 1)[1]
    return None


async def dispatch_cycle_v2(
    client: SQLiteTaskClient,
    session_mgr: SessionManager,
    store: AgentStore,
    project_config: dict = None,
) -> dict:
    """Run one v2 dispatch cycle.

    1. Check for actionable tasks (status=3, no future start_time)
    2. For each task, check if a session is already working on it
    3. If no session and capacity available, spawn one
    4. Return status summary

    Args:
        client: Task database client
        session_mgr: Session pool manager
        store: Agent store (for notifications, messages)
        project_config: Project definitions with priorities and paths
    """
    results = {
        "cycle_time": time.time(),
        "sessions_active": session_mgr.active_count,
        "sessions_max": session_mgr.max_sessions,
        "tasks_found": 0,
        "tasks_dispatched": 0,
        "tasks_skipped": [],
    }

    # Get all actionable tasks (status=3 New, ordered by priority)
    all_tasks = await client.list_tickets(status="3", limit=0)
    tasks = all_tasks.get("tickets", [])
    results["tasks_found"] = len(tasks)

    if not tasks:
        return results

    # Filter out tasks with future start_time
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    actionable = []
    for task in tasks:
        start_time = task.get("start_time", "")
        if start_time and start_time > now_str:
            continue
        # Skip tasks assigned to "human" — those require Human action
        if task.get("assignee") == "human":
            continue
        actionable.append(task)

    # Check which tasks already have active sessions
    active_task_ids = {
        s.task_id for s in session_mgr._sessions.values()
        if s.status in ("starting", "active")
    }

    for task in actionable:
        tid = task["id"]

        # Skip if already being worked on
        if tid in active_task_ids:
            results["tasks_skipped"].append({"id": tid, "reason": "session_active"})
            continue

        # Check capacity
        if not session_mgr.has_capacity:
            results["tasks_skipped"].append({"id": tid, "reason": "no_capacity"})
            continue

        # Select agent type and project
        agent_type = _select_agent_type(task)
        project = _extract_project(task)

        # Resolve project directories
        project_dirs = []
        if project_config and project in project_config:
            proj_cfg = project_config[project]
            if "path" in proj_cfg:
                project_dirs.append(proj_cfg["path"])
            if "add_dirs" in proj_cfg:
                project_dirs.extend(proj_cfg["add_dirs"])

        # Spawn session
        headline = task.get("headline", f"Task #{tid}")
        session = await session_mgr.spawn_session(
            agent_type=agent_type,
            task_id=tid,
            task_description=headline,
            project=project,
            project_dirs=project_dirs if project_dirs else None,
        )

        if session:
            # Mark task as in-progress
            await client.update_ticket(tid, status=4)
            results["tasks_dispatched"] += 1
            logger.info(f"Dispatched task #{tid} → {agent_type} session {session.session_id}")
        else:
            results["tasks_skipped"].append({"id": tid, "reason": "spawn_failed"})

    return results


async def dispatch_loop_v2(
    client: SQLiteTaskClient,
    session_mgr: SessionManager,
    store: AgentStore,
    interval: int = 30,
    project_config: dict = None,
):
    """Run v2 dispatch cycles continuously.

    Also starts the session monitor loop for idle detection.
    """
    logger.info(
        f"V2 dispatcher started: interval={interval}s, "
        f"max_sessions={session_mgr.max_sessions}"
    )

    # Start session monitor in background
    monitor_task = asyncio.create_task(session_mgr.monitor_loop())

    while True:
        try:
            results = await dispatch_cycle_v2(
                client, session_mgr, store,
                project_config=project_config,
            )

            # Log summary
            dispatched = results["tasks_dispatched"]
            found = results["tasks_found"]
            active = results["sessions_active"]
            if dispatched or found:
                logger.info(
                    f"V2 dispatch: {dispatched} dispatched, {found} found, "
                    f"{active}/{session_mgr.max_sessions} sessions active"
                )

            # Broadcast via WebSocket
            try:
                from agents_mcp.web.events import event_bus
                if event_bus.client_count > 0:
                    await event_bus.broadcast("v2_dispatch_completed", results)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"V2 dispatch error: {e}")

        await asyncio.sleep(interval)
