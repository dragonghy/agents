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

from agents_mcp.adapters.base import RenderedMessage, RunResult
from agents_mcp.web.orchestration_api import create_orchestration_router


# ── Fakes ──────────────────────────────────────────────────────────────────


class _FakeStore:
    """Records calls; returns canned data."""

    def __init__(self):
        self.profiles: list[dict] = []
        self.profile_lookup: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.list_calls = 0
        self.get_calls: list[str] = []
        self.paginated_response: tuple[list[dict], int] = ([], 0)
        self.paginated_calls: list[dict] = []
        self.by_profile_response: list[dict] = []
        self.by_ticket_response: list[dict] = []
        self.totals_response: dict = {
            "today": {"tokens_in": 0, "tokens_out": 0, "sessions_count": 0},
            "week": {"tokens_in": 0, "tokens_out": 0, "sessions_count": 0},
            "lifetime": {"tokens_in": 0, "tokens_out": 0, "sessions_count": 0},
        }

    async def list_profile_registry(self) -> list[dict]:
        self.list_calls += 1
        return list(self.profiles)

    async def get_profile_registry(self, name: str):
        return self.profile_lookup.get(name)

    async def get_session(self, session_id: str):
        self.get_calls.append(session_id)
        return self.sessions.get(session_id)

    async def list_sessions_paginated(
        self,
        status=None,
        profile_name=None,
        ticket_id=None,
        limit=50,
        offset=0,
    ):
        self.paginated_calls.append(
            {
                "status": status,
                "profile_name": profile_name,
                "ticket_id": ticket_id,
                "limit": limit,
                "offset": offset,
            }
        )
        if status is not None and status not in ("active", "closed"):
            raise ValueError(f"invalid status: {status!r}")
        return self.paginated_response

    async def cost_by_profile(self):
        return list(self.by_profile_response)

    async def cost_by_ticket(self):
        return list(self.by_ticket_response)

    async def cost_totals(self):
        return dict(self.totals_response)


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


# ── GET /profiles/{name} + /profiles/{name}/sessions (Task #18 Part C) ────


class TestProfileDetail:
    def test_unknown_404(self, harness):
        client, _, _ = harness
        r = client.get("/api/v1/orchestration/profiles/bogus")
        assert r.status_code == 404

    def test_returns_registry_only_when_dir_unknown(self, harness):
        client, store, _ = harness
        store.profile_lookup["secretary"] = {
            "name": "secretary",
            "description": "front door",
            "runner_type": "claude-sonnet-4.7",
            "file_path": "/no/such/path/profile.md",
            "file_hash": "abc",
            "loaded_at": "t",
            "last_used_at": None,
        }
        r = client.get("/api/v1/orchestration/profiles/secretary")
        assert r.status_code == 200
        body = r.json()
        assert body["registry"]["name"] == "secretary"
        # File doesn't exist on disk → profile is null but registry is preserved.
        assert body["profile"] is None

    def test_returns_full_profile_with_real_dir(self, harness, tmp_path):
        client, store, _ = harness
        # Build a synthetic profile.md
        pdir = tmp_path / "profiles" / "test_profile"
        pdir.mkdir(parents=True)
        (pdir / "profile.md").write_text(
            "---\n"
            "name: test_profile\n"
            "description: A test profile\n"
            "runner_type: claude-sonnet-4.7\n"
            "---\n"
            "You are a test agent.\n"
        )
        # Re-mount the router with profiles_dir argument.
        from agents_mcp.web.orchestration_api import create_orchestration_router

        store.profile_lookup["test_profile"] = {
            "name": "test_profile",
            "description": "A test profile",
            "runner_type": "claude-sonnet-4.7",
            "file_path": str(pdir / "profile.md"),
            "file_hash": "irrelevant",
            "loaded_at": "t",
            "last_used_at": None,
        }
        routes = create_orchestration_router(store, _FakeSessionManager(), tmp_path / "profiles")
        from starlette.applications import Starlette
        from starlette.routing import Mount, Router
        from starlette.testclient import TestClient as _TC

        app = Starlette(routes=[Mount("/api/v1/orchestration", app=Router(routes=routes))])
        c = _TC(app)
        r = c.get("/api/v1/orchestration/profiles/test_profile")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["registry"]["name"] == "test_profile"
        assert body["profile"] is not None
        assert body["profile"]["name"] == "test_profile"
        assert body["profile"]["runner_type"] == "claude-sonnet-4.7"
        assert "You are a test agent" in body["profile"]["system_prompt"]


