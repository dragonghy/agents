"""Tests for company CRUD and instance lifecycle API."""

import os

# Ensure mock mode is on for tests
os.environ["MGMT_MOCK_MODE"] = "true"


def test_create_company(client, auth_headers):
    resp = client.post("/api/companies", json={
        "name": "My Startup",
        "template": "standard",
        "auth_type": "oauth_token",
        "auth_token": "sk-test-token",
    }, headers=auth_headers)
    assert resp.status_code == 201
    company = resp.json()["company"]
    assert company["name"] == "My Startup"
    assert company["slug"] == "my-startup"
    assert company["status"] == "running"  # Auto-deployed in mock mode
    assert company["template"] == "standard"
    # auth_token should NOT be exposed
    assert "auth_token" not in company


def test_create_company_unauthenticated(client):
    resp = client.post("/api/companies", json={"name": "Test"})
    assert resp.status_code == 401


def test_create_company_no_name(client, auth_headers):
    resp = client.post("/api/companies", json={
        "template": "standard",
    }, headers=auth_headers)
    assert resp.status_code == 400


def test_create_company_invalid_template(client, auth_headers):
    resp = client.post("/api/companies", json={
        "name": "Test",
        "template": "invalid",
    }, headers=auth_headers)
    assert resp.status_code == 400


def test_list_companies(client, auth_headers):
    # Create two companies
    client.post("/api/companies", json={"name": "Company A"}, headers=auth_headers)
    client.post("/api/companies", json={"name": "Company B"}, headers=auth_headers)

    resp = client.get("/api/companies", headers=auth_headers)
    assert resp.status_code == 200
    companies = resp.json()["companies"]
    assert len(companies) == 2


def test_list_companies_empty(client, auth_headers):
    resp = client.get("/api/companies", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["companies"] == []


def test_get_company(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "Test Co",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]

    resp = client.get(f"/api/companies/{company_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["company"]["name"] == "Test Co"


def test_get_company_not_found(client, auth_headers):
    resp = client.get("/api/companies/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404


def test_update_company(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "Old Name",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]

    resp = client.patch(f"/api/companies/{company_id}", json={
        "name": "New Name",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["company"]["name"] == "New Name"


def test_delete_company(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "To Delete",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]

    resp = client.delete(f"/api/companies/{company_id}", headers=auth_headers)
    assert resp.status_code == 200

    # Should not appear in list
    list_resp = client.get("/api/companies", headers=auth_headers)
    assert len(list_resp.json()["companies"]) == 0


def test_stop_and_start(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "Lifecycle Test",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]
    assert create_resp.json()["company"]["status"] == "running"

    # Stop
    stop_resp = client.post(f"/api/companies/{company_id}/stop", headers=auth_headers)
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"] == "stopped"

    # Start
    start_resp = client.post(f"/api/companies/{company_id}/start", headers=auth_headers)
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "running"


def test_pause_and_resume(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "Pause Test",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]

    # Pause
    resp = client.post(f"/api/companies/{company_id}/pause", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"

    # Resume
    resp = client.post(f"/api/companies/{company_id}/resume", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_instance_status(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "Status Test",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]

    resp = client.get(f"/api/companies/{company_id}/status", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    assert resp.json()["mock_mode"] is True


def test_instance_logs(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "Logs Test",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]

    resp = client.get(f"/api/companies/{company_id}/logs", headers=auth_headers)
    assert resp.status_code == 200
    events = resp.json()["events"]
    # Should have at least "created" and "started" events
    event_types = [e["event_type"] for e in events]
    assert "created" in event_types
    assert "started" in event_types


def test_update_auth(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "Auth Test",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]

    resp = client.put(f"/api/companies/{company_id}/auth", json={
        "auth_type": "api_key",
        "auth_token": "sk-ant-test-key",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["company"]["auth_type"] == "api_key"


def test_auth_status(client, auth_headers):
    create_resp = client.post("/api/companies", json={
        "name": "Auth Status Test",
        "auth_type": "oauth_token",
        "auth_token": "sk-test",
    }, headers=auth_headers)
    company_id = create_resp.json()["company"]["id"]

    resp = client.get(f"/api/companies/{company_id}/auth/status", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["configured"] is True
    assert resp.json()["auth_type"] == "oauth_token"


def test_slug_uniqueness(client, auth_headers):
    """Two companies with the same name should get unique slugs."""
    r1 = client.post("/api/companies", json={"name": "Test Co"}, headers=auth_headers)
    r2 = client.post("/api/companies", json={"name": "Test Co"}, headers=auth_headers)
    slug1 = r1.json()["company"]["slug"]
    slug2 = r2.json()["company"]["slug"]
    assert slug1 != slug2


def test_cross_user_isolation(client):
    """Users cannot see each other's companies."""
    # Register user A
    r1 = client.post("/api/auth/register", json={
        "email": "a@example.com", "password": "password123",
    })
    headers_a = {"Authorization": f"Bearer {r1.json()['token']}"}

    # Register user B
    r2 = client.post("/api/auth/register", json={
        "email": "b@example.com", "password": "password123",
    })
    headers_b = {"Authorization": f"Bearer {r2.json()['token']}"}

    # User A creates a company
    cr = client.post("/api/companies", json={"name": "A's Company"}, headers=headers_a)
    company_id = cr.json()["company"]["id"]

    # User B cannot see it
    resp = client.get(f"/api/companies/{company_id}", headers=headers_b)
    assert resp.status_code == 404

    # User B's list is empty
    list_resp = client.get("/api/companies", headers=headers_b)
    assert len(list_resp.json()["companies"]) == 0
