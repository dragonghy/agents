"""Leantime JSON-RPC 2.0 client with agent-aware abstractions."""

import httpx
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Fields returned in ticket summary (list view)
SUMMARY_FIELDS = {
    "id", "headline", "status", "tags", "priority",
    "date", "dateToEdit", "type", "dependingTicketId",
    "projectId", "milestoneid",
}

# Fields returned in ticket detail view (get_ticket)
DETAIL_FIELDS = SUMMARY_FIELDS | {
    "description", "userId", "editFrom", "editTo",
    "storypoints", "sprint", "acceptanceCriteria",
}

# Fields returned in comment summary
COMMENT_FIELDS = {"id", "text", "userId", "date", "moduleId"}


def extract_assignee(ticket: dict) -> Optional[str]:
    """Extract agent assignee from tags (e.g. 'agent:dev' -> 'dev')."""
    tags = ticket.get("tags") or ""
    for part in tags.split(","):
        part = part.strip()
        if part.startswith("agent:"):
            return part[6:]
    return None


def inject_assignee(ticket: dict) -> dict:
    """Add 'assignee' field extracted from tags."""
    ticket = dict(ticket)
    ticket["assignee"] = extract_assignee(ticket)
    return ticket


def tags_with_assignee(existing_tags: Optional[str], assignee: str) -> str:
    """Add/replace agent: tag in a tags string."""
    parts = []
    if existing_tags:
        parts = [p.strip() for p in existing_tags.split(",") if not p.strip().startswith("agent:")]
    parts.append(f"agent:{assignee}")
    return ",".join(parts)