class TestProfileSessions:
    def test_default_limit(self, harness):
        client, store, _ = harness
        store.paginated_response = (
            [
                {"id": "s1", "profile_name": "secretary"},
                {"id": "s2", "profile_name": "secretary"},
            ],
            2,
        )
        r = client.get("/api/v1/orchestration/profiles/secretary/sessions")
        assert r.status_code == 200
        body = r.json()
        assert body["profile_name"] == "secretary"
        assert body["total"] == 2
        # Verify the store call passed profile_name=secretary, limit=10.
        assert store.paginated_calls[0]["profile_name"] == "secretary"
        assert store.paginated_calls[0]["limit"] == 10

    def test_custom_limit(self, harness):
        client, store, _ = harness
        client.get("/api/v1/orchestration/profiles/tpm/sessions?limit=5")
        assert store.paginated_calls[0]["limit"] == 5

    def test_limit_capped(self, harness):
        client, store, _ = harness
        client.get("/api/v1/orchestration/profiles/tpm/sessions?limit=9999")
        assert store.paginated_calls[0]["limit"] == 100

    def test_invalid_limit_400(self, harness):
        client, _, _ = harness
        r = client.get("/api/v1/orchestration/profiles/tpm/sessions?limit=abc")
        assert r.status_code == 400


# ── GET /sessions (list) + /sessions/{id}/history (Task #18 Part B) ───────


class TestListSessions:
    def test_empty(self, harness):
        client, store, _ = harness
        store.paginated_response = ([], 0)
        r = client.get("/api/v1/orchestration/sessions")
        assert r.status_code == 200
        assert r.json() == {
            "sessions": [],
            "total": 0,
            "limit": 50,
            "offset": 0,
        }

    def test_with_filters(self, harness):
        client, store, _ = harness
        client.get(
            "/api/v1/orchestration/sessions"
            "?status=closed&profile=tpm&ticket=42&limit=20&offset=10"
        )
        assert store.paginated_calls[0] == {
            "status": "closed",
            "profile_name": "tpm",
            "ticket_id": 42,
            "limit": 20,
            "offset": 10,
        }

    def test_invalid_ticket_400(self, harness):
        client, _, _ = harness
        r = client.get("/api/v1/orchestration/sessions?ticket=abc")
        assert r.status_code == 400


class TestSessionHistory:
    def test_unknown_session_404(self, harness):
        client, _, _ = harness
        r = client.get("/api/v1/orchestration/sessions/sess_nope/history")
        assert r.status_code == 404

    def test_happy_path(self, harness, monkeypatch):
        client, store, _ = harness
        store.sessions["sess_x"] = {
            "id": "sess_x",
            "runner_type": "claude-sonnet-4.7",
        }

        class _FakeAdapter:
            async def render_history(self, sid, s):
                assert sid == "sess_x"
                return [
                    RenderedMessage(role="user", text="hi", timestamp="t0"),
                    RenderedMessage(role="assistant", text="yo", timestamp="t1"),
                ]

        from agents_mcp.web import orchestration_api

        monkeypatch.setattr(
            "agents_mcp.adapters.get_adapter",
            lambda rt: _FakeAdapter(),
        )
        # Also patch on adapters module direct reference so the late
        # import inside the route resolves to our fake.
        import agents_mcp.adapters as adapters_pkg

        monkeypatch.setattr(adapters_pkg, "get_adapter", lambda rt: _FakeAdapter())

        r = client.get("/api/v1/orchestration/sessions/sess_x/history")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert body["messages"][0] == {"role": "user", "text": "hi", "timestamp": "t0"}
        assert body["messages"][1] == {"role": "assistant", "text": "yo", "timestamp": "t1"}

    def test_unknown_runner_type_400(self, harness, monkeypatch):
        client, store, _ = harness
        store.sessions["sess_x"] = {
            "id": "sess_x",
            "runner_type": "alien-runner",
        }

        def _bad_get_adapter(rt):
            raise ValueError(f"unknown: {rt}")

        import agents_mcp.adapters as adapters_pkg

        monkeypatch.setattr(adapters_pkg, "get_adapter", _bad_get_adapter)
        r = client.get("/api/v1/orchestration/sessions/sess_x/history")
        assert r.status_code == 400


# ── GET /cost/* (Task #18 Part A) ──────────────────────────────────────────


