"""Agents Essentials MCP Server.

Unified MCP providing:
  - Task management (backed by Leantime)
  - Auto-dispatch (background loop)
  - Agent coordination (roster, lookup)
"""

import asyncio
import json
import logging
import os
import re
import sys

import yaml
from fastmcp import FastMCP

from agents_mcp.leantime_client import LeantimeClient
from agents_mcp.dispatcher import dispatch_loop
from agents_mcp.store import AgentStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastMCP("agents-mcp")

# Global state
_client: LeantimeClient = None
_config: dict = None
_store: AgentStore = None


_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_match(match):
    expr = match.group(1)
    if ":-" in expr:
        var_name, _, default = expr.partition(":-")
        return os.environ.get(var_name.strip(), default)
    return os.environ.get(expr.strip(), match.group(0))


def _resolve_env_vars(obj):
    """Recursively resolve ${VAR} and ${VAR:-default} patterns in config."""
    if isinstance(obj, str):
        return _ENV_VAR_RE.sub(_resolve_env_match, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def _load_dotenv(dotenv_path):
    """Load .env file into os.environ (does not override existing vars)."""
    if not os.path.isfile(dotenv_path):
        return
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key not in os.environ:
                os.environ[key] = value


def _load_config() -> dict:
    """Load agents.yaml from AGENTS_CONFIG_PATH env var, resolving ${VAR} references."""
    config_path = os.environ.get("AGENTS_CONFIG_PATH")
    if not config_path or not os.path.isfile(config_path):
        raise ValueError(
            "AGENTS_CONFIG_PATH env var must point to agents.yaml"
        )
    # Load .env from the same directory as agents.yaml
    root_dir = os.path.dirname(os.path.abspath(config_path))
    _load_dotenv(os.path.join(root_dir, ".env"))

    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return _resolve_env_vars(cfg)


def get_config() -> dict:
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def resolve_agents(cfg: dict) -> dict:
    """Resolve agent templates. Each agent is listed individually in config."""
    resolved = {}
    for name, info in cfg.get("agents", {}).items():
        agent = dict(info)
        template = agent.pop("template", name)
        agent["_base_name"] = template
        resolved[name] = agent
    return resolved


def get_client() -> LeantimeClient:
    global _client
    if _client is None:
        cfg = get_config()
        lt = cfg["leantime"]
        _client = LeantimeClient(
            base_url=lt["url"],
            api_key=lt["api_key"],
            project_id=lt.get("project_id", 3),
        )
    return _client


async def get_store() -> AgentStore:
    global _store
    if _store is None:
        cfg = get_config()
        config_path = os.environ.get("AGENTS_CONFIG_PATH", ".")
        root_dir = os.path.dirname(os.path.abspath(config_path))
        db_path = os.path.join(root_dir, ".agents-mcp.db")
        _store = AgentStore(db_path)
        await _store.initialize()
    return _store


# ════════════════════════════════════════
# Task Management Tools
# ════════════════════════════════════════


@app.tool()
async def list_tickets(
    project_id: int = None,
    status: str = None,
    assignee: str = None,
    tags: str = None,
    dateFrom: str = None,
    limit: int = None,
    offset: int = 0,
) -> str:
    """List tickets (summary view). Returns only active tickets by default.

    Args:
        project_id: Filter by project ID.
        status: Comma-separated status codes (e.g. '3,4'). Defaults to '1,3,4'.
                Pass 'all' to include Done/Archived.
        assignee: Filter by agent name (e.g. 'dev'). Translates to tag filter internally.
        tags: Filter by tags (e.g. 'agent:dev'). Use assignee param instead for agent filtering.
        dateFrom: Only tickets created on/after this date (YYYY-MM-DD).
        limit: Max tickets to return (for pagination).
        offset: Skip first N tickets (for pagination).
    """
    client = get_client()
    result = await client.list_tickets(
        project_id=project_id, status=status, assignee=assignee,
        tags=tags, dateFrom=dateFrom, limit=limit, offset=offset,
    )
    return json.dumps(result, indent=2)


@app.tool()
async def get_ticket(ticket_id: int) -> str:
    """Get ticket details by ID. Returns detail fields + assignee (pruned from raw API)."""
    client = get_client()
    result = await client.get_ticket(ticket_id)
    return json.dumps(result, indent=2)


@app.tool()
async def create_ticket(
    headline: str,
    project_id: int = None,
    user_id: int = 1,
    description: str = None,
    status: int = None,
    priority: str = None,
    tags: str = None,
    assignee: str = None,
) -> str:
    """Create a new ticket.

    Args:
        headline: Ticket title.
        assignee: Agent name (e.g. 'dev'). Auto-translates to agent:dev tag.
        tags: Raw tags string. If assignee is also set, agent tag is merged in.
    """
    client = get_client()
    kwargs = {}
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status
    if priority is not None:
        kwargs["priority"] = priority
    result = await client.create_ticket(
        headline=headline, project_id=project_id,
        user_id=user_id, tags=tags, assignee=assignee, **kwargs,
    )
    return json.dumps(result, indent=2)


@app.tool()
async def update_ticket(
    ticket_id: int,
    project_id: int = None,
    headline: str = None,
    description: str = None,
    status: int = None,
    priority: str = None,
    tags: str = None,
    assignee: str = None,
) -> str:
    """Update an existing ticket.

    Args:
        ticket_id: ID of the ticket to update.
        assignee: Agent name (e.g. 'dev'). Auto-translates to agent:dev tag.
        tags: Raw tags string. Overwrites existing tags.
    """
    client = get_client()
    kwargs = {}
    if headline is not None:
        kwargs["headline"] = headline
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status
    if priority is not None:
        kwargs["priority"] = priority
    if tags is not None:
        kwargs["tags"] = tags
    result = await client.update_ticket(ticket_id, project_id, assignee=assignee, **kwargs)
    return json.dumps(result, indent=2)


@app.tool()
async def get_comments(module: str, module_id: int) -> str:
    """Get comments for a ticket or other module."""
    client = get_client()
    result = await client.get_comments(module, module_id)
    return json.dumps(result, indent=2)


@app.tool()
async def add_comment(module: str, module_id: int, comment: str) -> str:
    """Add a comment to a ticket or other module."""
    client = get_client()
    result = await client.add_comment(module, module_id, comment)
    return json.dumps(result, indent=2)


@app.tool()
async def get_status_labels() -> str:
    """Get available ticket status labels."""
    client = get_client()
    result = await client.get_status_labels()
    return json.dumps(result, indent=2)


@app.tool()
async def get_all_subtasks(ticket_id: int) -> str:
    """Get all subtasks for a ticket."""
    client = get_client()
    result = await client.get_all_subtasks(ticket_id)
    return json.dumps(result, indent=2)


@app.tool()
async def upsert_subtask(
    parent_ticket: int,
    headline: str,
    description: str = None,
    status: str = None,
    priority: str = None,
    tags: str = None,
    assignedTo: str = None,
) -> str:
    """Create or update a subtask."""
    client = get_client()
    kwargs = {}
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status
    if priority is not None:
        kwargs["priority"] = priority
    if assignedTo is not None:
        kwargs["assignedTo"] = assignedTo
    result = await client.upsert_subtask(
        parent_ticket_id=parent_ticket, headline=headline,
        tags=tags, **kwargs,
    )
    return json.dumps(result, indent=2)


# ════════════════════════════════════════
# Agent Coordination Tools
# ════════════════════════════════════════


@app.tool()
async def list_agents() -> str:
    """List all configured agents with their roles and status.

    Includes dynamic profile data (identity, current_context, expertise) if available.
    """
    cfg = get_config()
    agents_expanded = resolve_agents(cfg)
    store = await get_store()
    profiles = {p["agent_id"]: p for p in await store.get_all_profiles()}

    agents = []
    for name, info in agents_expanded.items():
        entry = {
            "id": name,
            "role": info.get("role", ""),
            "description": info.get("description", ""),
            "dispatchable": info.get("dispatchable", False),
            "tag": f"agent:{name}",
        }
        profile = profiles.get(name)
        if profile:
            entry["profile"] = {
                "identity": profile.get("identity"),
                "current_context": profile.get("current_context"),
                "active_skills": profile.get("active_skills"),
                "expertise": profile.get("expertise"),
                "updated_at": profile.get("updated_at"),
            }
        agents.append(entry)
    return json.dumps(agents, indent=2)


@app.tool()
async def get_agent_status(agent: str = "all") -> str:
    """Get agent status including tmux state and workload.

    Args:
        agent: Agent name or 'all' for all agents.
    """
    from agents_mcp.dispatcher import get_agent_tmux_status

    cfg = get_config()
    tmux_session = cfg.get("tmux_session", "agents")
    agents_expanded = resolve_agents(cfg)

    if agent == "all":
        targets = list(agents_expanded.keys())
    else:
        targets = [agent]

    client = get_client()
    workloads = await client.get_agent_workload(targets)

    results = []
    for name in targets:
        info = agents_expanded.get(name, {})
        tmux_status = get_agent_tmux_status(tmux_session, name)
        wl = workloads.get(name, {})
        results.append({
            "id": name,
            "role": info.get("role", ""),
            "is_idle": tmux_status == "idle",
            "tmux_status": tmux_status,
            "workload": wl,
            "dispatchable": info.get("dispatchable", False),
        })

    return json.dumps(results, indent=2)


@app.tool()
async def suggest_assignee(role: str = None, task_context: str = None) -> str:
    """Suggest the best agent for a new task based on workload, availability, and expertise.

    Args:
        role: Filter by template name (e.g. 'qa', 'dev') or role description (e.g. 'QA 工程师').
              If omitted, considers all dispatchable agents.
        task_context: Brief description of the task to match against agent expertise.

    Returns the recommended agent name and scoring details.
    """
    from agents_mcp.dispatcher import get_agent_tmux_status

    cfg = get_config()
    tmux_session = cfg.get("tmux_session", "agents")
    agents_expanded = resolve_agents(cfg)

    # Filter candidates by role if specified
    candidates = []
    for name, info in agents_expanded.items():
        if not info.get("dispatchable", False):
            continue
        if role:
            if info.get("_base_name") != role and info.get("role", "") != role:
                continue
        candidates.append(name)

    if not candidates:
        return json.dumps({"error": f"No dispatchable agents found for role: {role}"})

    client = get_client()
    workloads = await client.get_agent_workload(candidates)

    # Load profiles for expertise matching
    store = await get_store()
    profiles = {}
    for name in candidates:
        profiles[name] = await store.get_profile(name)

    scored = []
    for name in candidates:
        wl = workloads.get(name, {})
        tmux_status = get_agent_tmux_status(tmux_session, name)

        # Base score: lower is better
        score = wl.get("in_progress", 0) * 3 + wl.get("new", 0) * 1
        if tmux_status == "busy":
            score += 2
        elif tmux_status == "no_window":
            score += 5
        elif tmux_status == "unknown":
            score += 3

        # Expertise bonus (lower score = better)
        profile = profiles.get(name)
        if profile and task_context:
            expertise_raw = profile.get("expertise", "[]")
            try:
                expertise_list = json.loads(expertise_raw) if expertise_raw else []
            except (json.JSONDecodeError, TypeError):
                expertise_list = []
            ctx_lower = task_context.lower()
            if any(e.lower() in ctx_lower for e in expertise_list):
                score -= 1  # bonus for relevant expertise

        scored.append({
            "agent": name,
            "role": agents_expanded[name].get("role", ""),
            "score": score,
            "tmux_status": tmux_status,
            "workload": wl,
        })

    scored.sort(key=lambda x: x["score"])
    result = {
        "recommended": scored[0]["agent"],
        "candidates": scored,
    }
    return json.dumps(result, indent=2)


@app.tool()
async def dispatch_agents(agent: str = "all") -> str:
    """Manually trigger dispatch for one or all agents.

    Args:
        agent: Agent name or 'all' for all dispatchable agents.
    """
    from agents_mcp.dispatcher import dispatch_cycle

    cfg = get_config()
    tmux_session = cfg.get("tmux_session", "agents")
    agents_expanded = resolve_agents(cfg)

    if agent == "all":
        targets = [
            name for name, info in agents_expanded.items()
            if info.get("dispatchable", False)
        ]
    else:
        targets = [agent]

    client = get_client()
    store = await get_store()
    results = await dispatch_cycle(client, targets, tmux_session, store=store)
    return json.dumps(results, indent=2)


# ════════════════════════════════════════
# Profile & Messaging Tools
# ════════════════════════════════════════


@app.tool()
async def update_profile(
    agent_id: str,
    identity: str = None,
    current_context: str = None,
    active_skills: str = None,
    expertise: str = None,
) -> str:
    """Update the calling agent's self-description profile.

    Agents should call this when starting a new task, finishing a task,
    or when their context changes significantly. The profile feeds into
    smart routing (suggest_assignee).

    Args:
        agent_id: Your agent ID (e.g. 'dev-alex').
        identity: Who you are and your responsibilities.
        current_context: What you're currently working on.
        active_skills: JSON array of currently loaded skill names.
        expertise: JSON array of areas you're particularly experienced with.
    """
    store = await get_store()
    result = await store.upsert_profile(
        agent_id,
        identity=identity,
        current_context=current_context,
        active_skills=active_skills,
        expertise=expertise,
    )
    return json.dumps(result, indent=2)


@app.tool()
async def get_profile(agent_id: str) -> str:
    """Get an agent's profile including their self-description, context, and expertise.

    Args:
        agent_id: Agent ID to look up (e.g. 'dev-alex'), or 'all' for all profiles.
    """
    store = await get_store()
    if agent_id == "all":
        profiles = await store.get_all_profiles()
        return json.dumps(profiles, indent=2)
    profile = await store.get_profile(agent_id)
    if not profile:
        return json.dumps({"error": f"No profile found for {agent_id}"})
    return json.dumps(profile, indent=2)


@app.tool()
async def send_message(from_agent: str, to_agent: str, message: str) -> str:
    """Send a direct message to another agent.

    Use for quick questions, status updates, or coordination that doesn't
    warrant a full Leantime ticket. The recipient will see it in their inbox
    on the next dispatch cycle.

    Args:
        from_agent: Your agent ID (sender).
        to_agent: Recipient agent ID.
        message: Message content.
    """
    store = await get_store()
    msg_id = await store.insert_message(from_agent, to_agent, message)
    return json.dumps({"id": msg_id, "status": "sent"})


@app.tool()
async def get_inbox(
    agent_id: str,
    unread_only: bool = True,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Get messages in your inbox, sorted newest first.

    Args:
        agent_id: Your agent ID.
        unread_only: If true, only return unread messages. Default true.
        limit: Max messages to return. Default 20.
        offset: Skip first N messages. Default 0.
    """
    store = await get_store()
    result = await store.get_inbox(agent_id, unread_only=unread_only, limit=limit, offset=offset)
    return json.dumps(result, indent=2)


@app.tool()
async def get_conversation(
    agent_id: str,
    with_agent: str,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Get message history between you and another agent, sorted newest first.

    Args:
        agent_id: Your agent ID.
        with_agent: The other agent's ID.
        limit: Max messages to return. Default 20.
        offset: Skip first N messages. Default 0.
    """
    store = await get_store()
    result = await store.get_conversation(agent_id, with_agent, limit=limit, offset=offset)
    return json.dumps(result, indent=2)


@app.tool()
async def mark_messages_read(agent_id: str, message_ids: str) -> str:
    """Mark messages as read.

    Args:
        agent_id: Your agent ID (must be the recipient of the messages).
        message_ids: Comma-separated message IDs to mark as read (e.g. '1,2,3').
    """
    store = await get_store()
    ids = [int(x.strip()) for x in message_ids.split(",") if x.strip()]
    count = await store.mark_read(agent_id, ids)
    return json.dumps({"marked_read": count})


@app.tool()
async def reassign_ticket(
    ticket_id: int,
    from_agent: str,
    to_agent: str,
    comment: str = None,
) -> str:
    """Reassign a ticket to another agent and optionally add a handoff comment.

    Use this instead of creating new tickets when passing work along
    the Dev -> QA -> Product pipeline. The ticket persists through its
    entire lifecycle; only the assignee changes.

    Args:
        ticket_id: The ticket to reassign.
        from_agent: Your agent ID (current assignee).
        to_agent: New assignee agent ID.
        comment: Optional handoff comment explaining context for the next agent.
    """
    client = get_client()
    if comment:
        await client.add_comment(
            "ticket", ticket_id, f"[Handoff {from_agent} → {to_agent}] {comment}"
        )
    result = await client.update_ticket(ticket_id, assignee=to_agent, status=3)

    # Auto-dispatch target agent (best-effort)
    dispatch_result = None
    try:
        from agents_mcp.dispatcher import _tmux_window_exists, _is_idle, _dispatch_agent

        cfg = get_config()
        tmux_session = cfg.get("tmux_session", "agents")
        if not _tmux_window_exists(tmux_session, to_agent):
            dispatch_result = "no_window"
        elif not _is_idle(tmux_session, to_agent):
            dispatch_result = "busy"
        else:
            _dispatch_agent(tmux_session, to_agent)
            dispatch_result = "dispatched"
        logger.info(f"Reassign #{ticket_id} → {to_agent}: auto-dispatch={dispatch_result}")
    except Exception as e:
        dispatch_result = f"error"
        logger.warning(f"Auto-dispatch failed for {to_agent} after reassign #{ticket_id}: {e}")

    return json.dumps({
        "status": "reassigned", "ticket_id": ticket_id,
        "to": to_agent, "auto_dispatch": dispatch_result,
    })


# ════════════════════════════════════════
# Background auto-dispatch
# ════════════════════════════════════════


_dispatch_task = None


async def _start_auto_dispatch_async():
    """Start auto-dispatch as a background asyncio task (called from running loop)."""
    global _dispatch_task
    cfg = get_config()
    tmux_session = cfg.get("tmux_session", "agents")
    agents_expanded = resolve_agents(cfg)
    agents_list = [
        name for name, info in agents_expanded.items()
        if info.get("dispatchable", False)
    ]

    if not agents_list:
        logger.info("No dispatchable agents, skipping auto-dispatch")
        return

    # Extract schedule configs for agents that have them
    schedules = {}
    for name, info in agents_expanded.items():
        sched = info.get("schedule")
        if sched and "interval_hours" in sched and "prompt" in sched:
            schedules[name] = sched

    # Extract daily journal config and build all-agents list
    journal_config = cfg.get("daily_journal")
    all_agents_list = list(agents_expanded.keys())

    # Extract staleness detection config
    staleness_cfg = cfg.get("staleness", {})
    staleness_threshold = staleness_cfg.get("threshold_minutes", 30)

    client = get_client()
    store = await get_store()
    _dispatch_task = asyncio.create_task(
        dispatch_loop(client, agents_list, tmux_session, store=store,
                      interval=30, schedules=schedules,
                      journal_config=journal_config,
                      all_agents=all_agents_list,
                      staleness_threshold=staleness_threshold)
    )
    logger.info(f"Auto-dispatch background task started for {agents_list}")


# ════════════════════════════════════════
# Entry point
# ════════════════════════════════════════


def _check_port(host: str, port: int) -> bool:
    """Return True if port is available, False if in use."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _find_available_port(host: str, start: int = 8765, end: int = 8800) -> int | None:
    """Find first available port in range."""
    for port in range(start, end + 1):
        if _check_port(host, port):
            return port
    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Agents MCP Server")
    parser.add_argument(
        "--daemon", action="store_true",
        help="Run as SSE daemon (persistent server) instead of stdio",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Daemon bind host")
    parser.add_argument(
        "--port", default="8765",
        help="Daemon bind port (number or 'auto' to find available port)",
    )
    parser.add_argument(
        "--no-dispatch", action="store_true",
        help="Disable auto-dispatch background loop",
    )
    args = parser.parse_args()

    # Pre-load config to fail fast
    get_config()

    # Register auto-dispatch startup via a tool call on first use,
    # or run it inline for stdio mode
    if not args.no_dispatch:
        if not args.daemon:
            # stdio mode: try to start dispatch in current loop
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(_start_auto_dispatch_async())
            except RuntimeError:
                pass  # no running loop yet, will start with server

    if args.daemon:
        import uvicorn

        # Resolve port
        if args.port == "auto":
            port = _find_available_port(args.host)
            if port is None:
                logger.error("No available port found in range 8765-8800")
                sys.exit(1)
            logger.info(f"Auto-selected port {port}")
        else:
            try:
                port = int(args.port)
            except ValueError:
                logger.error(f"Invalid port: {args.port}")
                sys.exit(1)

        # Check port availability before starting
        if not _check_port(args.host, port):
            logger.error(
                f"Port {port} is already in use. "
                f"Try a different port with --port <number>, "
                f"or use --port auto to find an available port."
            )
            sys.exit(1)

        logger.info(f"Starting SSE daemon on {args.host}:{port}")

        http_app = app.http_app(transport="sse")

        # Mount REST API for Display UI
        from agents_mcp.web.api import create_api_router
        from agents_mcp.web.events import websocket_endpoint
        from starlette.routing import WebSocketRoute

        api_router = create_api_router(get_client, get_store, get_config, resolve_agents)
        http_app.mount("/api", api_router)

        # Mount WebSocket for real-time events
        http_app.routes.insert(0, WebSocketRoute("/ws", websocket_endpoint))

        # Mount static files with SPA fallback
        static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
        web_ui_available = False
        if os.path.isdir(static_dir) and os.path.isfile(
            os.path.join(static_dir, "index.html")
        ):
            from starlette.staticfiles import StaticFiles
            from starlette.responses import FileResponse

            index_path = os.path.join(static_dir, "index.html")

            class SPAStaticFiles(StaticFiles):
                """StaticFiles with SPA fallback: serves index.html for 404 GETs."""

                async def __call__(self, scope, receive, send):
                    if scope["type"] == "http" and scope.get("method") == "GET":
                        try:
                            return await super().__call__(scope, receive, send)
                        except Exception:
                            if os.path.isfile(index_path):
                                resp = FileResponse(index_path)
                                return await resp(scope, receive, send)
                            raise
                    return await super().__call__(scope, receive, send)

            http_app.mount("/", SPAStaticFiles(directory=static_dir, html=True))
            web_ui_available = True

        # Print startup summary
        logger.info(f"MCP SSE:  http://{args.host}:{port}/sse")
        if web_ui_available:
            logger.info(f"Web UI:   http://{args.host}:{port}/")
        else:
            logger.warning(
                "Web UI:   not available "
                "(run 'cd services/agents-mcp/web && npm install && npm run build' to enable)"
            )

        config = uvicorn.Config(
            http_app, host=args.host, port=port, log_level="info"
        )
        server = uvicorn.Server(config)

        if not args.no_dispatch:
            async def _run_with_dispatch():
                try:
                    await _start_auto_dispatch_async()
                except Exception as e:
                    logger.warning(f"Auto-dispatch not started: {e}")
                await server.serve()

            asyncio.run(_run_with_dispatch())
        else:
            asyncio.run(server.serve())
    else:
        app.run()


if __name__ == "__main__":
    main()