class LeantimeClient:
    """Client for Leantime JSON-RPC API with agent-aware features."""

    def __init__(self, base_url: str, api_key: str, project_id: int = 3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.project_id = project_id
        self.endpoint = f"{self.base_url}/api/jsonrpc"
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _call(self, method: str, params: Optional[dict] = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_id(),
        }
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": self.api_key,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.endpoint, json=payload, headers=headers, timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                err = data["error"]
                raise RuntimeError(f"Leantime API Error {err.get('code')}: {err.get('message')}")
            return data.get("result")

    # ── Ticket operations ──

    async def get_ticket(self, ticket_id: int, prune: bool = True) -> dict:
        """Get ticket by ID. If prune=True, returns DETAIL_FIELDS + assignee."""
        raw = await self._call(
            "leantime.rpc.Tickets.Tickets.getTicket", {"id": ticket_id}
        )
        if not raw or not prune:
            return raw
        pruned = {k: v for k, v in raw.items() if k in DETAIL_FIELDS}
        return inject_assignee(pruned)

    async def list_tickets(
        self,
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        tags: Optional[str] = None,
        dateFrom: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> dict:
        """List tickets with summary fields and pagination.

        Args:
            assignee: Filter by agent name (e.g. 'dev'). Translates to tag filter.

        Returns:
            {"tickets": [...], "total": N, "offset": N, "limit": N}
        """
        pid = project_id or self.project_id
        result = await self._call(
            "leantime.rpc.Tickets.Tickets.getAll",
            {"searchCriteria": {"currentProject": pid}},
        )
        if not isinstance(result, list):
            return {"tickets": [], "total": 0, "offset": 0, "limit": 0}

        # Status filter (default: active only)
        effective_status = status if status is not None else "1,3,4"
        if effective_status != "all":
            allowed = {int(s.strip()) for s in effective_status.split(",")}
            result = [t for t in result if t.get("status") in allowed]

        # Assignee filter (translates to agent:xxx tag)
        effective_tags = tags
        if assignee:
            effective_tags = f"agent:{assignee}"

        # Tags filter
        if effective_tags:
            result = [t for t in result if t.get("tags") and effective_tags in t["tags"]]

        # Date filter
        if dateFrom:
            result = [t for t in result if (t.get("date") or "") >= dateFrom]

        total = len(result)

        # Pagination
        if offset > 0:
            result = result[offset:]
        if limit is not None and limit > 0:
            result = result[:limit]

        # Field pruning + assignee injection
        pruned = [
            inject_assignee({k: v for k, v in t.items() if k in SUMMARY_FIELDS})
            for t in result
        ]

        return {
            "tickets": pruned,
            "total": total,
            "offset": offset,
            "limit": limit or total,
        }

    async def create_ticket(self, headline: str, project_id: Optional[int] = None,
                            user_id: int = 1, tags: Optional[str] = None,
                            assignee: Optional[str] = None, **kwargs) -> Any:
        """Create ticket. If assignee is set, translates to agent:xxx tag."""
        effective_tags = tags
        if assignee:
            effective_tags = tags_with_assignee(tags, assignee)
        values = {
            "headline": headline,
            "projectId": project_id or self.project_id,
            "userId": user_id,
            "date": datetime.now().strftime("%Y-%m-%d"),
            **kwargs,
        }
        if effective_tags is not None:
            values["tags"] = effective_tags
        return await self._call(
            "leantime.rpc.Tickets.Tickets.addTicket", {"values": values}
        )

    async def update_ticket(self, ticket_id: int, project_id: Optional[int] = None,
                            assignee: Optional[str] = None, **kwargs) -> Any:
        """Update ticket. If assignee is set, translates to agent:xxx tag."""
        pid = project_id or self.project_id
        current = await self.get_ticket(ticket_id, prune=False)
        if current:
            values = {**current, "id": ticket_id, "projectId": pid, **kwargs}
        else:
            values = {"id": ticket_id, "projectId": pid, **kwargs}
        if assignee:
            values["tags"] = tags_with_assignee(values.get("tags"), assignee)
        return await self._call(
            "leantime.rpc.Tickets.Tickets.updateTicket", {"values": values}
        )

    # ── Comments ──

    @staticmethod
    def _normalize_module(module: str) -> str:
        """Normalize module name: 'tickets' -> 'ticket' to avoid split comments."""
        if module == "tickets":
            return "ticket"
        return module

    async def add_comment(self, module: str, module_id: int, comment: str) -> Any:
        module = self._normalize_module(module)
        return await self._call(
            "leantime.rpc.AgentsApi.addComment",
            {
                "text": comment,
                "module": module,
                "entityId": module_id,
            },
        )

    async def get_comments(self, module: str, module_id: int) -> Any:
        module = self._normalize_module(module)
        raw = await self._call(
            "leantime.rpc.Comments.getComments",
            {"module": module, "entityId": module_id},
        )
        if not isinstance(raw, list):
            raw = []
        # Also fetch comments stored under legacy "tickets" module name
        if module == "ticket":
            legacy = await self._call(
                "leantime.rpc.Comments.getComments",
                {"module": "tickets", "entityId": module_id},
            )
            if isinstance(legacy, list):
                seen_ids = {c.get("id") for c in raw}
                raw.extend(c for c in legacy if c.get("id") not in seen_ids)
        return [
            {k: v for k, v in c.items() if k in COMMENT_FIELDS}
            for c in raw
        ]

    # ── Subtasks ──

    async def get_all_subtasks(self, ticket_id: int) -> Any:
        return await self._call(
            "leantime.rpc.Tickets.Tickets.getAllSubtasks", {"ticketId": ticket_id}
        )

    async def upsert_subtask(self, parent_ticket_id: int, headline: str,
                             tags: Optional[str] = None, **kwargs) -> Any:
        parent = await self.get_ticket(parent_ticket_id, prune=False)
        if not parent:
            raise ValueError(f"Parent ticket {parent_ticket_id} not found")
        values = {
            "headline": headline,
            "type": "subtask",
            "projectId": parent.get("projectId"),
            "userId": parent.get("userId"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "dependingTicketId": parent_ticket_id,
            "milestoneid": parent.get("milestoneid") or "",
            **kwargs,
        }
        if tags is not None:
            values["tags"] = tags
        return await self._call(
            "leantime.rpc.Tickets.Tickets.addTicket", {"values": values}
        )

    # ── Status labels ──

    async def get_status_labels(self) -> Any:
        return await self._call("leantime.rpc.Tickets.Tickets.getStatusLabels")

    # ── Dependency checking (for auto-dispatch) ──

    async def check_and_unblock_deps(self) -> list[str]:
        """Check blocked tickets' DEPENDS_ON and unblock if all deps are done.

        Returns list of log messages.
        """
        result = await self._call(
            "leantime.rpc.Tickets.Tickets.getAll",
            {"searchCriteria": {"currentProject": self.project_id}},
        )
        if not isinstance(result, list):
            return []

        status_map = {}
        for t in result:
            tid = t.get("id")
            if tid is not None:
                status_map[int(tid)] = int(t.get("status", 99))

        messages = []
        for t in result:
            if int(t.get("status", 99)) != 1:
                continue
            desc = t.get("description") or ""
            match = re.search(
                r"DEPENDS_ON:\s*((?:#\d+|&#35;\d+)(?:\s*,\s*(?:#\d+|&#35;\d+))*)",
                desc,
            )
            if not match:
                continue
            dep_ids = [int(x) for x in re.findall(r"(\d+)", match.group(1))]
            if not dep_ids:
                continue
            if not all(status_map.get(d, 99) in (0, -1) for d in dep_ids):
                continue

            ticket_id = int(t["id"])
            current = await self.get_ticket(ticket_id, prune=False)
            if current:
                current["status"] = 3
                current["id"] = ticket_id
                await self._call(
                    "leantime.rpc.Tickets.Tickets.updateTicket",
                    {"values": current},
                )
                messages.append(f"Unblocked #{ticket_id} (deps {dep_ids} all done)")

        return messages

    async def has_pending_tasks(self, agent: str) -> bool:
        """Check if an agent has pending tasks (status 3 or 4)."""
        result = await self._call(
            "leantime.rpc.Tickets.Tickets.getAll",
            {"searchCriteria": {"currentProject": self.project_id}},
        )
        if not isinstance(result, list):
            return False
        tag = f"agent:{agent}"
        return any(
            t.get("tags") and tag in t["tags"] and t.get("status") in (3, 4)
            for t in result
        )

    async def get_stale_in_progress(self, agent: str, threshold_minutes: int = 30) -> list[dict]:
        """Get in_progress (status=4) tickets for agent older than threshold.

        Uses ticket creation date as proxy for staleness. Returns list of
        dicts with id, headline, date for stale tickets.
        """
        result = await self._call(
            "leantime.rpc.Tickets.Tickets.getAll",
            {"searchCriteria": {"currentProject": self.project_id}},
        )
        if not isinstance(result, list):
            return []

        tag = f"agent:{agent}"
        cutoff = datetime.utcnow() - timedelta(minutes=threshold_minutes)
        stale = []

        for t in result:
            if not (t.get("tags") and tag in t["tags"] and t.get("status") == 4):
                continue
            date_str = t.get("date") or ""
            if not date_str or date_str.startswith("0000"):
                continue
            try:
                ticket_date = datetime.strptime(date_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    ticket_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue
            if ticket_date < cutoff:
                stale.append({
                    "id": int(t.get("id")),
                    "headline": t.get("headline", ""),
                    "date": date_str,
                })
        return stale

    async def get_agent_workload(self, agents: list[str]) -> dict[str, dict]:
        """Get workload info for multiple agents.

        Returns: {agent_name: {"in_progress": N, "new": N, "blocked": N, "total_active": N}}
        """
        result = await self._call(
            "leantime.rpc.Tickets.Tickets.getAll",
            {"searchCriteria": {"currentProject": self.project_id}},
        )
        if not isinstance(result, list):
            return {a: {"in_progress": 0, "new": 0, "blocked": 0, "total_active": 0} for a in agents}

        workloads = {}
        for agent in agents:
            tag = f"agent:{agent}"
            agent_tickets = [
                t for t in result
                if t.get("tags") and tag in t["tags"]
            ]
            in_progress = sum(1 for t in agent_tickets if t.get("status") == 4)
            new = sum(1 for t in agent_tickets if t.get("status") == 3)
            blocked = sum(1 for t in agent_tickets if t.get("status") == 1)
            workloads[agent] = {
                "in_progress": in_progress,
                "new": new,
                "blocked": blocked,
                "total_active": in_progress + new,
            }
        return workloads
