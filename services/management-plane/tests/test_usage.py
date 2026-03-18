"""Tests for token usage tracking and billing API."""

import os

os.environ["MGMT_MOCK_MODE"] = "true"


def test_record_and_get_usage(client, auth_headers):
    """POST usage, then GET usage returns it."""
    # Create company
    r = client.post("/api/companies", json={"name": "Usage Test"}, headers=auth_headers)
    cid = r.json()["company"]["id"]

    # Record usage via internal API (with shared secret)
    r = client.post(
        f"/api/companies/{cid}/usage",
        json={
            "date": "2026-03-17",
            "input_tokens": 1000,
            "output_tokens": 500,
            "model": "claude-sonnet-4-20250514",
        },
        headers={"x-usage-secret": "dev-usage-secret"},
    )
    assert r.status_code == 201
    assert r.json()["recorded"] is True

    # Get usage
    r = client.get(f"/api/companies/{cid}/usage", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["total_tokens"] == 1500
    assert data["summary"]["total_input"] == 1000
    assert data["summary"]["total_output"] == 500
    assert len(data["records"]) == 1


def test_usage_date_filter(client, auth_headers):
    """GET usage supports date range filtering."""
    r = client.post("/api/companies", json={"name": "Filter Test"}, headers=auth_headers)
    cid = r.json()["company"]["id"]
    secret = {"x-usage-secret": "dev-usage-secret"}

    # Record usage on different dates
    client.post(f"/api/companies/{cid}/usage", json={
        "date": "2026-03-15", "input_tokens": 100, "output_tokens": 50,
    }, headers=secret)
    client.post(f"/api/companies/{cid}/usage", json={
        "date": "2026-03-16", "input_tokens": 200, "output_tokens": 100,
    }, headers=secret)
    client.post(f"/api/companies/{cid}/usage", json={
        "date": "2026-03-17", "input_tokens": 300, "output_tokens": 150,
    }, headers=secret)

    # Filter by date range
    r = client.get(
        f"/api/companies/{cid}/usage?from=2026-03-16&to=2026-03-16",
        headers=auth_headers,
    )
    assert r.status_code == 200
    records = r.json()["records"]
    assert len(records) == 1
    assert records[0]["date"] == "2026-03-16"


def test_usage_summary_daily(client, auth_headers):
    """Summary includes daily breakdown."""
    r = client.post("/api/companies", json={"name": "Daily Test"}, headers=auth_headers)
    cid = r.json()["company"]["id"]
    secret = {"x-usage-secret": "dev-usage-secret"}

    client.post(f"/api/companies/{cid}/usage", json={
        "date": "2026-03-15", "input_tokens": 100, "output_tokens": 50,
    }, headers=secret)
    client.post(f"/api/companies/{cid}/usage", json={
        "date": "2026-03-15", "input_tokens": 200, "output_tokens": 100,
        "model": "claude-sonnet-4-20250514",
    }, headers=secret)

    r = client.get(f"/api/companies/{cid}/usage", headers=auth_headers)
    summary = r.json()["summary"]

    # Total should be aggregated
    assert summary["total_tokens"] == 450

    # Daily breakdown
    assert len(summary["daily"]) == 1
    assert summary["daily"][0]["total_tokens"] == 450

    # By model
    assert len(summary["by_model"]) == 1
    assert summary["by_model"][0]["model"] == "claude-sonnet-4-20250514"


def test_usage_unauthorized_without_secret(client, auth_headers):
    """POST usage without secret is rejected."""
    r = client.post("/api/companies", json={"name": "Secret Test"}, headers=auth_headers)
    cid = r.json()["company"]["id"]

    r = client.post(f"/api/companies/{cid}/usage", json={
        "date": "2026-03-17", "input_tokens": 100, "output_tokens": 50,
    })
    assert r.status_code == 401


def test_usage_wrong_secret(client, auth_headers):
    """POST usage with wrong secret is rejected."""
    r = client.post("/api/companies", json={"name": "Wrong Secret"}, headers=auth_headers)
    cid = r.json()["company"]["id"]

    r = client.post(
        f"/api/companies/{cid}/usage",
        json={"date": "2026-03-17", "input_tokens": 100, "output_tokens": 50},
        headers={"x-usage-secret": "wrong-secret"},
    )
    assert r.status_code == 401


def test_usage_requires_date(client, auth_headers):
    """POST usage without date returns 400."""
    r = client.post("/api/companies", json={"name": "Date Test"}, headers=auth_headers)
    cid = r.json()["company"]["id"]

    r = client.post(
        f"/api/companies/{cid}/usage",
        json={"input_tokens": 100},
        headers={"x-usage-secret": "dev-usage-secret"},
    )
    assert r.status_code == 400


def test_billing_endpoint(client, auth_headers):
    """GET billing returns plan info and usage summary."""
    r = client.post("/api/companies", json={"name": "Billing Test"}, headers=auth_headers)
    cid = r.json()["company"]["id"]

    r = client.get(f"/api/companies/{cid}/billing", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["plan"]["name"] == "Free Beta"
    assert data["plan"]["price_monthly"] == 0
    assert "features" in data["plan"]
    assert data["stripe_enabled"] is False
    assert data["usage_summary"]["total_tokens"] == 0


def test_plans_endpoint(client):
    """GET /api/plans lists available plans."""
    r = client.get("/api/plans")
    assert r.status_code == 200
    plans = r.json()["plans"]
    assert "free_beta" in plans
    assert "starter" in plans
    assert "pro" in plans


def test_usage_empty_company(client, auth_headers):
    """GET usage for company with no usage returns empty data."""
    r = client.post("/api/companies", json={"name": "Empty"}, headers=auth_headers)
    cid = r.json()["company"]["id"]

    r = client.get(f"/api/companies/{cid}/usage", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["total_tokens"] == 0
    assert data["records"] == []
