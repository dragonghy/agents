"""REST API routes for the Display UI."""

import json
import logging
import os
import re
import subprocess
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Router

logger = logging.getLogger(__name__)

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def create_api_router(get_client, get_store, get_config, resolve_agents):
    """Create a Starlette Router with REST API endpoints.

    Args:
        get_client: Callable returning LeantimeClient
        get_store: Async callable returning AgentStore
        get_config: Callable returning config dict
        resolve_agents: Callable taking config dict, returning resolved agents
    """

    def _get_tmux_status(tmux_session: str, agent: str) -> str:
        try:
            from agents_mcp.dispatcher import get_agent_tmux_status
            return get_agent_tmux_status(tmux_session, agent)
        except (FileNotFoundError, OSError):
            return "unavailable"

    # ── Agents ──

    async def list_agents(request: Request) -> JSONResponse:
        cfg = get_config()
        tmux_session = cfg.get("tmux_session", "agents")
        agents_expanded = resolve_agents(cfg)
        client = get_client()
        store = await get_store()

        targets = list(agents_expanded.keys())
        workloads = await client.get_agent_workload(targets)
        profiles = {p["agent_id"]: p for p in await store.get_all_profiles()}

        result = []
        for name, info in agents_expanded.items():
            tmux_status = _get_tmux_status(tmux_session, name)
            wl = workloads.get(name, {})
            entry = {
                "id": name,
                "role": info.get("role", ""),
                "description": info.get("description", ""),
                "project": info.get("project", ""),
                "work_stream": info.get("work_stream", ""),
                "dispatchable": info.get("dispatchable", False),
                "tmux_status": tmux_status,
                "workload": wl,
            }
            profile = profiles.get(name)
            if profile:
                entry["profile"] = {
                    "identity": profile.get("identity"),
                    "current_context": profile.get("current_context"),
                    "expertise": profile.get("expertise"),
                    "updated_at": profile.get("updated_at"),
                }
            result.append(entry)

        return JSONResponse(result)

    async def get_agent(request: Request) -> JSONResponse:
        agent_id = request.path_params["id"]
        cfg = get_config()
        tmux_session = cfg.get("tmux_session", "agents")
        agents_expanded = resolve_agents(cfg)

        info = agents_expanded.get(agent_id)
        if not info:
            return JSONResponse({"error": f"Agent {agent_id} not found"}, status_code=404)

        client = get_client()
        store = await get_store()

        workloads = await client.get_agent_workload([agent_id])
        wl = workloads.get(agent_id, {})
        tmux_status = _get_tmux_status(tmux_session, agent_id)
        profile = await store.get_profile(agent_id)

        result = {
            "id": agent_id,
            "role": info.get("role", ""),
            "description": info.get("description", ""),
            "project": info.get("project", ""),
            "work_stream": info.get("work_stream", ""),
            "dispatchable": info.get("dispatchable", False),
            "tmux_status": tmux_status,
            "workload": wl,
        }
        if profile:
            result["profile"] = {
                "identity": profile.get("identity"),
                "current_context": profile.get("current_context"),
                "expertise": profile.get("expertise"),
                "updated_at": profile.get("updated_at"),
            }

        return JSONResponse(result)

    async def get_agent_terminal(request: Request) -> JSONResponse:
        agent_id = request.path_params["id"]
        cfg = get_config()
        tmux_session = cfg.get("tmux_session", "agents")
        lines = int(request.query_params.get("lines", "50"))

        raw = request.query_params.get("raw", "false").lower() == "true"

        try:
            out = subprocess.check_output(
                ["tmux", "capture-pane", "-t", f"{tmux_session}:{agent_id}",
                 "-p", "-S", f"-{lines}", "-e"],
                text=True, stderr=subprocess.DEVNULL,
            )
            output = out if raw else ANSI_RE.sub('', out)
            return JSONResponse({"agent_id": agent_id, "output": output, "raw": raw})
        except (subprocess.CalledProcessError, FileNotFoundError):
            return JSONResponse(
                {"agent_id": agent_id, "output": "", "error": "Terminal not available"},
            )

    # ── Tickets ──

    async def list_tickets(request: Request) -> JSONResponse:
        client = get_client()
        params = request.query_params
        result = await client.list_tickets(
            project_id=int(params["project_id"]) if "project_id" in params else None,
            status=params.get("status"),
            assignee=params.get("assignee"),
            tags=params.get("tags"),
            dateFrom=params.get("dateFrom"),
            limit=int(params["limit"]) if "limit" in params else None,
            offset=int(params.get("offset", 0)),
        )
        return JSONResponse(result)

    async def get_ticket(request: Request) -> JSONResponse:
        ticket_id = int(request.path_params["id"])
        client = get_client()
        result = await client.get_ticket(ticket_id)
        if not result:
            return JSONResponse({"error": f"Ticket {ticket_id} not found"}, status_code=404)
        return JSONResponse(result)

    async def ticket_comments(request: Request) -> JSONResponse:
        ticket_id = int(request.path_params["id"])
        client = get_client()
        if request.method == "POST":
            body = await request.json()
            comment = body.get("comment")
            if not comment:
                return JSONResponse({"error": "comment required"}, status_code=400)
            result = await client.add_comment("ticket", ticket_id, comment)
            return JSONResponse({"status": "added", "result": result})
        # GET
        result = await client.get_comments("ticket", ticket_id)
        if not isinstance(result, list):
            result = []
        return JSONResponse(result)

    async def get_ticket_subtasks(request: Request) -> JSONResponse:
        ticket_id = int(request.path_params["id"])
        client = get_client()
        result = await client.get_all_subtasks(ticket_id)
        if not isinstance(result, list):
            result = []
        return JSONResponse(result)

    async def get_status_labels(request: Request) -> JSONResponse:
        client = get_client()
        result = await client.get_status_labels()
        return JSONResponse(result)

    # ── Messages ──

    async def list_messages(request: Request) -> JSONResponse:
        store = await get_store()
        params = request.query_params
        limit = int(params.get("limit", "100"))
        offset = int(params.get("offset", "0"))
        agents_only = params.get("agents_only", "false").lower() == "true"

        result = await store.get_all_messages(limit=limit, offset=offset)

        # When agents_only=true, filter threads to only include conversations
        # between currently configured agents (from agents.yaml)
        agent_ids = None
        if agents_only:
            cfg = get_config()
            agents_expanded = resolve_agents(cfg)
            agent_ids = list(agents_expanded.keys()) + ["human"]

        threads = await store.get_conversation_threads(agent_ids=agent_ids)
        result["threads"] = threads
        return JSONResponse(result)

    async def get_inbox(request: Request) -> JSONResponse:
        agent_id = request.path_params["agent_id"]
        store = await get_store()
        params = request.query_params
        unread_only = params.get("unread_only", "true").lower() == "true"
        limit = int(params.get("limit", "20"))
        offset = int(params.get("offset", "0"))
        result = await store.get_inbox(agent_id, unread_only=unread_only,
                                       limit=limit, offset=offset)
        return JSONResponse(result)

    async def get_conversation(request: Request) -> JSONResponse:
        agent_a = request.path_params["a"]
        agent_b = request.path_params["b"]
        store = await get_store()
        params = request.query_params
        limit = int(params.get("limit", "50"))
        offset = int(params.get("offset", "0"))
        result = await store.get_conversation(agent_a, agent_b,
                                              limit=limit, offset=offset)
        return JSONResponse(result)

    # ── Write Operations ──

    async def send_message(request: Request) -> JSONResponse:
        body = await request.json()
        from_agent = body.get("from_agent")
        to_agent = body.get("to_agent")
        message = body.get("message")
        if not all([from_agent, to_agent, message]):
            return JSONResponse({"error": "from_agent, to_agent, message required"}, status_code=400)
        store = await get_store()
        msg_id = await store.insert_message(from_agent, to_agent, message)
        # Broadcast via WebSocket
        from agents_mcp.web.events import event_bus
        await event_bus.broadcast("message_sent", {
            "id": msg_id, "from_agent": from_agent,
            "to_agent": to_agent, "body": message,
        })
        return JSONResponse({"id": msg_id, "status": "sent"})

    async def create_ticket(request: Request) -> JSONResponse:
        body = await request.json()
        headline = body.get("headline")
        if not headline:
            return JSONResponse({"error": "headline required"}, status_code=400)
        client = get_client()
        kwargs = {}
        for field in ("description", "status", "priority"):
            if body.get(field) is not None:
                kwargs[field] = body[field]
        result = await client.create_ticket(
            headline=headline,
            project_id=body.get("project_id"),
            assignee=body.get("assignee"),
            **kwargs,
        )
        return JSONResponse({"ticket_id": result, "status": "created"})

    async def update_ticket(request: Request) -> JSONResponse:
        ticket_id = int(request.path_params["id"])
        body = await request.json()
        client = get_client()
        kwargs = {}
        for field in ("headline", "description", "status", "priority", "tags"):
            if body.get(field) is not None:
                kwargs[field] = body[field]
        result = await client.update_ticket(
            ticket_id,
            project_id=body.get("project_id"),
            assignee=body.get("assignee"),
            **kwargs,
        )
        return JSONResponse({"status": "updated"})

    async def reassign_ticket(request: Request) -> JSONResponse:
        ticket_id = int(request.path_params["id"])
        body = await request.json()
        from_agent = body.get("from_agent")
        to_agent = body.get("to_agent")
        if not all([from_agent, to_agent]):
            return JSONResponse({"error": "from_agent, to_agent required"}, status_code=400)
        client = get_client()
        comment = body.get("comment")

        # Add handoff comment (best-effort: don't block reassignment if comment fails)
        comment_added = True
        comment_error = None
        if comment:
            try:
                await client.add_comment(
                    "ticket", ticket_id,
                    f"[Handoff {from_agent} → {to_agent}] {comment}",
                )
            except Exception as e:
                logger.warning(
                    f"Failed to add handoff comment on #{ticket_id}: {e}. "
                    "Proceeding with reassignment."
                )
                comment_added = False
                comment_error = str(e)

        await client.update_ticket(ticket_id, assignee=to_agent, status=3)
        response = {
            "status": "reassigned", "ticket_id": ticket_id,
            "to": to_agent, "comment_added": comment_added,
        }
        if comment_error:
            response["comment_error"] = comment_error
        return JSONResponse(response)

    async def dispatch_agent(request: Request) -> JSONResponse:
        agent_id = request.path_params["id"]
        from agents_mcp.dispatcher import dispatch_cycle
        cfg = get_config()
        tmux_session = cfg.get("tmux_session", "agents")
        client = get_client()
        store = await get_store()
        results = await dispatch_cycle(client, [agent_id], tmux_session, store=store)
        # Broadcast dispatch result
        from agents_mcp.web.events import event_bus
        await event_bus.broadcast("dispatch_completed", results)
        return JSONResponse(results)

    async def dispatch_all_agents(request: Request) -> JSONResponse:
        from agents_mcp.dispatcher import dispatch_cycle
        cfg = get_config()
        tmux_session = cfg.get("tmux_session", "agents")
        agents_expanded = resolve_agents(cfg)
        targets = [
            name for name, info in agents_expanded.items()
            if info.get("dispatchable", False)
        ]
        client = get_client()
        store = await get_store()
        results = await dispatch_cycle(client, targets, tmux_session, store=store)
        # Broadcast dispatch result
        from agents_mcp.web.events import event_bus
        await event_bus.broadcast("dispatch_completed", results)
        return JSONResponse(results)

    async def submit_feedback(request: Request) -> JSONResponse:
        body = await request.json()
        title = body.get("title")
        if not title:
            return JSONResponse({"error": "title required"}, status_code=400)
        client = get_client()
        kwargs = {}
        if body.get("description"):
            kwargs["description"] = body["description"]
        if body.get("priority"):
            kwargs["priority"] = body["priority"]
        tags = "feedback"
        result = await client.create_ticket(
            headline=title,
            assignee=body.get("target_agent"),
            tags=tags,
            **kwargs,
        )
        return JSONResponse({"ticket_id": result, "status": "created"})

    # ── Token Usage ──

    async def get_agent_usage(request: Request) -> JSONResponse:
        agent_id = request.path_params["id"]
        store = await get_store()
        result = await store.get_agent_usage(agent_id)
        return JSONResponse(result)

    async def get_all_usage(request: Request) -> JSONResponse:
        store = await get_store()
        result = await store.get_all_agents_usage_summary()

        # Enrich each entry with project / work_stream from config
        cfg = get_config()
        agents_expanded = resolve_agents(cfg)
        for entry in result:
            info = agents_expanded.get(entry["agent_id"], {})
            entry["project"] = info.get("project", "")
            entry["work_stream"] = info.get("work_stream", "")

        return JSONResponse(result)

    async def refresh_agent_usage(request: Request) -> JSONResponse:
        """Trigger an immediate usage scan for one agent."""
        agent_id = request.path_params["id"]
        from agents_mcp.usage import collect_agent_usage

        cfg = get_config()
        config_path = os.environ.get("AGENTS_CONFIG_PATH", ".")
        root_dir = os.path.dirname(os.path.abspath(config_path))

        store = await get_store()
        scan_state = await store.get_scan_state(agent_id)
        result = collect_agent_usage(root_dir, agent_id, scan_state=scan_state)
        if result["daily"]:
            await store.upsert_daily_usage(agent_id, result["daily"])
        await store.save_scan_state(agent_id, result["scan_state"])

        usage = await store.get_agent_usage(agent_id)
        return JSONResponse(usage)

    # ── Journals ──

    def _get_root_dir() -> str:
        config_path = os.environ.get("AGENTS_CONFIG_PATH", ".")
        return os.path.dirname(os.path.abspath(config_path))

    async def list_agent_journals(request: Request) -> JSONResponse:
        agent_id = request.path_params["id"]
        cfg = get_config()
        agents_expanded = resolve_agents(cfg)
        if agent_id not in agents_expanded:
            return JSONResponse({"error": f"Agent {agent_id} not found"}, status_code=404)

        root_dir = _get_root_dir()
        journal_dir = os.path.join(root_dir, "agents", agent_id, "journal")

        if not os.path.isdir(journal_dir):
            return JSONResponse({"journals": [], "total": 0})

        # Collect all YYYY-MM-DD.md files
        date_re = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
        entries = []
        for fname in os.listdir(journal_dir):
            m = date_re.match(fname)
            if m:
                entries.append({"date": m.group(1), "filename": fname})

        # Sort by date descending (newest first)
        entries.sort(key=lambda e: e["date"], reverse=True)
        total = len(entries)

        # Pagination
        params = request.query_params
        limit = int(params.get("limit", "7"))
        offset = int(params.get("offset", "0"))
        entries = entries[offset:offset + limit]

        return JSONResponse({"journals": entries, "total": total})

    async def get_agent_journal(request: Request) -> JSONResponse:
        agent_id = request.path_params["id"]
        date = request.path_params["date"]

        # Validate date format to prevent path traversal
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return JSONResponse(
                {"error": "Invalid date format. Use YYYY-MM-DD."},
                status_code=400,
            )

        cfg = get_config()
        agents_expanded = resolve_agents(cfg)
        if agent_id not in agents_expanded:
            return JSONResponse({"error": f"Agent {agent_id} not found"}, status_code=404)

        root_dir = _get_root_dir()
        journal_path = os.path.join(root_dir, "agents", agent_id, "journal", f"{date}.md")

        if not os.path.isfile(journal_path):
            return JSONResponse(
                {"error": f"No journal found for {agent_id} on {date}"},
                status_code=404,
            )

        with open(journal_path, encoding="utf-8") as f:
            content = f.read()

        return JSONResponse({"date": date, "content": content})

    # ── Health ──

    async def health(request: Request) -> JSONResponse:
        from agents_mcp.dispatcher import get_rate_limit_info

        cfg = get_config()
        tmux_session = cfg.get("tmux_session", "agents")

        leantime_ok = False
        try:
            client = get_client()
            await client.get_status_labels()
            leantime_ok = True
        except Exception:
            pass

        tmux_ok = False
        try:
            subprocess.check_output(
                ["tmux", "has-session", "-t", tmux_session],
                stderr=subprocess.DEVNULL,
            )
            tmux_ok = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        result = {
            "status": "ok",
            "leantime": leantime_ok,
            "tmux_session": tmux_session,
            "tmux_active": tmux_ok,
        }
        rate_limit = get_rate_limit_info()
        if rate_limit:
            result["rate_limit"] = rate_limit

        return JSONResponse(result)

    routes = [
        # Read endpoints
        Route("/v1/agents", list_agents),
        Route("/v1/agents/{id}/terminal", get_agent_terminal),
        Route("/v1/agents/{id}/usage", get_agent_usage),
        Route("/v1/agents/{id}/usage/refresh", refresh_agent_usage, methods=["POST"]),
        Route("/v1/agents/{id}/journals/{date}", get_agent_journal),
        Route("/v1/agents/{id}/journals", list_agent_journals),
        Route("/v1/agents/{id}", get_agent),
        Route("/v1/usage", get_all_usage),
        Route("/v1/tickets/{id}/comments", ticket_comments, methods=["GET", "POST"]),
        Route("/v1/tickets/{id}/subtasks", get_ticket_subtasks),
        Route("/v1/tickets/{id}/reassign", reassign_ticket, methods=["POST"]),
        Route("/v1/tickets/{id}", get_ticket, methods=["GET"]),
        Route("/v1/tickets", list_tickets, methods=["GET"]),
        Route("/v1/messages", list_messages, methods=["GET"]),
        Route("/v1/messages/inbox/{agent_id}", get_inbox),
        Route("/v1/messages/conversation/{a}/{b}", get_conversation),
        Route("/v1/status-labels", get_status_labels),
        Route("/v1/health", health),
        # Write endpoints
        Route("/v1/messages/send", send_message, methods=["POST"]),
        Route("/v1/tickets/create", create_ticket, methods=["POST"]),
        Route("/v1/tickets/{id}/update", update_ticket, methods=["PATCH", "POST"]),
        Route("/v1/agents/{id}/dispatch", dispatch_agent, methods=["POST"]),
        Route("/v1/agents/dispatch-all", dispatch_all_agents, methods=["POST"]),
        Route("/v1/feedback", submit_feedback, methods=["POST"]),
    ]

    return Router(routes=routes)
