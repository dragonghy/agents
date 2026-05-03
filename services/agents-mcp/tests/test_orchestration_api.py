"""Tests for the orchestration v1 REST API (Task #17 — MVTH backend).

Hermetic: builds a Starlette app from
``create_orchestration_router(mock_store, mock_session_manager)`` and
drives it with :class:`starlette.testclient.TestClient`. Both
collaborators are simple ``unittest.mock.MagicMock`` instances with
async-method shims; no real LLM, no real SQLite.

The five endpoints under test:

- ``GET  /profiles``
- ``POST /sessions``
- ``POST /sessions/{id}/messages``
- ``POST /sessions/{id}/close``
- ``GET  /sessions/{id}``

Each endpoint gets coverage on the happy path plus the most likely
failure modes (404 on missing session, 400 on missing required body
fields, 400 on bad JSON, 400 on validation errors raised by the
SessionManager).
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount, Router
from starlette.testclient import TestClient

from agents_mcp.adapters.base import RunResult
from agents_mcp.web.orchestration_api import create_orchestration_router


# ── Fakes ──────────────────────────────────────────────────────────────────


class _FakeStore:
    """Records calls; returns canned data."""

    def __init__(self):
        self.profiles: list[dict] = []
        self.sessions: dict[str, dict] = {}
        self.list_calls = 0
        self.get_calls: list[str] = []

    async def list_profile_registry(self) -> list[dict]:
        self.list_calls += 1
        return list(self.profiles)

    async def get_session(self, session_id: str):
        self.get_calls.append(session_id)
        return self.sessions.get(session_id)


class _FakeSessionManager:
    """Mirrors the SessionManager surface the router uses."""

    def __init__(self):
        self.spawn_calls: list[dict] = []
        self.append_calls: list[tuple[str, str]] = []
        self.close_calls: list[str] = []
        self.spawn_result: dict | None = None
        self.spawn_error: BaseException | None = None
        self.append_result: RunResult | None = None
        self.append_error: BaseException | None = None
        self.close_result: bool = True

    async def spawn(
        self,
        *,
        profile_name: str,
        binding_kind: str,
        ticket_id: int | None = None,
        channel_id: str | None = None,
        parent_session_id: str | None = None,
    ) -> dict:
        self.spawn_calls.append(
            {
                "profile_name": profile_name,
                "binding_kind": binding_kind,
                "ticket_id": ticket_id,
                "channel_id": channel_id,
                "parent_session_id": parent_session_id,
            }
        )
        if self.spawn_error is not None:
            raise self.spawn_error
        return self.spawn_result or {
            "id": "sess_fake",
            "profile_name": profile_name,
            "binding_kind": binding_kind,
            "ticket_id": ticket_id,
            "channel_id": channel_id,
            "parent_session_id": parent_session_id,
            "status": "active",
            "runner_type": "claude-sonnet-4.6",
            "native_handle": None,
            "cost_tokens_in": 0,
            "cost_tokens_out": 0,
        }

    async def append_message(self, session_id: str, text: str) -> RunResult:
        self.append_calls.append((session_id, text))
        if self.append_error is not None:
            raise self.append_error
        return self.append_result or RunResult(
            assistant_text="canned reply",
            tokens_in=12,
            tokens_out=7,
            native_handle="native-1",
        )

    async def close(self, session_id: str) -> bool:
        self.close_calls.append(session_id)
        return self.close_result


# ── App fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def harness():
    """Spin up a Starlette app with the orchestration router mounted."""
    store = _FakeStore()
    mgr = _FakeSessionManager()
    routes = create_orchestration_router(store, mgr)
    app = Starlette(routes=[Mount("/api/v1/orchestration", app=Router(routes=routes))])
    client = TestClient(app)
    return client, store, mgr


# ── GET /profiles ──────────────────────────────────────────────────────────


class TestListProfiles:
    def test_empty(self, harness):
        client, store, _ = harness
        store.profiles = []
        r = client.get("/api/v1/orchestration/profiles")
        assert r.status_code == 200
        body = r.json()
        assert body == {"profiles": [], "total": 0}
        assert store.list_calls == 1

    def test_populated(self, harness):
        client, store, _ = harness
        store.profiles = [
            {
                "name": "secretary",
                "description": "front door",
                "runner_type": "claude-sonnet-4.6",
                "file_path": "/profiles/secretary/profile.md",
                "file_hash": "abc",
                "loaded_at": "2026-05-02 12:00:00",
                "last_used_at": None,
            },
            {
                "name": "tpm",
                "description": "ticket coordinator",
                "runner_type": "claude-sonnet-4.6",
                "file_path": "/profiles/tpm/profile.md",
                "file_hash": "def",
                "loaded_at": "2026-05-02 12:00:00",
                "last_used_at": "2026-05-02 13:00:00",
            },
        ]
        r = client.get("/api/v1/orchestration/profiles")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        names = [p["name"] for p in body["profiles"]]
        assert names == ["secretary", "tpm"]


# ── POST /sessions ─────────────────────────────────────────────────────────


class TestSpawnSession:
    def test_minimal_happy_path(self, harness):
        client, _, mgr = harness
        r = client.post(
            "/api/v1/orchestration/sessions",
            json={"profile_name": "secretary", "binding_kind": "standalone"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["profile_name"] == "secretary"
        assert body["binding_kind"] == "standalone"
        assert body["status"] == "active"
        assert mgr.spawn_calls == [
            {
                "profile_name": "secretary",
                "binding_kind": "standalone",
                "ticket_id": None,
                "channel_id": None,
                "parent_session_id": None,
            }
        ]

    def test_full_args(self, harness):
        client, _, mgr = harness
        r = client.post(
            "/api/v1/orchestration/sessions",
            json={
                "profile_name": "tpm",
                "binding_kind": "ticket-subagent",
                "ticket_id": 42,
                "channel_id": "telegram:1",
                "parent_session_id": "sess_parent",
            },
        )
        assert r.status_code == 201
        assert mgr.spawn_calls[0] == {
            "profile_name": "tpm",
            "binding_kind": "ticket-subagent",
            "ticket_id": 42,
            "channel_id": "telegram:1",
            "parent_session_id": "sess_parent",
        }

    def test_missing_profile_name(self, harness):
        client, _, mgr = harness
        r = client.post(
            "/api/v1/orchestration/sessions",
            json={"binding_kind": "standalone"},
        )
        assert r.status_code == 400
        assert "profile_name" in r.json()["error"]
        assert mgr.spawn_calls == []

    def test_missing_binding_kind(self, harness):
        client, _, mgr = harness
        r = client.post(
            "/api/v1/orchestration/sessions",
            json={"profile_name": "secretary"},
        )
        assert r.status_code == 400
        assert "binding_kind" in r.json()["error"]
        assert mgr.spawn_calls == []

    def test_invalid_json(self, harness):
        client, _, _ = harness
        r = client.post(
            "/api/v1/orchestration/sessions",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 400

    def test_unknown_profile_404(self, harness):
        client, _, mgr = harness
        mgr.spawn_error = FileNotFoundError("profiles/bogus/profile.md")
        r = client.post(
            "/api/v1/orchestration/sessions",
            json={"profile_name": "bogus", "binding_kind": "standalone"},
        )
        assert r.status_code == 404
        assert "bogus" in r.json()["error"]

    def test_invalid_binding_kind_400(self, harness):
        client, _, mgr = harness
        mgr.spawn_error = ValueError(
            "binding_kind must be one of [...], got 'foo'"
        )
        r = client.post(
            "/api/v1/orchestration/sessions",
            json={"profile_name": "secretary", "binding_kind": "foo"},
        )
        assert r.status_code == 400
        assert "binding_kind" in r.json()["error"]

    def test_ticket_id_must_be_int(self, harness):
        client, _, mgr = harness
        r = client.post(
            "/api/v1/orchestration/sessions",
            json={
                "profile_name": "tpm",
                "binding_kind": "ticket-subagent",
                "ticket_id": "not-a-number",
            },
        )
        assert r.status_code == 400
        assert mgr.spawn_calls == []


# ── POST /sessions/{id}/messages ───────────────────────────────────────────


class TestAppendMessage:
    def test_happy_path(self, harness):
        client, _, mgr = harness
        mgr.append_result = RunResult(
            assistant_text="hello, I am secretary",
            tokens_in=42,
            tokens_out=11,
            native_handle="native-xyz",
        )
        r = client.post(
            "/api/v1/orchestration/sessions/sess_abc/messages",
            json={"text": "hi there"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {
            "assistant_text": "hello, I am secretary",
            "tokens_in": 42,
            "tokens_out": 11,
            "native_handle": "native-xyz",
        }
        assert mgr.append_calls == [("sess_abc", "hi there")]

    def test_missing_text(self, harness):
        client, _, mgr = harness
        r = client.post(
            "/api/v1/orchestration/sessions/sess_abc/messages",
            json={},
        )
        assert r.status_code == 400
        assert "text" in r.json()["error"]
        assert mgr.append_calls == []

    def test_empty_text(self, harness):
        client, _, mgr = harness
        r = client.post(
            "/api/v1/orchestration/sessions/sess_abc/messages",
            json={"text": ""},
        )
        assert r.status_code == 400
        assert mgr.append_calls == []

    def test_unknown_session_404(self, harness):
        client, _, mgr = harness
        mgr.append_error = LookupError("unknown session id: 'sess_bogus'")
        r = client.post(
            "/api/v1/orchestration/sessions/sess_bogus/messages",
            json={"text": "hi"},
        )
        assert r.status_code == 404

    def test_closed_session_400(self, harness):
        client, _, mgr = harness
        mgr.append_error = RuntimeError(
            "session 'sess_abc' is closed; cannot append messages"
        )
        r = client.post(
            "/api/v1/orchestration/sessions/sess_abc/messages",
            json={"text": "hi"},
        )
        assert r.status_code == 400
        assert "closed" in r.json()["error"]

    def test_invalid_json(self, harness):
        client, _, _ = harness
        r = client.post(
            "/api/v1/orchestration/sessions/sess_abc/messages",
            content=b"{",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 400


# ── POST /sessions/{id}/close ──────────────────────────────────────────────


class TestCloseSession:
    def test_happy_path(self, harness):
        client, store, mgr = harness
        store.sessions["sess_abc"] = {"id": "sess_abc", "status": "active"}
        mgr.close_result = True
        r = client.post("/api/v1/orchestration/sessions/sess_abc/close")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert mgr.close_calls == ["sess_abc"]

    def test_already_closed_returns_false(self, harness):
        client, store, mgr = harness
        store.sessions["sess_abc"] = {"id": "sess_abc", "status": "closed"}
        mgr.close_result = False
        r = client.post("/api/v1/orchestration/sessions/sess_abc/close")
        assert r.status_code == 200
        assert r.json() == {"ok": False}

    def test_unknown_session_404(self, harness):
        client, _, mgr = harness
        r = client.post("/api/v1/orchestration/sessions/sess_nope/close")
        assert r.status_code == 404
        assert mgr.close_calls == []


# ── GET /sessions/{id} ─────────────────────────────────────────────────────


class TestGetSession:
    def test_happy_path(self, harness):
        client, store, _ = harness
        store.sessions["sess_abc"] = {
            "id": "sess_abc",
            "profile_name": "secretary",
            "status": "active",
            "binding_kind": "standalone",
            "runner_type": "claude-sonnet-4.6",
            "native_handle": "native-xyz",
            "cost_tokens_in": 100,
            "cost_tokens_out": 50,
        }
        r = client.get("/api/v1/orchestration/sessions/sess_abc")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "sess_abc"
        assert body["profile_name"] == "secretary"
        assert body["cost_tokens_in"] == 100

    def test_unknown_session_404(self, harness):
        client, _, _ = harness
        r = client.get("/api/v1/orchestration/sessions/sess_nope")
        assert r.status_code == 404
        assert "not found" in r.json()["error"]


# ── _resolve helper accepts callables (server.py uses this path) ───────────


class TestCallableInjection:
    """The router accepts either live objects or zero-arg async getters."""

    def test_async_getter_used_for_store(self):
        store = _FakeStore()
        store.profiles = [{"name": "x", "runner_type": "y"}]
        mgr = _FakeSessionManager()

        async def store_getter():
            return store

        async def mgr_getter():
            return mgr

        routes = create_orchestration_router(store_getter, mgr_getter)
        app = Starlette(routes=[Mount("/api/v1/orchestration", app=Router(routes=routes))])
        client = TestClient(app)
        r = client.get("/api/v1/orchestration/profiles")
        assert r.status_code == 200
        assert r.json()["total"] == 1


# Make pyflakes happy — Any imported for typing comments only.
_ = Any
