"""Smoke tests: hit each endpoint, assert response shape.

Requires a real harness repo (uses the live SQLite databases in read-only mode).
The Makefile sets AGENTS_REPO_ROOT for this; pytest discovers it from env.
"""

import os
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def has_repo():
    """Skip tests if AGENTS_REPO_ROOT isn't set or the DBs aren't there."""
    root = os.environ.get("AGENTS_REPO_ROOT")
    if not root or not os.path.exists(root):
        pytest.skip("AGENTS_REPO_ROOT not set or missing")
    if not os.path.exists(os.path.join(root, ".agents-mcp.db")):
        pytest.skip(".agents-mcp.db not found")
    if not os.path.exists(os.path.join(root, ".agents-tasks.db")):
        pytest.skip(".agents-tasks.db not found")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_health(has_repo, client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mcp_db_exists"] is True
    assert body["tasks_db_exists"] is True


async def test_workspaces(has_repo, client):
    r = await client.get("/api/workspaces")
    assert r.status_code == 200
    body = r.json()
    assert "workspaces" in body
    # Two seeded workspaces in the harness DB (Work + Personal)
    names = {w["name"] for w in body["workspaces"]}
    assert "Work" in names
    assert "Personal" in names


async def test_agents_list(has_repo, client):
    r = await client.get("/api/agents")
    assert r.status_code == 200
    body = r.json()
    ids = {a["id"] for a in body}
    # The four currently-registered v1 agents
    for expected in ("admin", "ops", "dev-alex", "qa-lucy"):
        assert expected in ids, f"missing agent {expected}; got {ids}"


async def test_agent_detail(has_repo, client):
    r = await client.get("/api/agents/dev-alex")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "dev-alex"
    assert "workload" in body
    assert "tmux_status" in body


async def test_agent_tickets(has_repo, client):
    r = await client.get("/api/agents/dev-alex/tickets")
    assert r.status_code == 200
    assert "tickets" in r.json()


async def test_tickets_list(has_repo, client):
    r = await client.get("/api/tickets?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "tickets" in body


async def test_ticket_board(has_repo, client):
    r = await client.get("/api/tickets/board")
    assert r.status_code == 200
    body = r.json()
    assert "columns" in body
    statuses = {c["status"] for c in body["columns"]}
    assert statuses == {3, 4, 1}


async def test_ticket_detail_498(has_repo, client):
    r = await client.get("/api/tickets/498")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 498
    assert "headline" in body


async def test_ticket_comments_498(has_repo, client):
    r = await client.get("/api/tickets/498/comments")
    assert r.status_code == 200
    assert "comments" in r.json()


async def test_briefs_list(has_repo, client):
    r = await client.get("/api/briefs")
    assert r.status_code == 200
    body = r.json()
    assert "briefs" in body
    assert body["total"] >= 1
    # Each brief should have date + filename
    for b in body["briefs"]:
        assert "date" in b
        assert "filename" in b


async def test_brief_today_or_recent(has_repo, client):
    list_resp = await client.get("/api/briefs?limit=1")
    items = list_resp.json()["briefs"]
    if not items:
        pytest.skip("no briefs on filesystem")
    most_recent = items[0]["date"]
    r = await client.get(f"/api/briefs/{most_recent}")
    assert r.status_code == 200
    assert r.json()["date"] == most_recent
    assert "markdown" in r.json()


async def test_brief_invalid_date(has_repo, client):
    r = await client.get("/api/briefs/not-a-date")
    assert r.status_code == 400


async def test_cost_summary(has_repo, client):
    r = await client.get("/api/cost/summary")
    assert r.status_code == 200
    body = r.json()
    for k in ("today_usd", "week_usd", "lifetime_usd", "by_agent", "pricing"):
        assert k in body
    assert body["lifetime_usd"] >= 0
    # Should have at least admin in the breakdown
    agent_ids = {a["agent_id"] for a in body["by_agent"]}
    assert "admin" in agent_ids


async def test_tmux_windows(has_repo, client):
    r = await client.get("/api/tmux/agents/windows")
    # tmux may or may not be running; either case should be 200 with `exists` flag
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        assert "windows" in body
        assert "exists" in body
