"""Brief history — read filesystem briefs/brief-YYYY-MM-DD.md."""

import re

from fastapi import APIRouter, HTTPException

from app import repo

router = APIRouter(prefix="/briefs", tags=["briefs"])

BRIEF_RE = re.compile(r"^brief-(\d{4}-\d{2}-\d{2})\.md$")


@router.get("")
async def list_briefs(limit: int = 14):
    """Return up to `limit` most recent briefs (date + filename only)."""
    bdir = repo.briefs_dir()
    if not bdir.exists():
        return {"briefs": [], "total": 0}
    items = []
    for path in sorted(bdir.iterdir(), reverse=True):
        m = BRIEF_RE.match(path.name)
        if not m:
            continue
        items.append(
            {
                "date": m.group(1),
                "filename": path.name,
                "size_bytes": path.stat().st_size,
            }
        )
        if len(items) >= limit:
            break
    return {"briefs": items, "total": len(items)}


@router.get("/{date}")
async def get_brief(date: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    path = repo.briefs_dir() / f"brief-{date}.md"
    if not path.exists():
        raise HTTPException(404, f"No brief for {date}")
    return {"date": date, "markdown": path.read_text(encoding="utf-8")}