class TestCostBySession:
    def test_empty(self, harness):
        client, store, _ = harness
        store.paginated_response = ([], 0)
        r = client.get("/api/v1/orchestration/cost/by-session")
        assert r.status_code == 200
        body = r.json()
        assert body == {"sessions": [], "total": 0, "limit": 50, "offset": 0}
        assert store.paginated_calls == [
            {
                "status": None,
                "profile_name": None,
                "ticket_id": None,
                "limit": 50,
                "offset": 0,
            }
        ]

    def test_returns_rows_with_usd(self, harness):
        client, store, _ = harness
        store.paginated_response = (
            [
                {
                    "id": "sess_a",
                    "profile_name": "tpm",
                    "ticket_id": 100,
                    "channel_id": None,
                    "status": "active",
                    "cost_tokens_in": 1_000_000,
                    "cost_tokens_out": 500_000,
                    "created_at": "2026-05-03 10:00:00",
                },
            ],
            1,
        )
        r = client.get("/api/v1/orchestration/cost/by-session")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        row = body["sessions"][0]
        # 1M input * $3/M + 500K output * $15/M = $3 + $7.5 = $10.5
        assert row["cost_usd"] == 10.5

    def test_filters_passthrough(self, harness):
        client, store, _ = harness
        r = client.get(
            "/api/v1/orchestration/cost/by-session"
            "?status=active&profile=tpm&ticket=42&limit=10&offset=20"
        )
        assert r.status_code == 200
        assert store.paginated_calls[0] == {
            "status": "active",
            "profile_name": "tpm",
            "ticket_id": 42,
            "limit": 10,
            "offset": 20,
        }

    def test_invalid_ticket_400(self, harness):
        client, _, _ = harness
        r = client.get("/api/v1/orchestration/cost/by-session?ticket=abc")
        assert r.status_code == 400

    def test_invalid_status_400(self, harness):
        client, _, _ = harness
        r = client.get("/api/v1/orchestration/cost/by-session?status=bogus")
        assert r.status_code == 400

    def test_limit_capped(self, harness):
        client, store, _ = harness
        client.get("/api/v1/orchestration/cost/by-session?limit=9999")
        assert store.paginated_calls[0]["limit"] == 500


class TestCostByProfile:
    def test_empty(self, harness):
        client, store, _ = harness
        store.by_profile_response = []
        r = client.get("/api/v1/orchestration/cost/by-profile")
        assert r.status_code == 200
        assert r.json() == {"rollup": [], "total": 0}

    def test_with_rows(self, harness):
        client, store, _ = harness
        store.by_profile_response = [
            {
                "profile_name": "tpm",
                "sessions_count": 3,
                "total_tokens_in": 2_000_000,
                "total_tokens_out": 1_000_000,
                "last_used_at": "2026-05-03 10:00:00",
            }
        ]
        r = client.get("/api/v1/orchestration/cost/by-profile")
        body = r.json()
        assert body["total"] == 1
        # 2M*3 + 1M*15 = 6 + 15 = 21
        assert body["rollup"][0]["total_usd"] == 21.0


class TestCostByTicket:
    def test_empty(self, harness):
        client, store, _ = harness
        store.by_ticket_response = []
        r = client.get("/api/v1/orchestration/cost/by-ticket")
        assert r.status_code == 200
        assert r.json() == {"rollup": [], "total": 0}

    def test_with_rows(self, harness):
        client, store, _ = harness
        store.by_ticket_response = [
            {
                "ticket_id": 18,
                "sessions_count": 2,
                "total_tokens_in": 100_000,
                "total_tokens_out": 50_000,
                "last_used_at": "2026-05-03 10:00:00",
            }
        ]
        r = client.get("/api/v1/orchestration/cost/by-ticket")
        body = r.json()
        assert body["total"] == 1
        # 100K*3 + 50K*15 = $0.3 + $0.75 = $1.05
        assert body["rollup"][0]["total_usd"] == 1.05


class TestCostTotals:
    def test_empty(self, harness):
        client, _, _ = harness
        r = client.get("/api/v1/orchestration/cost/totals")
        assert r.status_code == 200
        body = r.json()
        assert "today" in body
        assert "week" in body
        assert "lifetime" in body
        assert "pricing" in body
        for bucket in ("today", "week", "lifetime"):
            assert body[bucket] == {
                "tokens_in": 0,
                "tokens_out": 0,
                "sessions_count": 0,
                "usd": 0.0,
            }

    def test_with_data(self, harness):
        client, store, _ = harness
        store.totals_response = {
            "today": {"tokens_in": 1_000_000, "tokens_out": 0, "sessions_count": 5},
            "week": {"tokens_in": 5_000_000, "tokens_out": 100_000, "sessions_count": 20},
            "lifetime": {"tokens_in": 10_000_000, "tokens_out": 200_000, "sessions_count": 100},
        }
        r = client.get("/api/v1/orchestration/cost/totals")
        body = r.json()
        # 1M * 3 = $3
        assert body["today"]["usd"] == 3.0
        # 5M * 3 + 100K * 15 = 15 + 1.5 = 16.5
        assert body["week"]["usd"] == 16.5
        # 10M * 3 + 200K * 15 = 30 + 3 = 33
        assert body["lifetime"]["usd"] == 33.0
        assert body["pricing"]["input_per_million"] == 3.0
        assert body["pricing"]["output_per_million"] == 15.0


# Make pyflakes happy — Any imported for typing comments only.
_ = Any
