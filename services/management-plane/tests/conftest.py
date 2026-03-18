"""Test fixtures for Management Plane tests."""

import os
import tempfile

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Use a temp database for each test."""
    db_path = str(tmp_path / "test.db")
    os.environ["MGMT_DB_PATH"] = db_path
    # Reset the global db connection
    import management.db as db_mod
    db_mod._db = None
    db_mod.DB_PATH = db_path
    yield db_path
    # Cleanup
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(db_mod.close_db())
    except RuntimeError:
        pass


@pytest.fixture
def client():
    """Create a test client for the app."""
    from management.app import create_app
    app = create_app()
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Register a test user and return auth headers."""
    resp = client.post("/api/auth/register", json={
        "email": "test@example.com",
        "password": "testpassword123",
        "name": "Test User",
    })
    assert resp.status_code == 201
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
