"""Brief Responder: parse Human's natural language reply to Morning Brief.

Interprets Human responses and translates them into ticket system actions:
- "Approve #442" → mark ticket as actionable, notify assignee
- "Defer #429" → set ticket status to blocked with note
- "Cancel #362" → archive the ticket
- "先做不需要支付的部分" → add comment to relevant ticket
- Direct instructions → create new ticket or add comment

This module provides the parsing logic. The actual execution happens
through the existing MCP tool infrastructure.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def parse_brief_response(text: str) -> list[dict]:
    """Parse a natural language response into actionable directives.

    Args:
        text: Human's free-form reply (could be voice-to-text, short typed message, etc.)

    Returns:
        List of action dicts, each with:
        - action: "approve" | "defer" | "cancel" | "comment" | "create" | "instruction"
        - ticket_id: int (if referencing a specific ticket)
        - message: str (human's words for context)
    """
    actions = []
    text = text.strip()
    if not text:
        return actions

    # Split by sentences/lines for multi-action responses
    segments = re.split(r'[。\n;；，,、]+', text)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        action = _parse_segment(segment)
        if action:
            actions.append(action)

    # If no structured actions found, do NOT auto-interpret.
    # Only explicit action keywords (approve/defer/cancel + ticket number) trigger execution.
    # Everything else is just a regular message — routed to admin inbox, not executed.
    return actions


def _parse_segment(text: str) -> Optional[dict]:
    """Parse a single segment into an action."""

    # Match explicit approve/defer/cancel patterns
    # English: "approve #442", "defer 429", "cancel #362"
    # Chinese: "批准 #442", "推迟 429", "取消 #362"
    approve_pattern = re.compile(
        r'(?:approve|批准|同意|通过|ok|yes|确认|执行)\s*#?(\d+)',
        re.IGNORECASE,
    )
    defer_pattern = re.compile(
        r'(?:defer|推迟|延迟|下周|以后再说|暂缓|搁置)\s*#?(\d+)',
        re.IGNORECASE,
    )
    cancel_pattern = re.compile(
        r'(?:cancel|取消|关闭|不要|不需要|算了)\s*#?(\d+)',
        re.IGNORECASE,
    )

    # Also match "A 方案" / "方案 A" / "choose A" patterns
    choice_pattern = re.compile(
        r'(?:choose|选|选择)?\s*(?:方案\s*)?([A-Za-z])\s*(?:方案)?',
        re.IGNORECASE,
    )

    m = approve_pattern.search(text)
    if m:
        return {"action": "approve", "ticket_id": int(m.group(1)), "message": text}

    m = defer_pattern.search(text)
    if m:
        return {"action": "defer", "ticket_id": int(m.group(1)), "message": text}

    m = cancel_pattern.search(text)
    if m:
        return {"action": "cancel", "ticket_id": int(m.group(1)), "message": text}

    # Check for ticket reference with instruction
    ticket_ref = re.search(r'#(\d+)', text)
    if ticket_ref:
        return {
            "action": "comment",
            "ticket_id": int(ticket_ref.group(1)),
            "message": text,
        }

    return None


async def execute_actions(
    actions: list[dict],
    client,
    store=None,
) -> list[dict]:
    """Execute parsed actions against the ticket system.

    Args:
        actions: List of action dicts from parse_brief_response()
        client: SQLiteTaskClient
        store: AgentStore (optional, for notifications)

    Returns:
        List of result dicts with status of each action.
    """
    results = []

    for action in actions:
        act = action["action"]
        tid = action.get("ticket_id")
        msg = action.get("message", "")

        try:
            if act == "approve" and tid:
                # Move from human queue → actionable (status 3, clear human assignee)
                await client.update_ticket(tid, status=3, assignee="")
                await client.add_comment(
                    "ticket", tid,
                    f"[Human] Approved. {msg}",
                    author="human",
                )
                results.append({"action": act, "ticket_id": tid, "status": "done"})

            elif act == "defer" and tid:
                await client.add_comment(
                    "ticket", tid,
                    f"[Human] Deferred. {msg}",
                    author="human",
                )
                results.append({"action": act, "ticket_id": tid, "status": "done"})

            elif act == "cancel" and tid:
                await client.update_ticket(tid, status=-1)  # Archive
                await client.add_comment(
                    "ticket", tid,
                    f"[Human] Cancelled. {msg}",
                    author="human",
                )
                results.append({"action": act, "ticket_id": tid, "status": "done"})

            elif act == "comment" and tid:
                await client.add_comment(
                    "ticket", tid,
                    f"[Human] {msg}",
                    author="human",
                )
                results.append({"action": act, "ticket_id": tid, "status": "done"})

            elif act == "instruction":
                # General instruction — create a new ticket for ops to handle
                new_tid = await client.create_ticket(
                    headline=f"Human instruction: {msg[:80]}",
                    assignee="ops",
                    tags="from:human",
                    description=f"Human replied to Morning Brief with:\n\n{msg}",
                )
                results.append({"action": act, "ticket_id": new_tid, "status": "created"})

            else:
                results.append({"action": act, "ticket_id": tid, "status": "unknown_action"})

        except Exception as e:
            results.append({"action": act, "ticket_id": tid, "status": f"error: {e}"})

    return results
