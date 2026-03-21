"""Tests for the dashboard stats endpoint."""

from unittest.mock import AsyncMock, patch


def test_dashboard_stats_unauthenticated(client):
    """Dashboard stats requires authentication."""
    resp = client.get("/api/dashboard/stats")
    assert resp.status_code == 401


def test_dashboard_stats_returns_structure(client, auth_headers):
    """Dashboard stats returns the expected top-level keys."""
    resp = client.get("/api/dashboard/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert "tickets" in data
    assert "tokens" in data
    assert "messages" in data


def test_dashboard_stats_tokens_structure(client, auth_headers):
    """Token stats include today, yesterday, and 7-day daily breakdown."""
    resp = client.get("/api/dashboard/stats", headers=auth_headers)
    data = resp.json()
    tokens = data["tokens"]
    assert "today" in tokens
    assert "yesterday" in tokens
    assert "daily" in tokens
    assert isinstance(tokens["daily"], list)
    assert len(tokens["daily"]) == 7


def test_dashboard_stats_agents_structure(client, auth_headers):
    """Agent data includes total, by_status, and details."""
    resp = client.get("/api/dashboard/stats", headers=auth_headers)
    data = resp.json()
    agents = data["agents"]
    assert "total" in agents
    assert "by_status" in agents
    assert "details" in agents
    assert isinstance(agents["details"], list)


def test_dashboard_stats_tickets_structure(client, auth_headers):
    """Ticket data includes total, by_status, human_blocked, stale_count."""
    resp = client.get("/api/dashboard/stats", headers=auth_headers)
    data = resp.json()
    tickets = data["tickets"]
    assert "total" in tickets
    assert "by_status" in tickets
    assert "human_blocked" in tickets
    assert "stale_count" in tickets


def test_dashboard_stats_with_usage_data(client, auth_headers):
    """Token stats reflect recorded usage."""
    from datetime import datetime

    # Create a company first
    resp = client.post(
        "/api/companies",
        json={"name": "Test Co", "template": "solo"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    company_id = resp.json()["company"]["id"]

    # Record some usage for today
    today = datetime.utcnow().strftime("%Y-%m-%d")
    resp = client.post(
        f"/api/companies/{company_id}/usage",
        json={"date": today, "input_tokens": 1000, "output_tokens": 2000, "model": "test"},
        headers={"x-usage-secret": "dev-usage-secret"},
    )
    assert resp.status_code == 201

    # Check dashboard stats
    resp = client.get("/api/dashboard/stats", headers=auth_headers)
    data = resp.json()
    assert data["tokens"]["today"] == 3000


def test_dashboard_stats_messages_structure(client, auth_headers):
    """Messages data includes unread_total."""
    resp = client.get("/api/dashboard/stats", headers=auth_headers)
    data = resp.json()
    messages = data["messages"]
    assert "unread_total" in messages
    assert isinstance(messages["unread_total"], int)
