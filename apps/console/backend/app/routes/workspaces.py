"""Workspace endpoints (read-only)."""

from fastapi import APIRouter, HTTPException

from app import db, repo

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("")
async def list_workspaces():
    rows = await db.fetch_all(
        repo.tasks_db_path(),
        "SELECT id, name, kind, description, default_assignee, created_at, updated_at "
        "FROM workspaces ORDER BY id",
    )
    return {"workspaces": rows, "total": len(rows)}


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: int):
    row = await db.fetch_one(
        repo.tasks_db_path(),
        "SELECT id, name, kind, description, default_assignee, created_at, updated_at "
        "FROM workspaces WHERE id = ?",
        (workspace_id,),
    )
    if not row:
        raise HTTPException(404, f"Workspace {workspace_id} not found")
    return row
