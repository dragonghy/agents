"""Dashboard aggregate stats API route."""

import logging
import os
from datetime import datetime, timedelta

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..auth import get_current_user
from ..db import get_db

logger = logging.getLogger(__name__)

DAEMON_API_URL = os.environ.get("DAEMON_API_URL", "http://127.0.0.1:8765")


def _require_auth(handler):
    """Decorator that injects user_id from JWT."""

    async def wrapper(request: Request) -> JSONResponse:
        payload = await get_current_user(request)
        if not payload:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        request.state.user_id = payload["sub"]
        return await handler(request)

    return wrapper


async def _fetch_daemon_data() -> dict:
    """Fetch agent and ticket data from the agents-mcp daemon.

    Returns a dict with 'agents' and 'tickets' keys.
    Falls back to empty data on failure.
    """
    agents_data: dict = {"total": 0, "by_status": {}, "details": []}
    tickets_data: dict = {
        "total": 0,
        "by_status": {},
        "human_blocked": 0,
        "stale_count": 0,
    }
    messages_data: dict = {"unread_total": 0}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Fetch agent profiles
            try:
                resp = await client.get(f"{DAEMON_API_URL}/api/v1/profiles")
                if resp.status_code == 200:
                    profiles = resp.json()
                    if isinstance(profiles, dict):
                        profiles = profiles.get("profiles", [])
                    agents_data["total"] = len(profiles)
                    status_counts: dict[str, int] = {}
                    details = []
                    for p in profiles:
                        status = (p.get("status") or p.get("current_status") or "idle").lower()
                        status_counts[status] = status_counts.get(status, 0) + 1
                        details.append({
                            "name": p.get("agent_id") or p.get("name", "unknown"),
                            "status": status,
                            "current_ticket": p.get("current_context"),
                        })
                    agents_data["by_status"] = status_counts
                    agents_data["details"] = details
            except Exception as e:
                logger.debug("Failed to fetch daemon profiles: %s", e)

            # Fetch tickets
            try:
                resp = await client.get(f"{DAEMON_API_URL}/api/v1/tickets")
                if resp.status_code == 200:
                    data = resp.json()
                    tickets = data if isinstance(data, list) else data.get("tickets", [])
                    tickets_data["total"] = len(tickets)
                    t_status_counts: dict[str, int] = {}
                    human_blocked = 0
                    stale_count = 0
                    for t in tickets:
                        # Leantime status mapping: 3=new, 4=in_progress, 1=blocked, 0=done
                        raw_status = t.get("status")
                        if raw_status == 3 or raw_status == "3":
                            s = "new"
                        elif raw_status == 4 or raw_status == "4":
                            s = "in_progress"
                        elif raw_status == 1 or raw_status == "1":
                            s = "blocked"
                        elif raw_status == 0 or raw_status == "0":
                            s = "done"
                        else:
                            s = str(raw_status) if raw_status is not None else "unknown"
                        t_status_counts[s] = t_status_counts.get(s, 0) + 1

                        # Detect human-blocked
                        tags = t.get("tags") or ""
                        desc = t.get("description") or ""
                        assignee = t.get("editorId") or ""
                        if "agent:human" in str(tags) or "agent:human" in str(assignee):
                            human_blocked += 1
                        elif "DEPENDS_ON" in desc and s == "blocked":
                            human_blocked += 1

                        # Detect stale (in_progress > 3 days)
                        if s == "in_progress":
                            updated = t.get("dateModified") or t.get("modified") or ""
                            if updated:
                                try:
                                    mod_date = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                                    if (datetime.now(mod_date.tzinfo) - mod_date).days > 3:
                                        stale_count += 1
                                except (ValueError, TypeError):
                                    pass

                    tickets_data["by_status"] = t_status_counts
                    tickets_data["human_blocked"] = human_blocked
                    tickets_data["stale_count"] = stale_count
            except Exception as e:
                logger.debug("Failed to fetch daemon tickets: %s", e)

            # Fetch unread messages
            try:
                resp = await client.get(f"{DAEMON_API_URL}/api/v1/messages/unread")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        messages_data["unread_total"] = data.get("total", 0)
                    elif isinstance(data, list):
                        messages_data["unread_total"] = len(data)
            except Exception as e:
                logger.debug("Failed to fetch daemon messages: %s", e)

    except Exception as e:
        logger.warning("Failed to connect to daemon at %s: %s", DAEMON_API_URL, e)

    return {
        "agents": agents_data,
        "tickets": tickets_data,
        "messages": messages_data,
    }


async def _fetch_token_stats(user_id: str) -> dict:
    """Fetch token usage stats from the local database.

    Returns today's total, yesterday's total, and 7-day daily breakdown.
    """
    db = await get_db()
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=6)

    today_str = today.isoformat()
    yesterday_str = (today - timedelta(days=1)).isoformat()
    week_ago_str = week_ago.isoformat()

    # Get all companies for this user
    cursor = await db.execute(
        "SELECT id FROM companies WHERE user_id = ? AND status != 'deleted'",
        (user_id,),
    )
    company_rows = await cursor.fetchall()
    company_ids = [r["id"] for r in company_rows]

    if not company_ids:
        empty_daily = []
        for i in range(7):
            d = (week_ago + timedelta(days=i)).isoformat()
            empty_daily.append({"date": d, "total_tokens": 0})
        return {"today": 0, "yesterday": 0, "daily": empty_daily}

    placeholders = ",".join("?" for _ in company_ids)

    # Today's total
    cursor = await db.execute(
        f"""SELECT COALESCE(SUM(total_tokens), 0) as total
        FROM token_usage WHERE company_id IN ({placeholders}) AND date = ?""",
        [*company_ids, today_str],
    )
    row = await cursor.fetchone()
    today_total = row["total"] if row else 0

    # Yesterday's total
    cursor = await db.execute(
        f"""SELECT COALESCE(SUM(total_tokens), 0) as total
        FROM token_usage WHERE company_id IN ({placeholders}) AND date = ?""",
        [*company_ids, yesterday_str],
    )
    row = await cursor.fetchone()
    yesterday_total = row["total"] if row else 0

    # 7-day daily breakdown
    cursor = await db.execute(
        f"""SELECT date, SUM(total_tokens) as total_tokens
        FROM token_usage
        WHERE company_id IN ({placeholders}) AND date >= ?
        GROUP BY date
        ORDER BY date ASC""",
        [*company_ids, week_ago_str],
    )
    daily_rows = await cursor.fetchall()
    daily = [{"date": r["date"], "total_tokens": r["total_tokens"]} for r in daily_rows]

    # Fill in missing dates with 0
    daily_map = {d["date"]: d["total_tokens"] for d in daily}
    filled_daily = []
    for i in range(7):
        d = (week_ago + timedelta(days=i)).isoformat()
        filled_daily.append({"date": d, "total_tokens": daily_map.get(d, 0)})

    return {
        "today": today_total,
        "yesterday": yesterday_total,
        "daily": filled_daily,
    }


@_require_auth
async def dashboard_stats_route(request: Request) -> JSONResponse:
    """GET /api/dashboard/stats -- aggregate dashboard statistics."""
    daemon_data = await _fetch_daemon_data()
    token_data = await _fetch_token_stats(request.state.user_id)

    return JSONResponse({
        "agents": daemon_data["agents"],
        "tickets": daemon_data["tickets"],
        "tokens": token_data,
        "messages": daemon_data["messages"],
    })


routes = [
    Route("/api/dashboard/stats", dashboard_stats_route, methods=["GET"]),
]
