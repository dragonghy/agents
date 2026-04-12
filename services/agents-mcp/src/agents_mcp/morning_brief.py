"""Morning Brief: automated daily digest for Human.

Generates a concise summary of system state, work progress, decisions needed,
and resources blocked. Delivered via email (Outlook MCP) or saved to file.

Designed for the v2 operating model: Human reads in 5 min, responds with
natural language, and the system acts on it.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from agents_mcp.sqlite_task_client import SQLiteTaskClient
from agents_mcp.store import AgentStore

logger = logging.getLogger(__name__)


async def generate_brief(
    client: SQLiteTaskClient,
    store: AgentStore,
    config: dict = None,
) -> str:
    """Generate the Morning Brief content.

    Returns:
        Markdown-formatted brief string.
    """
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today_str = now.strftime("%Y-%m-%d")

    sections = []
    sections.append(f"# Morning Brief — {now.strftime('%Y-%m-%d %A')}\n")

    # ── Section 1: System Health ──
    health_lines = []

    # Agent session status (check tmux)
    try:
        import re
        import subprocess
        tmux_session = (config or {}).get("tmux_session", "agents")
        out = subprocess.check_output(
            ["tmux", "list-windows", "-t", tmux_session, "-F", "#{window_name}"],
            text=True, timeout=5,
        )
        windows = [w.strip() for w in out.strip().split("\n") if w.strip()]
        health_lines.append(f"- **Agent windows**: {len(windows)} active in tmux")

        # Split v1 permanent windows from v2 ephemeral sessions.
        # v2 pattern: <role>-<digits> (e.g. dev-001, qa-042).
        v2_pattern = re.compile(r"^[a-z]+-\d+$")
        v1_windows = sorted(w for w in windows if not v2_pattern.match(w))
        v2_windows = sorted(w for w in windows if v2_pattern.match(w))

        health_lines.append("- **Active Sessions**:")
        if v1_windows:
            health_lines.append(
                f"  - v1 permanent ({len(v1_windows)}): "
                + ", ".join(f"`{w}`" for w in v1_windows)
            )
        else:
            health_lines.append("  - v1 permanent (0): none")
        if v2_windows:
            health_lines.append(
                f"  - v2 ephemeral ({len(v2_windows)}): "
                + ", ".join(f"`{w}`" for w in v2_windows)
            )
        else:
            health_lines.append("  - v2 ephemeral (0): none")
    except Exception:
        health_lines.append("- **Agent windows**: Unable to check tmux status")

    # Dispatch events in last 24h
    try:
        events = await store.get_dispatch_events(limit=200)
        recent_events = [
            e for e in events.get("events", [])
            if e.get("created_at", "") >= yesterday
        ]
        if recent_events:
            # Count by trigger type
            triggers = {}
            for e in recent_events:
                t = e.get("trigger_type", "unknown")
                triggers[t] = triggers.get(t, 0) + 1
            trigger_summary = ", ".join(f"{v} {k}" for k, v in sorted(triggers.items()))
            health_lines.append(f"- **Dispatches (24h)**: {len(recent_events)} ({trigger_summary})")
        else:
            health_lines.append("- **Dispatches (24h)**: None")
    except Exception:
        pass

    sections.append("## System Health\n" + "\n".join(health_lines))

    # ── Section 2: Work Summary ──
    work_lines = []

    # Tickets completed recently
    try:
        done_tickets = await client.list_tickets(status="0", limit=20)
        recent_done = [
            t for t in done_tickets.get("tickets", [])
            if t.get("dateToEdit", "") >= yesterday or t.get("date", "") >= yesterday
        ]
        if recent_done:
            work_lines.append(f"### Completed ({len(recent_done)})")
            for t in recent_done[:10]:
                work_lines.append(f"- ✅ #{t['id']}: {t['headline']}")
        else:
            work_lines.append("### Completed: None in the last 24 hours")
    except Exception as e:
        work_lines.append(f"### Completed: Error fetching ({e})")

    # Active in-progress tickets
    try:
        in_progress = await client.list_tickets(status="4", limit=20)
        ip_tickets = in_progress.get("tickets", [])
        if ip_tickets:
            work_lines.append(f"\n### In Progress ({len(ip_tickets)})")
            for t in ip_tickets:
                assignee = t.get("assignee", "?")
                work_lines.append(f"- 🔄 #{t['id']}: {t['headline']} (→ {assignee})")
    except Exception:
        pass

    # New unassigned tickets
    try:
        new_tickets = await client.list_tickets(status="3", limit=20)
        new_list = new_tickets.get("tickets", [])
        if new_list:
            work_lines.append(f"\n### New / Waiting ({len(new_list)})")
            for t in new_list:
                assignee = t.get("assignee", "unassigned")
                work_lines.append(f"- 📋 #{t['id']}: {t['headline']} (→ {assignee})")
    except Exception:
        pass

    # Blocked tickets
    try:
        blocked = await client.list_tickets(status="1", limit=20)
        blocked_list = blocked.get("tickets", [])
        if blocked_list:
            work_lines.append(f"\n### Blocked ({len(blocked_list)})")
            for t in blocked_list:
                work_lines.append(f"- 🚫 #{t['id']}: {t['headline']}")
    except Exception:
        pass

    sections.append("## Work Summary\n" + "\n".join(work_lines))

    # ── Section 3: Decisions Needed ──
    decision_lines = []

    # Human-assigned tickets (things waiting for Human)
    try:
        human_tickets = await client.list_tickets(status="3", assignee="human", limit=20)
        human_list = human_tickets.get("tickets", [])
        if human_list:
            for t in human_list:
                age_days = _ticket_age_days(t)
                priority = t.get("priority", "medium")
                tid = t["id"]
                headline = t["headline"]

                # Try to extract context from latest comment
                context_hint = ""
                try:
                    comments = await client.get_comments("ticket", tid, limit=1)
                    comment_list = comments.get("comments", [])
                    if comment_list:
                        latest = comment_list[0].get("text", "")
                        # Take first 150 chars as context
                        context_hint = latest[:150].replace("\n", " ").strip()
                        if len(latest) > 150:
                            context_hint += "..."
                except Exception:
                    pass

                decision_block = (
                    f"### #{tid}: {headline}\n"
                    f"- **Priority**: {priority} | **Waiting**: {age_days} days\n"
                )
                if context_hint:
                    decision_block += f"- **Context**: {context_hint}\n"
                decision_block += (
                    f"- → Choose: **[Approve]** **[Defer]** **[Cancel]** or reply with instructions\n"
                )
                decision_lines.append(decision_block)
        else:
            decision_lines.append("No decisions pending. 🎉")
    except Exception as e:
        decision_lines.append(f"Error checking: {e}")

    sections.append("## Decisions Needed\n" + "\n".join(decision_lines))

    # ── Section 4: Resources Needed ──
    resource_lines = []
    try:
        # Blocked tickets represent resource needs
        blocked_tickets = await client.list_tickets(status="1", limit=20)
        blocked_list = blocked_tickets.get("tickets", [])
        if blocked_list:
            for t in blocked_list:
                age_days = _ticket_age_days(t)
                depends = t.get("depends_on", "")
                blocker_info = f" (blocked by #{depends})" if depends else ""
                resource_lines.append(
                    f"- **#{t['id']}**: {t['headline']}{blocker_info} — waiting {age_days} days"
                )
        else:
            resource_lines.append("No resources blocked.")
    except Exception:
        pass
    sections.append("## Resources Needed\n" + "\n".join(resource_lines))

    # ── Section 5: Cost Report ──
    cost_lines = []
    try:
        usage_summary = await store.get_all_agents_usage_summary()
        if usage_summary:
            total_today_input = sum(a["today"]["input_tokens"] for a in usage_summary)
            total_today_output = sum(a["today"]["output_tokens"] for a in usage_summary)
            total_lifetime_input = sum(a["lifetime"]["input_tokens"] for a in usage_summary)
            total_lifetime_output = sum(a["lifetime"]["output_tokens"] for a in usage_summary)

            # Rough cost estimate (Claude Sonnet pricing ~$3/M input, $15/M output)
            today_cost = (total_today_input * 3 + total_today_output * 15) / 1_000_000
            lifetime_cost = (total_lifetime_input * 3 + total_lifetime_output * 15) / 1_000_000

            cost_lines.append(f"- **Today**: ~${today_cost:.2f} ({total_today_input:,} in / {total_today_output:,} out)")
            cost_lines.append(f"- **Lifetime**: ~${lifetime_cost:.2f}")

            # Top spenders today
            today_sorted = sorted(usage_summary, key=lambda a: a["today"]["output_tokens"], reverse=True)
            top = [a for a in today_sorted[:3] if a["today"]["output_tokens"] > 0]
            if top:
                cost_lines.append("- **Top spenders today**: " + ", ".join(
                    f"{a['agent_id']} (${(a['today']['input_tokens']*3 + a['today']['output_tokens']*15)/1_000_000:.2f})"
                    for a in top
                ))
        else:
            cost_lines.append("No usage data available.")
    except Exception as e:
        cost_lines.append(f"Error fetching usage: {e}")

    sections.append("## Cost Report\n" + "\n".join(cost_lines))

    # ── Section 6: Velocity (7-day trend) ──
    velocity_lines = []
    try:
        all_done = await client.list_tickets(status="0", limit=100)
        done_list = all_done.get("tickets", [])

        # Count completions by day (last 7 days)
        from collections import Counter
        daily_counts = Counter()
        for t in done_list:
            date_str = t.get("dateToEdit") or t.get("date", "")
            if date_str:
                day = date_str[:10]
                daily_counts[day] += 1

        # Last 7 days
        recent_days = []
        for i in range(7):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            count = daily_counts.get(d, 0)
            recent_days.append((d, count))

        total_7d = sum(c for _, c in recent_days)
        avg_per_day = total_7d / 7 if total_7d else 0

        spark = " ".join(f"{c}" for _, c in reversed(recent_days))
        velocity_lines.append(f"- **7-day total**: {total_7d} tickets completed (avg {avg_per_day:.1f}/day)")
        velocity_lines.append(f"- **Daily**: {spark} (oldest → newest)")
    except Exception as e:
        velocity_lines.append(f"Velocity data unavailable: {e}")

    sections.append("## Velocity\n" + "\n".join(velocity_lines))

    # ── Section 7: Project Breakdown ──
    project_lines = []
    try:
        # Gather all active tickets and group by project tag
        from collections import defaultdict
        project_stats = defaultdict(lambda: {"done": 0, "in_progress": 0, "new": 0, "blocked": 0})

        for status_code, status_name in [("0", "done"), ("4", "in_progress"), ("3", "new"), ("1", "blocked")]:
            tickets_resp = await client.list_tickets(status=status_code, limit=100)
            for t in tickets_resp.get("tickets", []):
                proj = _extract_project_tag(t.get("tags", ""))
                project_stats[proj][status_name] += 1

        if project_stats:
            for proj in sorted(project_stats.keys()):
                s = project_stats[proj]
                total = s["done"] + s["in_progress"] + s["new"] + s["blocked"]
                project_lines.append(
                    f"- **{proj}**: {total} tickets "
                    f"(✅{s['done']} 🔄{s['in_progress']} 📋{s['new']} 🚫{s['blocked']})"
                )
        else:
            project_lines.append("No project data available.")
    except Exception as e:
        project_lines.append(f"Project data unavailable: {e}")

    sections.append("## Projects\n" + "\n".join(project_lines))

    # ── Footer ──
    sections.append(
        "\n---\n"
        f"*Generated at {now.strftime('%H:%M:%S')} by Agent Harness Morning Brief*\n"
        "*Reply with decisions or instructions. Natural language is fine.*"
    )

    return "\n\n".join(sections)


def _extract_project_tag(tags: str) -> str:
    """Extract project name from tags like 'project:agent-hub,phase:implement'."""
    for tag in tags.split(","):
        tag = tag.strip()
        if tag.startswith("project:"):
            return tag.split(":", 1)[1]
    return "(untagged)"


def _ticket_age_days(ticket: dict) -> int:
    """Calculate ticket age in days."""
    date_str = ticket.get("date", "")
    if not date_str:
        return 0
    try:
        created = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (datetime.now() - created).days
    except Exception:
        return 0


async def save_brief(
    client: SQLiteTaskClient,
    store: AgentStore,
    config: dict = None,
    output_dir: str = None,
) -> str:
    """Generate and save the Morning Brief to a file.

    Returns:
        Path to the saved brief file.
    """
    brief = await generate_brief(client, store, config)

    if not output_dir:
        output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "briefs")
    os.makedirs(output_dir, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(output_dir, f"brief-{today}.md")
    with open(filepath, "w") as f:
        f.write(brief)

    logger.info(f"Morning Brief saved to {filepath}")
    return filepath


async def _send_brief_email(filepath: str, date_str: str):
    """Notify that the Morning Brief is ready for email delivery.

    The daemon generates the brief, but email delivery requires Microsoft MCP
    which is only available to agent sessions (not the daemon process).

    Strategy: Create a send_message to ops agent, who has Microsoft MCP access
    and can send the email on next dispatch cycle.
    """
    try:
        from agents_mcp.store import AgentStore
        # Get the store from the global state in server.py
        # We import lazily to avoid circular imports
        import agents_mcp.server as srv
        store = await srv.get_store()

        with open(filepath) as f:
            content = f.read()

        # Send message to ops agent to deliver the email
        await store.insert_message(
            from_agent="system",
            to_agent="ops",
            body=(
                f"Morning Brief for {date_str} is ready.\n\n"
                f"Please send it via email to huayang.guo@gmail.com using Microsoft MCP.\n"
                f"Subject: 🤖 Morning Brief — {date_str}\n"
                f"The brief content is saved at: {filepath}\n\n"
                f"Use: mcp__microsoft__send_email(account_id=..., to='huayang.guo@gmail.com', "
                f"subject='🤖 Morning Brief — {date_str}', body=<content of {filepath}>)"
            ),
        )
        logger.info(f"Morning Brief email delivery requested via ops agent")

    except Exception as e:
        logger.warning(f"Morning Brief email notification failed: {e}")


async def brief_loop(
    client: SQLiteTaskClient,
    store: AgentStore,
    config: dict = None,
    target_hour: int = 7,
    target_minute: int = 0,
    output_dir: str = None,
):
    """Background loop that generates the Morning Brief daily at the target time.

    Args:
        target_hour: Hour in local time to generate (default 7 AM).
        target_minute: Minute (default 0).
        output_dir: Directory to save briefs.
    """
    logger.info(f"Morning Brief loop started, target time: {target_hour:02d}:{target_minute:02d}")
    last_generated_date = None

    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            # Check if it's time and we haven't generated today
            if (now.hour >= target_hour and
                now.minute >= target_minute and
                last_generated_date != today):

                filepath = await save_brief(client, store, config, output_dir)
                last_generated_date = today
                logger.info(f"Morning Brief generated: {filepath}")

                # Send via email
                await _send_brief_email(filepath, today)

        except Exception as e:
            logger.error(f"Morning Brief generation failed: {e}")

        await asyncio.sleep(60)  # Check every minute
