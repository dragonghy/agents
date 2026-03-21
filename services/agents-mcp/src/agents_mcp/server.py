"""Agents Essentials MCP Server.

Unified MCP providing:
  - Task management (backed by SQLite)
  - Auto-dispatch (background loop)
  - Agent coordination (roster, lookup)
"""

import asyncio
import functools
import json
import logging
import os
import re
import sys

import yaml
from fastmcp import FastMCP

from agents_mcp.sqlite_task_client import SQLiteTaskClient
from agents_mcp.dispatcher import dispatch_loop
from agents_mcp.store import AgentStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastMCP("agents-mcp")

# Global state
_client: SQLiteTaskClient = None
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


def _find_project_root() -> str:
    """Auto-detect the project root by looking for known markers.

    Checks the package's own location first (server.py is at
    services/agents-mcp/src/agents_mcp/server.py, so root is 4 levels up),
    then walks up from CWD.
    """
    # Try from this file's location: root is 4 levels up
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.normpath(os.path.join(pkg_dir, "..", "..", "..", ".."))
    if os.path.isfile(os.path.join(candidate, "setup-agents.py")):
        return candidate

    # Walk up from CWD
    d = os.path.abspath(".")
    for _ in range(10):
        if os.path.isfile(os.path.join(d, "setup-agents.py")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent

    # Fallback to CWD
    return os.path.abspath(".")


def _load_config() -> dict:
    """Load agents.yaml, resolving ${VAR} references.

    Config path resolution order:
    1. AGENTS_CONFIG_PATH env var (explicit)
    2. Auto-detect project root and look for agents.yaml there

    If the config file does not exist yet (first-time setup / onboarding),
    returns a minimal empty config so the daemon can start and serve the
    onboarding wizard which will generate the real agents.yaml.
    """
    config_path = os.environ.get("AGENTS_CONFIG_PATH")
    if not config_path:
        # Auto-detect: find project root and set AGENTS_CONFIG_PATH
        root = _find_project_root()
        config_path = os.path.join(root, "agents.yaml")
        os.environ["AGENTS_CONFIG_PATH"] = config_path

    if not os.path.isfile(config_path):
        # No config yet — return minimal config for onboarding mode
        return {"agents": {}}

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


def reload_config() -> dict:
    """Force reload of agents.yaml configuration."""
    global _config
    _config = None
    return get_config()


def resolve_agents(cfg: dict) -> dict:
    """Resolve agent templates. Each agent is listed individually in config."""
    resolved = {}
    for name, info in cfg.get("agents", {}).items():
        agent = dict(info)
        template = agent.pop("template", name)
        agent["_base_name"] = template
        resolved[name] = agent
    return resolved


def get_client() -> SQLiteTaskClient:
    global _client
    if _client is None:
        cfg = get_config()
        config_path = os.environ.get("AGENTS_CONFIG_PATH", ".")
        root_dir = os.path.dirname(os.path.abspath(config_path))
        db_path = os.path.join(root_dir, ".agents-tasks.db")
        project_id = cfg.get("project_id", 3)
        _client = SQLiteTaskClient(db_path=db_path, project_id=project_id)
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
# Tool timeout protection
# ════════════════════════════════════════

# Tiered timeouts by tool category (seconds)
_TOOL_TIMEOUTS = {
    # Fast tools: simple DB reads/writes (30s)
    "list_tickets": 30,
    "search_tickets": 30,
    "get_ticket": 30,
    "get_comments": 30,
    "add_comment": 30,
    "get_status_labels": 30,
    "get_all_subtasks": 30,
    "update_profile": 30,
    "get_profile": 30,
    "list_agents": 30,
    "get_inbox": 30,
    "get_conversation": 30,
    "send_message": 30,
    "mark_messages_read": 30,
    # Medium tools: involve more logic or external calls (120s)
    "create_ticket": 120,
    "update_ticket": 120,
    "reassign_ticket": 120,
    "upsert_subtask": 120,
    "update_depends_on": 30,
    "suggest_assignee": 120,
    "get_agent_status": 120,
    "get_schedules": 120,
    "schedule_task": 120,
    "remove_schedule": 120,
    # Slow tools: involve subprocess, tmux, or heavy operations (300s)
    "dispatch_agents": 300,
    "request_restart": 300,
}
_DEFAULT_TOOL_TIMEOUT = 120


def _with_timeout(fn):
    """Decorator that wraps an async tool handler with asyncio.wait_for timeout.

    On timeout, returns a JSON error instead of hanging forever.
    """
    timeout = _TOOL_TIMEOUTS.get(fn.__name__, _DEFAULT_TOOL_TIMEOUT)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
        except asyncio.TimeoutError:
            msg = (
                f"Tool '{fn.__name__}' timed out after {timeout}s. "
                f"The daemon may be overloaded. Please retry."
            )
            logger.warning(msg)
            return json.dumps({"error": msg})

    return wrapper


# ════════════════════════════════════════
# Task Management Tools
# ════════════════════════════════════════


@app.tool()
@_with_timeout
async def list_tickets(
    project_id: int = None,
    status: str = None,
    assignee: str = None,
    tags: str = None,
    dateFrom: str = None,
    limit: int = 20,
    offset: int = 0,
    include_future: bool = False,
) -> str:
    """List tickets (summary view). Returns only active tickets by default.

    Paginated: returns at most `limit` tickets (default 20). Use offset to
    page through results. The response includes `total` for the full count.

    By default, tickets with start_time in the future are excluded.

    Args:
        project_id: Filter by project ID.
        status: Comma-separated status codes (e.g. '3,4'). Defaults to '1,3,4'.
                Pass 'all' to include Done/Archived.
        assignee: Filter by agent name (e.g. 'dev'). Filters on native assignee column.
        tags: Filter by tags (e.g. 'agent:dev'). Use assignee param instead for agent filtering.
        dateFrom: Only tickets created on/after this date (YYYY-MM-DD).
        limit: Max tickets per page (default 20, 0 for unlimited).
        offset: Skip first N tickets (for pagination).
        include_future: If True, include tickets with start_time in the future.
    """
    client = get_client()
    result = await client.list_tickets(
        project_id=project_id, status=status, assignee=assignee,
        tags=tags, dateFrom=dateFrom, limit=limit, offset=offset,
        include_future=include_future,
    )
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def search_tickets(
    query: str,
    limit: int = 10,
    time_range: str = None,
    status: str = None,
    assignee: str = None,
) -> str:
    """Full-text search for tickets by keyword. Matches against headline and description.

    Returns results ranked by relevance (best matches first). Use this instead of
    list_tickets when looking for specific topics or past tickets.

    Args:
        query: Search keywords (required). Supports FTS5 syntax (e.g. "agent hub",
               "scroll OR drag", "desktop NOT browser").
        limit: Max results to return (default 10, max 50).
        time_range: Only search recent tickets, e.g. "7d" for last 7 days, "30d" for last month.
        status: Filter by status codes (e.g. "3,4" for active only).
        assignee: Filter by agent name (e.g. "dev-alex").
    """
    client = get_client()
    result = await client.search_tickets(
        query=query, limit=limit, time_range=time_range,
        status=status, assignee=assignee,
    )
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def get_ticket(ticket_id: int) -> str:
    """Get ticket details by ID. Returns detail fields + assignee (pruned from raw API)."""
    client = get_client()
    result = await client.get_ticket(ticket_id)
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def create_ticket(
    headline: str,
    project_id: int = None,
    user_id: int = 1,
    description: str = None,
    status: int = None,
    priority: str = None,
    tags: str = None,
    assignee: str = None,
    start_time: str = None,
) -> str:
    """Create a new ticket.

    Args:
        headline: Ticket title.
        assignee: Agent name (e.g. 'dev'). Auto-translates to agent:dev tag.
        tags: Raw tags string. If assignee is also set, agent tag is merged in.
        start_time: Optional future start time (YYYY-MM-DD HH:MM:SS). If set, the ticket
                    won't be dispatched to agents until this time is reached.
    """
    client = get_client()
    kwargs = {}
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status
    if priority is not None:
        kwargs["priority"] = priority
    if start_time is not None:
        kwargs["start_time"] = start_time
    result = await client.create_ticket(
        headline=headline, project_id=project_id,
        user_id=user_id, tags=tags, assignee=assignee, **kwargs,
    )
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
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
@_with_timeout
async def get_comments(
    module: str, module_id: int, limit: int = 10, offset: int = 0
) -> str:
    """Get comments for a ticket or other module, with pagination.

    Args:
        module: Module type (e.g. 'ticket').
        module_id: ID of the module entity.
        limit: Max comments to return. Default 10. Use 0 for all.
        offset: Skip first N comments. Default 0.
    """
    client = get_client()
    result = await client.get_comments(module, module_id, limit=limit, offset=offset)
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def add_comment(module: str, module_id: int, comment: str, author: str = None) -> str:
    """Add a comment to a ticket or other module.

    Args:
        module: Module type (e.g. 'ticket').
        module_id: ID of the module entity.
        comment: Comment text.
        author: Agent ID of the comment author (e.g. 'dev-alex'). Optional.
    """
    client = get_client()
    result = await client.add_comment(module, module_id, comment, author=author)
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def get_status_labels() -> str:
    """Get available ticket status labels."""
    client = get_client()
    result = await client.get_status_labels()
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def get_all_subtasks(ticket_id: int) -> str:
    """Get all subtasks for a ticket."""
    client = get_client()
    result = await client.get_all_subtasks(ticket_id)
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def upsert_subtask(
    parent_ticket: int,
    headline: str,
    description: str = None,
    status: str = None,
    priority: str = None,
    tags: str = None,
    assignedTo: str = None,
) -> str:
    """Create or update a subtask.

    Args:
        parent_ticket: Parent ticket ID.
        headline: Subtask title.
        description: Subtask description.
        status: Subtask status.
        priority: Subtask priority.
        tags: Raw tags string.
        assignedTo: Agent name to assign (e.g. 'dev-alex'). Writes native assignee column.
    """
    client = get_client()
    kwargs = {}
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status
    if priority is not None:
        kwargs["priority"] = priority
    result = await client.upsert_subtask(
        parent_ticket_id=parent_ticket, headline=headline,
        tags=tags, assignee=assignedTo, **kwargs,
    )
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def update_depends_on(ticket_id: int, depends_on: str) -> str:
    """Update the dependency list for a ticket.

    Sets the depends_on field to a comma-separated list of ticket IDs that
    this ticket depends on. The auto-dispatch system uses this to auto-lock
    tickets with unresolved dependencies (status→1) and auto-unlock when
    all dependencies are done (status→3).

    Args:
        ticket_id: The ticket to update.
        depends_on: Comma-separated ticket IDs (e.g. '10,20,30').
    """
    client = get_client()
    result = await client.update_depends_on(ticket_id, depends_on)
    return json.dumps(result, indent=2)


# ════════════════════════════════════════
# Agent Coordination Tools
# ════════════════════════════════════════


@app.tool()
@_with_timeout
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
@_with_timeout
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
@_with_timeout
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

        # Expertise & context matching (lower score = better)
        profile = profiles.get(name)
        if profile and task_context:
            ctx_words = set(re.findall(r'[a-zA-Z0-9]+', task_context.lower()))

            # 1) Expertise keyword matching (word-level overlap)
            expertise_raw = profile.get("expertise", "[]")
            try:
                expertise_list = json.loads(expertise_raw) if expertise_raw else []
            except (json.JSONDecodeError, TypeError):
                expertise_list = []
            match_count = 0
            for e in expertise_list:
                e_words = set(re.findall(r'[a-zA-Z0-9]+', e.lower()))
                overlap = e_words & ctx_words
                # Single-word expertise: 1 match suffices (e.g. "Remix")
                # Multi-word expertise: require >=2 overlapping words to avoid
                # false positives on generic terms like "integration", "development"
                min_overlap = 1 if len(e_words) <= 1 else 2
                if len(overlap) >= min_overlap:
                    match_count += 1
            # Each matching expertise area gives -2 (significant vs +3 per in_progress)
            score -= match_count * 2

            # 2) Current context bonus: recent work on similar topics
            current_ctx = profile.get("current_context") or ""
            if current_ctx:
                ctx_current_words = set(re.findall(r'[a-zA-Z0-9]+', current_ctx.lower()))
                overlap = ctx_words & ctx_current_words
                if len(overlap) >= 2:  # at least 2 words in common
                    score -= 1  # bonus for recent relevant work

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
@_with_timeout
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
@_with_timeout
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
@_with_timeout
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
@_with_timeout
async def send_message(from_agent: str, to_agent: str, message: str) -> str:
    """Send a direct message to another agent.

    Use for quick questions, status updates, or coordination that doesn't
    warrant a full ticket. The recipient will see it in their inbox
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
@_with_timeout
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
@_with_timeout
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
@_with_timeout
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
@_with_timeout
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

    # Add handoff comment (best-effort: don't block reassignment if comment fails)
    comment_added = True
    comment_error = None
    if comment:
        try:
            await client.add_comment(
                "ticket", ticket_id,
                f"[Handoff {from_agent} → {to_agent}] {comment}",
                author=from_agent,
            )
        except Exception as e:
            comment_added = False
            comment_error = str(e)
            logger.warning(
                f"Failed to add handoff comment on #{ticket_id}: {e}. "
                "Proceeding with reassignment."
            )

    result = await client.update_ticket(ticket_id, assignee=to_agent, status=3)

    # Auto-dispatch target agent (best-effort)
    # If agent is idle → dispatch immediately
    # If agent is busy → schedule deferred dispatch (retry until idle or timeout)
    dispatch_result = None
    deferred_result = None
    try:
        from agents_mcp.dispatcher import (
            _tmux_window_exists, _is_idle, _dispatch_agent,
            schedule_deferred_dispatch,
        )

        cfg = get_config()
        tmux_session = cfg.get("tmux_session", "agents")
        store = await get_store()

        if not _tmux_window_exists(tmux_session, to_agent):
            dispatch_result = "no_window"
        elif not _is_idle(tmux_session, to_agent):
            dispatch_result = "busy"
            # Schedule deferred dispatch: retry until agent becomes idle
            deferred_result = schedule_deferred_dispatch(
                tmux_session, to_agent, ticket_id, store=store,
            )
        else:
            _dispatch_agent(tmux_session, to_agent)
            dispatch_result = "dispatched"
            # Log dispatch event
            try:
                await store.log_dispatch_event(
                    to_agent, "reassign",
                    f"Immediate dispatch after reassign #{ticket_id} from {from_agent}",
                )
            except Exception:
                pass  # Logging is best-effort
        logger.info(
            f"Reassign #{ticket_id} → {to_agent}: "
            f"auto-dispatch={dispatch_result}, deferred={deferred_result}"
        )
    except Exception as e:
        dispatch_result = f"error"
        logger.warning(f"Auto-dispatch failed for {to_agent} after reassign #{ticket_id}: {e}")

    response = {
        "status": "reassigned", "ticket_id": ticket_id,
        "to": to_agent, "auto_dispatch": dispatch_result,
        "comment_added": comment_added,
    }
    if deferred_result:
        response["deferred_dispatch"] = deferred_result
    if comment_error:
        response["comment_error"] = comment_error
    return json.dumps(response)


# ════════════════════════════════════════
# Agent Lifecycle Tools
# ════════════════════════════════════════


@app.tool()
@_with_timeout
async def request_restart(agent_id: str, target_agent_id: str = "", reason: str = "") -> str:
    """Request a restart of an agent session. Use when MCP tools are broken,
    session is corrupted, or you need a fresh start.

    Permission model:
    - Admin agent can restart ANY agent (specify target_agent_id).
    - All other agents can only restart THEMSELVES (target_agent_id must be empty or same as agent_id).

    After restart, the target agent will receive a continuation message with
    instructions to resume work. Conversation history is preserved via --resume.

    Args:
        agent_id: Your agent ID (the agent making the request).
        target_agent_id: Agent to restart. If empty, restarts yourself. Admin can specify any agent.
        reason: Why the restart is needed (e.g. 'MCP connections broken').
    """
    cfg = get_config()
    agents_expanded = resolve_agents(cfg)

    if agent_id not in agents_expanded:
        return json.dumps({"error": f"Unknown caller agent: {agent_id}"})

    # Determine target
    target = target_agent_id.strip() if target_agent_id else agent_id
    if target not in agents_expanded:
        return json.dumps({"error": f"Unknown target agent: {target}"})

    # Permission check: non-admin agents can only restart themselves
    if agent_id != "admin" and target != agent_id:
        return json.dumps({
            "error": f"Permission denied: {agent_id} can only restart itself, not {target}. "
                     f"Only admin can restart other agents."
        })

    # Send a continuation message that the target agent will receive after restart
    store = await get_store()
    if target == agent_id:
        requester_info = "由你自己请求"
    else:
        requester_info = f"由 {agent_id} 请求"

    continuation_msg = (
        f"你的 session 已被重启（{requester_info}）。\n"
        f"原因: {reason or '未指定'}\n\n"
        f"请执行以下步骤:\n"
        f"1. 检查 MCP 工具是否正常（尝试调用 list_tickets 或 get_inbox）\n"
        f"2. 用 get_inbox(agent_id=\"{target}\") 检查未读消息\n"
        f"3. 用 list_tickets(assignee=\"{target}\", status=\"3,4\") 检查待办任务\n"
        f"4. 继续之前的工作"
    )
    await store.insert_message("system", target, continuation_msg)

    # Run restart in background (don't block MCP response)
    config_path = os.environ.get("AGENTS_CONFIG_PATH", ".")
    root_dir = os.path.dirname(os.path.abspath(config_path))
    restart_script = os.path.join(root_dir, "restart_all_agents.sh")

    async def _do_restart():
        await asyncio.sleep(2)  # Brief delay to let MCP response go through
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", restart_script, target,
                cwd=root_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0:
                logger.info(f"Agent {target} restarted successfully (requested by {agent_id}: {reason})")
            else:
                logger.error(f"Agent {target} restart failed: {stderr.decode()}")
        except asyncio.TimeoutError:
            logger.error(f"Agent {target} restart timed out")
        except Exception as e:
            logger.error(f"Agent {target} restart error: {e}")

    asyncio.create_task(_do_restart())

    return json.dumps({
        "status": "restart_scheduled",
        "target_agent_id": target,
        "requested_by": agent_id,
        "message": f"Restart of {target} will happen in ~2 seconds. A continuation message has been sent.",
    })


# ════════════════════════════════════════
# Schedule Management Tools
# ════════════════════════════════════════


@app.tool()
@_with_timeout
async def schedule_task(
    agent_id: str,
    interval_hours: float,
    prompt: str,
) -> str:
    """Create a scheduled task that periodically dispatches an agent with a prompt.

    The schedule runs automatically: when interval_hours elapses since the last
    dispatch, the agent is woken up with the given prompt message.

    Permission: Admin can create schedules for any agent. Other agents should
    only create schedules for themselves (enforced by convention).

    Args:
        agent_id: Target agent ID for the schedule.
        interval_hours: How often to dispatch (e.g. 24 for daily, 12 for twice daily).
        prompt: The message to send when the schedule triggers.
    """
    store = await get_store()
    result = await store.create_schedule(agent_id, interval_hours, prompt)
    logger.info(f"Schedule created: #{result['id']} for {agent_id} every {interval_hours}h")
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def get_schedules(agent_id: str = None) -> str:
    """Get scheduled tasks for an agent or all agents.

    Args:
        agent_id: Agent ID to filter by. Pass 'all' or omit to get all schedules
                  (admin only by convention). Other agents should pass their own ID.
    """
    store = await get_store()
    if agent_id and agent_id != "all":
        result = await store.get_agent_schedules(agent_id)
    else:
        result = await store.get_all_schedules()
    return json.dumps(result, indent=2)


@app.tool()
@_with_timeout
async def remove_schedule(schedule_id: int, agent_id: str) -> str:
    """Remove a scheduled task.

    Permission: Admin can remove any schedule. Other agents can only remove
    their own schedules (server-side enforced).

    Args:
        schedule_id: ID of the schedule to remove.
        agent_id: Your agent ID (for permission check).
    """
    store = await get_store()
    schedule = await store.get_schedule(schedule_id)
    if not schedule:
        return json.dumps({"error": f"Schedule #{schedule_id} not found"})

    # Permission check: non-admin agents can only remove their own schedules
    if agent_id != "admin" and schedule["agent_id"] != agent_id:
        return json.dumps({
            "error": f"Permission denied: {agent_id} cannot remove schedule "
                     f"belonging to {schedule['agent_id']}. Only admin or the "
                     f"schedule owner can remove it."
        })

    deleted = await store.delete_schedule(schedule_id)
    logger.info(f"Schedule #{schedule_id} removed by {agent_id}")
    return json.dumps({"status": "deleted", "schedule_id": schedule_id})


# ════════════════════════════════════════
# Background auto-dispatch
# ════════════════════════════════════════


_dispatch_task = None
_usage_task = None


async def _usage_collection_loop(root_dir: str, agents: list[str], interval: int = 300):
    """Background loop that periodically collects token usage from JSONL files."""
    from agents_mcp.usage import collect_agent_usage

    logger.info(f"Usage collection loop started (interval={interval}s, agents={agents})")
    while True:
        try:
            store = await get_store()
            for agent_id in agents:
                try:
                    scan_state = await store.get_scan_state(agent_id)
                    result = collect_agent_usage(root_dir, agent_id, scan_state=scan_state)
                    if result["daily"]:
                        await store.upsert_daily_usage(agent_id, result["daily"])
                    await store.save_scan_state(agent_id, result["scan_state"])
                except Exception as e:
                    logger.warning(f"Usage collection failed for {agent_id}: {e}")
        except Exception as e:
            logger.warning(f"Usage collection loop error: {e}")
        await asyncio.sleep(interval)


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

    # Extract staleness detection config
    staleness_cfg = cfg.get("staleness", {})
    staleness_threshold = staleness_cfg.get("threshold_minutes", 30)

    config_path = os.environ.get("AGENTS_CONFIG_PATH", ".")
    root_dir = os.path.dirname(os.path.abspath(config_path))

    client = get_client()
    store = await get_store()

    # Seed schedules from agents.yaml into DB (only for agents with no existing schedule)
    import time as _time
    start_time = _time.time()
    seeded = 0
    for name, info in agents_expanded.items():
        sched = info.get("schedule")
        if sched and "interval_hours" in sched and "prompt" in sched:
            # Calculate initial last_dispatched_at from offset (stagger first dispatch)
            offset = sched.get("offset_hours", 0)
            interval_sec = sched["interval_hours"] * 3600
            initial_last = start_time - interval_sec + offset * 3600
            result = await store.seed_schedule(
                name, sched["interval_hours"], sched["prompt"],
                last_dispatched_at=initial_last,
            )
            if result:
                seeded += 1
                logger.info(f"Seeded schedule for {name}: every {sched['interval_hours']}h (offset {offset}h)")
    if seeded:
        logger.info(f"Seeded {seeded} schedule(s) from agents.yaml")

    _dispatch_task = asyncio.create_task(
        dispatch_loop(client, agents_list, tmux_session, store=store,
                      interval=30,
                      staleness_threshold=staleness_threshold,
                      root_dir=root_dir)
    )
    logger.info(f"Auto-dispatch background task started for {agents_list}")

    # Start usage collection background task (collect from ALL agents, not just dispatchable)
    global _usage_task
    all_agents = list(agents_expanded.keys())
    _usage_task = asyncio.create_task(
        _usage_collection_loop(root_dir, all_agents, interval=300)
    )
    logger.info(f"Usage collection background task started for {all_agents}")


# ════════════════════════════════════════
# Entry point
# ════════════════════════════════════════


def _check_port(host: str, port: int) -> bool:
    """Return True if port is available, False if in use."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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

            try:
                asyncio.run(_run_with_dispatch())
            except KeyboardInterrupt:
                logger.info("Daemon stopped by user (KeyboardInterrupt)")
            except Exception as e:
                logger.error(f"Daemon crashed: {e}", exc_info=True)
                raise
        else:
            try:
                asyncio.run(server.serve())
            except KeyboardInterrupt:
                logger.info("Daemon stopped by user (KeyboardInterrupt)")
            except Exception as e:
                logger.error(f"Daemon crashed: {e}", exc_info=True)
                raise
    else:
        app.run()


if __name__ == "__main__":
    main()
