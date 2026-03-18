"""Tests for auth API endpoints."""


def test_register(client):
    resp = client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "password123",
        "name": "Alice",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "token" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["name"] == "Alice"


def test_register_duplicate_email(client):
    client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "password123",
    })
    resp = client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "password456",
    })
    assert resp.status_code == 409


def test_register_invalid_email(client):
    resp = client.post("/api/auth/register", json={
        "email": "not-an-email",
        "password": "password123",
    })
    assert resp.status_code == 400


def test_register_short_password(client):
    resp = client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "short",
    })
    assert resp.status_code == 400


def test_login(client):
    client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "password123",
    })
    resp = client.post("/api/auth/login", json={
        "email": "alice@example.com",
        "password": "password123",
    })
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "password123",
    })
    resp = client.post("/api/auth/login", json={
        "email": "alice@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_login_nonexistent_email(client):
    resp = client.post("/api/auth/login", json={
        "email": "nobody@example.com",
        "password": "password123",
    })
    assert resp.status_code == 401


def test_me(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "test@example.com"


def test_me_unauthenticated(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
