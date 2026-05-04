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
        # Dependency DAG (Task #20).
        # depends_on_map[parent] = list of children parent depends on (parent → child).
        # dependents_map[child]  = list of parents that depend on this child.
        self.depends_on_map: dict[int, list[int]] = {}
        self.dependents_map: dict[int, list[int]] = {}

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
        channel_id=None,
        limit=50,
        offset=0,
    ):
        self.paginated_calls.append(
            {
                "status": status,
                "profile_name": profile_name,
                "ticket_id": ticket_id,
                "channel_id": channel_id,
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

    async def get_dependencies(self, ticket_id: int) -> list[int]:
        return list(self.depends_on_map.get(int(ticket_id), []))

    async def get_dependents(self, ticket_id: int) -> list[int]:
        return list(self.dependents_map.get(int(ticket_id), []))

    async def get_active_tpm_for_ticket(self, ticket_id: int):
        # Default: no active TPM. Tests that need one set this attribute.
        return getattr(self, "_active_tpm", None)

    async def close_session(self, session_id: str) -> bool:
        # Used by maybe_close_tpm_for_status_change.
        return True


class _FakeTaskClient:
    """Mirrors the slice of SQLiteTaskClient the ticket endpoints use."""

    def __init__(self):
        # ticket_id -> dict
        self.tickets: dict[int, dict] = {}
        self.workspaces: list[dict] = []
        # ticket_id -> [comment dict, ...]
        self.comments: dict[int, list[dict]] = {}
        self.update_calls: list[dict] = []
        self.update_error: BaseException | None = None
        self.list_error: BaseException | None = None
        # POST /tickets, POST /tickets/{id}/comments — call recorders.
        self.create_ticket_calls: list[dict] = []
        self.create_ticket_error: BaseException | None = None
        self.add_comment_calls: list[dict] = []
        self.add_comment_error: BaseException | None = None
        self._next_ticket_id: int = 1
        self._next_comment_id: int = 1

    async def list_workspaces(self, kind: str | None = None) -> list[dict]:
        if kind is None:
            return list(self.workspaces)
        return [w for w in self.workspaces if w.get("kind") == kind]

    async def get_ticket(self, ticket_id: int, prune: bool = True) -> dict:
        return dict(self.tickets.get(int(ticket_id), {}))

    async def list_tickets(
        self,
        project_id: int | None = None,
        status: str | None = None,
        workspace_id: int | None = None,
        limit: int = 200,
        offset: int = 0,
        ticket_type: str | None = None,
        **kwargs,
    ) -> dict:
        if self.list_error is not None:
            raise self.list_error
        rows = list(self.tickets.values())
        if workspace_id is not None:
            rows = [t for t in rows if t.get("workspace_id") == workspace_id]
        if project_id is not None:
            rows = [t for t in rows if t.get("projectId") == project_id]
        if ticket_type is not None:
            rows = [t for t in rows if t.get("type") == ticket_type]
        if status and status != "all":
            allowed = [int(s.strip()) for s in str(status).split(",")]
            rows = [t for t in rows if int(t.get("status") or 0) in allowed]
        total = len(rows)
        if offset:
            rows = rows[offset:]
        if limit and limit > 0:
            rows = rows[:limit]
        return {"tickets": rows, "total": total, "offset": offset, "limit": limit}

    async def get_comments(
        self, module: str, module_id: int, limit: int = 10, offset: int = 0
    ) -> dict:
        rows = list(self.comments.get(int(module_id), []))
        total = len(rows)
        if offset:
            rows = rows[offset:]
        if limit and limit > 0:
            rows = rows[:limit]
        return {"comments": rows, "total": total, "limit": limit, "offset": offset}

    async def update_ticket(self, ticket_id: int, **kwargs) -> bool:
        if self.update_error is not None:
            raise self.update_error
        self.update_calls.append({"ticket_id": int(ticket_id), **kwargs})
        if int(ticket_id) in self.tickets:
            self.tickets[int(ticket_id)].update(kwargs)
        return True

    async def create_ticket(
        self,
        headline: str,
        project_id: int | None = None,
        user_id: int = 1,
        tags: str | None = None,
        assignee: str | None = None,
        **kwargs,
    ) -> int:
        if self.create_ticket_error is not None:
            raise self.create_ticket_error
        # Auto-increment id, sidestepping any seeded ids in self.tickets.
        while self._next_ticket_id in self.tickets:
            self._next_ticket_id += 1
        new_id = self._next_ticket_id
        self._next_ticket_id += 1
        record = {
            "headline": headline,
            "project_id": project_id,
            "user_id": user_id,
            "tags": tags,
            "assignee": assignee,
            **kwargs,
        }
        self.create_ticket_calls.append(record)
        # Persist a row so the post-create get_ticket round-trip succeeds.
        self.tickets[new_id] = {
            "id": new_id,
            "headline": headline,
            "status": kwargs.get("status", 3),
            "type": "task",
            "priority": kwargs.get("priority", "medium"),
            "workspace_id": kwargs.get("workspace_id", 1),
            "projectId": project_id or 100,
            "tags": tags or "",
            "assignee": assignee or "",
            "phase": "",
            "date": "2026-05-03",
            "description": kwargs.get("description", ""),
            "dependingTicketId": kwargs.get("dependingTicketId"),
        }
        return new_id

    async def add_comment(
        self,
        module: str,
        module_id: int,
        comment: str,
        author: str | None = None,
    ) -> int:
        if self.add_comment_error is not None:
            raise self.add_comment_error
        new_id = self._next_comment_id
        self._next_comment_id += 1
        row = {
            "id": new_id,
            "text": comment,
            "userId": 1,
            "date": "2026-05-03 12:00:00",
            "moduleId": int(module_id),
            "author": author or "",
        }
        self.add_comment_calls.append(
            {
                "module": module,
                "module_id": int(module_id),
                "comment": comment,
                "author": author,
                "id": new_id,
            }
        )
        self.comments.setdefault(int(module_id), []).append(row)
        return new_id


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


@pytest.fixture
def ticket_harness():
    """Harness that includes a task_client for ticket endpoint tests."""
    store = _FakeStore()
    mgr = _FakeSessionManager()
    tc = _FakeTaskClient()
    routes = create_orchestration_router(store, mgr, task_client=tc)
    app = Starlette(routes=[Mount("/api/v1/orchestration", app=Router(routes=routes))])
    client = TestClient(app)
    return client, store, mgr, tc


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
            "channel_id": None,
            "limit": 20,
            "offset": 10,
        }

    def test_with_channel_filter(self, harness):
        """Channel adapters (Phase 4) filter by channel_id to find the
        active human-channel session for an inbound Telegram message."""
        client, store, _ = harness
        store.paginated_response = ([], 0)
        client.get(
            "/api/v1/orchestration/sessions"
            "?channel_id=telegram%3A12345&status=active"
        )
        assert store.paginated_calls[0]["channel_id"] == "telegram:12345"
        assert store.paginated_calls[0]["status"] == "active"

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
                "channel_id": None,
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
            "channel_id": None,
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


# ── Ticket endpoints (Task #20 — UI rework) ─────────────────────────────────


def _seed_workspaces(tc: _FakeTaskClient) -> None:
    tc.workspaces = [
        {"id": 1, "name": "Work", "kind": "work"},
        {"id": 2, "name": "Personal", "kind": "personal"},
    ]


def _make_ticket(
    tid: int,
    headline: str = "ticket",
    status: int = 4,
    workspace_id: int = 1,
    project_id: int | None = 100,
    ticket_type: str = "task",
    priority: str = "medium",
) -> dict:
    return {
        "id": tid,
        "headline": headline,
        "status": status,
        "type": ticket_type,
        "priority": priority,
        "workspace_id": workspace_id,
        "projectId": project_id,
        "tags": "",
        "assignee": "",
        "phase": "",
        "date": "2026-05-02",
    }


class TestListTickets:
    def test_no_task_client(self):
        # Build a router without a task_client to confirm 500.
        store = _FakeStore()
        mgr = _FakeSessionManager()
        routes = create_orchestration_router(store, mgr)  # no task_client
        app = Starlette(
            routes=[Mount("/api/v1/orchestration", app=Router(routes=routes))]
        )
        client = TestClient(app)
        r = client.get("/api/v1/orchestration/tickets")
        assert r.status_code == 500
        assert "task_client" in r.json()["error"]

    def test_empty(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        r = client.get("/api/v1/orchestration/tickets")
        assert r.status_code == 200
        body = r.json()
        assert body == {"tickets": [], "total": 0, "limit": 200, "offset": 0}

    def test_populated_with_workspace_resolution(self, ticket_harness):
        client, store, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {
            1: _make_ticket(1, "first", workspace_id=1),
            2: _make_ticket(2, "second", workspace_id=2),
        }
        # Wire up dependencies for ticket 1 only.
        store.depends_on_map = {1: [99]}
        store.dependents_map = {1: [50, 51]}
        r = client.get("/api/v1/orchestration/tickets")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        # Find each ticket and assert workspace resolution.
        by_id = {t["id"]: t for t in body["tickets"]}
        assert by_id[1]["workspace_name"] == "Work"
        assert by_id[2]["workspace_name"] == "Personal"
        assert by_id[1]["dependencies"] == {
            "depends_on_count": 1,
            "dependents_count": 2,
        }
        assert by_id[2]["dependencies"] == {
            "depends_on_count": 0,
            "dependents_count": 0,
        }

    def test_workspace_filter(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {
            1: _make_ticket(1, "first", workspace_id=1),
            2: _make_ticket(2, "second", workspace_id=2),
        }
        r = client.get("/api/v1/orchestration/tickets?workspace=2")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["tickets"][0]["id"] == 2

    def test_status_filter(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {
            1: _make_ticket(1, "wip", status=4),
            2: _make_ticket(2, "blocked", status=1),
            3: _make_ticket(3, "done", status=0),
        }
        r = client.get("/api/v1/orchestration/tickets?status=4,1")
        body = r.json()
        ids = sorted([t["id"] for t in body["tickets"]])
        assert ids == [1, 2]

    def test_invalid_workspace(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.get("/api/v1/orchestration/tickets?workspace=abc")
        assert r.status_code == 400


class TestGetTicket:
    def test_404(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.get("/api/v1/orchestration/tickets/999")
        assert r.status_code == 404

    def test_invalid_id(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.get("/api/v1/orchestration/tickets/not-a-number")
        assert r.status_code == 400

    def test_happy_path_with_dependencies(self, ticket_harness):
        client, store, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {
            10: _make_ticket(10, "main", project_id=100, workspace_id=1),
            20: _make_ticket(20, "child A", project_id=100),
            30: _make_ticket(30, "parent", project_id=100),
            100: _make_ticket(100, "Project Foo", ticket_type="project"),
        }
        store.depends_on_map = {10: [20]}  # 10 depends on 20
        store.dependents_map = {10: [30]}  # 30 depends on 10

        r = client.get("/api/v1/orchestration/tickets/10")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == 10
        assert body["workspace_name"] == "Work"
        assert body["project_name"] == "Project Foo"
        depends_on = body["dependencies"]["depends_on"]
        dependents = body["dependencies"]["dependents"]
        assert [d["id"] for d in depends_on] == [20]
        assert depends_on[0]["headline"] == "child A"
        assert [d["id"] for d in dependents] == [30]
        assert dependents[0]["headline"] == "parent"


class TestGetTicketComments:
    def test_empty(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.get("/api/v1/orchestration/tickets/42/comments")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["comments"] == []

    def test_populated(self, ticket_harness):
        client, _, _, tc = ticket_harness
        tc.comments = {
            42: [
                {"id": 1, "text": "first", "author": "alice", "date": "2026-05-02"},
                {"id": 2, "text": "second", "author": "bob", "date": "2026-05-02"},
            ]
        }
        r = client.get("/api/v1/orchestration/tickets/42/comments")
        body = r.json()
        assert body["total"] == 2
        assert [c["text"] for c in body["comments"]] == ["first", "second"]

    def test_invalid_id(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.get("/api/v1/orchestration/tickets/bad/comments")
        assert r.status_code == 400


class TestGetTicketSessions:
    def test_uses_paginated_list(self, ticket_harness):
        client, store, *_ = ticket_harness
        store.paginated_response = (
            [{"id": "sess_1", "ticket_id": 7, "profile_name": "tpm"}],
            1,
        )
        r = client.get("/api/v1/orchestration/tickets/7/sessions")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["ticket_id"] == 7
        assert store.paginated_calls[-1]["ticket_id"] == 7

    def test_invalid_id(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.get("/api/v1/orchestration/tickets/bad/sessions")
        assert r.status_code == 400


class TestPatchTicket:
    def test_empty_body(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.request(
            "PATCH",
            "/api/v1/orchestration/tickets/1",
            json={},
        )
        assert r.status_code == 400
        assert "no editable fields" in r.json()["error"]

    def test_status_update_no_change(self, ticket_harness):
        client, _, mgr, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {1: _make_ticket(1, status=4)}
        r = client.request(
            "PATCH",
            "/api/v1/orchestration/tickets/1",
            json={"status": 4},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        # No spawn — status didn't change.
        assert mgr.spawn_calls == []

    def test_status_3_to_4_fires_tpm_spawn(self, ticket_harness):
        client, _, mgr, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {1: _make_ticket(1, status=3)}
        r = client.request(
            "PATCH",
            "/api/v1/orchestration/tickets/1",
            json={"status": 4},
        )
        assert r.status_code == 200
        # The TPM spawn helper looks up active TPM via store; with empty
        # store it should attempt to spawn.
        assert any(
            c["profile_name"] == "tpm" and c["ticket_id"] == 1
            for c in mgr.spawn_calls
        )

    def test_priority_only(self, ticket_harness):
        client, _, mgr, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {1: _make_ticket(1)}
        r = client.request(
            "PATCH",
            "/api/v1/orchestration/tickets/1",
            json={"priority": "high"},
        )
        assert r.status_code == 200
        assert tc.update_calls[-1]["priority"] == "high"
        # No status change → no spawn.
        assert mgr.spawn_calls == []

    def test_invalid_status_type(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.request(
            "PATCH",
            "/api/v1/orchestration/tickets/1",
            json={"status": "active"},
        )
        assert r.status_code == 400

    def test_invalid_id(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.request(
            "PATCH",
            "/api/v1/orchestration/tickets/bad",
            json={"status": 4},
        )
        assert r.status_code == 400

    def test_update_failure_500(self, ticket_harness):
        client, _, _, tc = ticket_harness
        tc.update_error = RuntimeError("db locked")
        r = client.request(
            "PATCH",
            "/api/v1/orchestration/tickets/1",
            json={"status": 4},
        )
        assert r.status_code == 500


class TestCreateTicket:
    """POST /tickets — task #34 (dogfood-driven; see services/agents-mcp/PR #34)."""

    def test_minimal_happy_path(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        r = client.post(
            "/api/v1/orchestration/tickets",
            json={"headline": "ship rest endpoints"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # New id surfaced + headline echoed back via get_ticket round-trip.
        assert isinstance(body["id"], int)
        assert body["headline"] == "ship rest endpoints"
        assert tc.create_ticket_calls
        last = tc.create_ticket_calls[-1]
        assert last["headline"] == "ship rest endpoints"
        # No optional fields → no description / parent / etc.
        assert last["assignee"] is None
        assert last.get("dependingTicketId") is None

    def test_full_args_round_trip(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        # Seed an existing parent so the parent_id check passes.
        tc.tickets[100] = _make_ticket(100, "umbrella", status=4, project_id=100)
        r = client.post(
            "/api/v1/orchestration/tickets",
            json={
                "headline": "child task",
                "description": "the long form description",
                "assignee": "dev",
                "tags": ["needs-review", "infra"],
                "priority": "high",
                "parent_id": 100,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["headline"] == "child task"
        # Round-trip via GET to confirm persistence.
        get = client.get(f"/api/v1/orchestration/tickets/{body['id']}")
        assert get.status_code == 200
        got = get.json()
        assert got["headline"] == "child task"
        assert got["dependingTicketId"] == 100
        # tags list joined with commas, assignee passed through.
        last = tc.create_ticket_calls[-1]
        assert last["tags"] == "needs-review,infra"
        assert last["assignee"] == "dev"
        assert last["description"] == "the long form description"
        assert last["priority"] == "high"
        assert last["dependingTicketId"] == 100

    def test_priority_int_coerced_to_string(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        r = client.post(
            "/api/v1/orchestration/tickets",
            json={"headline": "x", "priority": 2},
        )
        assert r.status_code == 201
        assert tc.create_ticket_calls[-1]["priority"] == "2"

    def test_missing_headline_400(self, ticket_harness):
        client, _, _, tc = ticket_harness
        r = client.post(
            "/api/v1/orchestration/tickets",
            json={"description": "no headline here"},
        )
        assert r.status_code == 400
        assert "headline" in r.json()["error"]
        assert tc.create_ticket_calls == []

    def test_empty_headline_400(self, ticket_harness):
        client, _, _, tc = ticket_harness
        r = client.post(
            "/api/v1/orchestration/tickets",
            json={"headline": ""},
        )
        assert r.status_code == 400
        assert tc.create_ticket_calls == []

    def test_invalid_json_400(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.post(
            "/api/v1/orchestration/tickets",
            content=b"<not json>",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 400

    def test_unknown_parent_id_404(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        # No ticket #999 seeded → parent lookup yields {} → 404.
        r = client.post(
            "/api/v1/orchestration/tickets",
            json={"headline": "orphaned child", "parent_id": 999},
        )
        assert r.status_code == 404
        assert "999" in r.json()["error"]
        # Did NOT call create_ticket on the underlying client.
        assert tc.create_ticket_calls == []

    def test_invalid_tags_type_400(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.post(
            "/api/v1/orchestration/tickets",
            json={"headline": "x", "tags": 42},
        )
        assert r.status_code == 400

    def test_no_task_client_500(self):
        # Build a router without a task_client to confirm 500.
        store = _FakeStore()
        mgr = _FakeSessionManager()
        routes = create_orchestration_router(store, mgr)
        app = Starlette(
            routes=[Mount("/api/v1/orchestration", app=Router(routes=routes))]
        )
        client = TestClient(app)
        r = client.post(
            "/api/v1/orchestration/tickets",
            json={"headline": "x"},
        )
        assert r.status_code == 500


class TestCreateTicketComment:
    """POST /tickets/{id}/comments — task #34."""

    def test_happy_path(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets[5] = _make_ticket(5, "host ticket")
        r = client.post(
            "/api/v1/orchestration/tickets/5/comments",
            json={"body": "looks good to me", "author": "dev-alex"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["text"] == "looks good to me"
        assert body["author"] == "dev-alex"
        assert isinstance(body["id"], int)
        # Visible in subsequent GET.
        get = client.get("/api/v1/orchestration/tickets/5/comments")
        assert get.status_code == 200
        comments = get.json()["comments"]
        assert any(c["text"] == "looks good to me" for c in comments)

    def test_anonymous_author_ok(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets[5] = _make_ticket(5)
        r = client.post(
            "/api/v1/orchestration/tickets/5/comments",
            json={"body": "human comment, no author"},
        )
        assert r.status_code == 201
        # Author defaulted to "" downstream.
        assert tc.add_comment_calls[-1]["author"] is None

    def test_missing_body_400(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets[5] = _make_ticket(5)
        r = client.post(
            "/api/v1/orchestration/tickets/5/comments",
            json={"author": "qa-lucy"},
        )
        assert r.status_code == 400
        assert "body" in r.json()["error"]
        assert tc.add_comment_calls == []

    def test_empty_body_400(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets[5] = _make_ticket(5)
        r = client.post(
            "/api/v1/orchestration/tickets/5/comments",
            json={"body": ""},
        )
        assert r.status_code == 400
        assert tc.add_comment_calls == []

    def test_unknown_ticket_404(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        # No ticket #777 → 404 before insert.
        r = client.post(
            "/api/v1/orchestration/tickets/777/comments",
            json={"body": "nope"},
        )
        assert r.status_code == 404
        assert "777" in r.json()["error"]
        assert tc.add_comment_calls == []

    def test_invalid_id_400(self, ticket_harness):
        client, *_ = ticket_harness
        r = client.post(
            "/api/v1/orchestration/tickets/not-an-int/comments",
            json={"body": "hi"},
        )
        assert r.status_code == 400

    def test_invalid_json_400(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets[5] = _make_ticket(5)
        r = client.post(
            "/api/v1/orchestration/tickets/5/comments",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 400


class TestGetTicketTree:
    def test_empty(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        r = client.get("/api/v1/orchestration/tickets/tree")
        assert r.status_code == 200
        body = r.json()
        # Both seed workspaces appear even with no tickets.
        assert "workspaces" in body
        ws_names = [w["workspace"]["name"] for w in body["workspaces"]]
        assert "Work" in ws_names
        assert "Personal" in ws_names

    def test_grouping_and_status_sort(self, ticket_harness):
        client, store, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {
            1: _make_ticket(1, "wip", status=4, project_id=100),
            2: _make_ticket(2, "new", status=3, project_id=100),
            3: _make_ticket(3, "blocked", status=1, project_id=100),
            4: _make_ticket(4, "personal", status=4, project_id=200, workspace_id=2),
            100: _make_ticket(100, "Project A", ticket_type="project", project_id=None),
            200: _make_ticket(
                200, "Project B", ticket_type="project", project_id=None, workspace_id=2
            ),
        }
        r = client.get("/api/v1/orchestration/tickets/tree")
        body = r.json()
        work = next(
            w for w in body["workspaces"] if w["workspace"]["name"] == "Work"
        )
        # Project A tickets only.
        proj = next(p for p in work["projects"] if p["project"]["id"] == 100)
        # No dependency relationships → all three are top-level.
        ids = [item["ticket"]["id"] for item in proj["tickets"]]
        # Sort: 4 (WIP) → 3 (New) → 1 (Blocked); within tie, id desc.
        assert ids == [1, 2, 3]

    def test_parent_child_nesting(self, ticket_harness):
        client, store, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {
            10: _make_ticket(10, "umbrella", project_id=100),
            11: _make_ticket(11, "child a", project_id=100),
            12: _make_ticket(12, "child b", project_id=100),
            100: _make_ticket(100, "Project A", ticket_type="project"),
        }
        # 10 is parent; 11 and 12 are dependents of 10.
        store.dependents_map = {10: [11, 12]}
        # 11 depends on 10; 12 depends on 10.
        store.depends_on_map = {11: [10], 12: [10]}

        r = client.get("/api/v1/orchestration/tickets/tree")
        body = r.json()
        work = next(
            w for w in body["workspaces"] if w["workspace"]["name"] == "Work"
        )
        proj = next(p for p in work["projects"] if p["project"]["id"] == 100)
        # Top-level should be just ticket 10 (child tickets 11 + 12 are nested).
        ids = [item["ticket"]["id"] for item in proj["tickets"]]
        assert ids == [10]
        children = proj["tickets"][0]["children"]
        child_ids = sorted([c["id"] for c in children])
        assert child_ids == [11, 12]

    def test_workspace_filter(self, ticket_harness):
        client, _, _, tc = ticket_harness
        _seed_workspaces(tc)
        tc.tickets = {
            1: _make_ticket(1, workspace_id=1),
            2: _make_ticket(2, workspace_id=2),
        }
        r = client.get("/api/v1/orchestration/tickets/tree?workspace=2")
        body = r.json()
        ws_names = [w["workspace"]["name"] for w in body["workspaces"]]
        assert ws_names == ["Personal"]


# Make pyflakes happy — Any imported for typing comments only.
_ = Any
