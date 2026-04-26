"""Ticket endpoints (read-only)."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app import db, repo

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("")
async def list_tickets(
    workspace_id: Optional[int] = Query(None),
    status: Optional[int] = Query(None),
    assignee: Optional[str] = Query(None),
    limit: int = Query(200, le=500),
    offset: int = Query(0, ge=0),
):
    """List tickets with optional filters.

    Returns the columns the UI cares about. Tickets-board needs status to
    render Kanban columns (3=New, 4=InProgress, 1=Blocked, 0=Done, -1=Archived).
    """
    where = []
    params: list = []
    if workspace_id is not None:
        where.append("workspace_id = ?")
        params.append(workspace_id)
    if status is not None:
        where.append("status = ?")
        params.append(status)
    if assignee:
        where.append("assignee = ?")
        params.append(assignee)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, headline, type, status, priority, tags, projectId, "
        "assignee, workspace_id, phase, depends_on, date "
        f"FROM tickets {where_sql} "
        "ORDER BY status ASC, priority DESC, id DESC "
        "LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    rows = await db.fetch_all(repo.tasks_db_path(), sql, tuple(params))
    return {"tickets": rows, "total": len(rows), "limit": limit, "offset": offset}


@router.get("/board")
async def ticket_board(workspace_id: Optional[int] = Query(None)):
    """Kanban view: tickets grouped by status, restricted to active states."""
    where = ["status IN (3, 4, 1)"]
    params: list = []
    if workspace_id is not None:
        where.append("workspace_id = ?")
        params.append(workspace_id)
    where_sql = "WHERE " + " AND ".join(where)
    sql = (
        "SELECT id, headline, type, status, priority, tags, assignee, workspace_id, phase, date "
        f"FROM tickets {where_sql} "
        "ORDER BY priority DESC, id DESC"
    )
    rows = await db.fetch_all(repo.tasks_db_path(), sql, tuple(params))
    columns: dict[int, list] = {3: [], 4: [], 1: []}
    for r in rows:
        columns.setdefault(r["status"], []).append(r)
    return {
        "columns": [
            {"status": 3, "label": "New", "tickets": columns.get(3, [])},
            {"status": 4, "label": "In Progress", "tickets": columns.get(4, [])},
            {"status": 1, "label": "Blocked", "tickets": columns.get(1, [])},
        ]
    }


@router.get("/{ticket_id}")
async def get_ticket(ticket_id: int):
    row = await db.fetch_one(
        repo.tasks_db_path(),
        "SELECT * FROM tickets WHERE id = ?",
        (ticket_id,),
    )
    if not row:
        raise HTTPException(404, f"Ticket {ticket_id} not found")
    return row


@router.get("/{ticket_id}/comments")
async def ticket_comments(ticket_id: int, limit: int = Query(50, le=200)):
    rows = await db.fetch_all(
        repo.tasks_db_path(),
        "SELECT id, text, author, date, userId "
        "FROM comments "
        "WHERE module IN ('ticket', 'tickets') AND moduleId = ? "
        "ORDER BY id DESC LIMIT ?",
        (ticket_id, limit),
    )
    return {"comments": rows, "total": len(rows)}
