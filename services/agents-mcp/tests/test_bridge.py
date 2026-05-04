"""Smoke tests for the Telegram-bot bridge routes (web/bridge.py).

These mount the bridge into a Starlette app and drive it via the in-process
TestClient. All daemon-side dependencies (AgentStore, the task client, the
config dict) are stubbed — no SQLite, no tmux, no Anthropic API. The goal
is "the bot's 5 routes return the documented shape", not a full integration
test (the latter lives in the e2e runbook).
"""
from __future__ import annotations

from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount, Router
from starlette.testclient import TestClient

from agents_mcp.web.bridge import create_bridge_router


# ── Stubs ──────────────────────────────────────────────────────────────


class _StubCursor:
    """Minimal aiosqlite-cursor lookalike — yields a fixed row list."""

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def fetchall(self):
        return self._rows


class _StubDB:
    """Minimal aiosqlite-connection lookalike. Always returns the same rows
    for any execute() call — sufficient for the outbox query."""

    def __init__(self, outbox_rows: list[dict[str, Any]]):
        self._outbox_rows = outbox_rows

    def execute(self, *args, **kwargs):
        return _StubCursor(self._outbox_rows)


class _StubStore:
    """Stub AgentStore tracking calls so we can assert on them."""

    def __init__(self, outbox_rows: list[dict[str, Any]] | None = None):
        self.inserted_human: list[dict] = []
        self.inserted_p2p: list[dict] = []
        self.processed_ids: list[int] = []
        self._next_id = 100
        self._db = _StubDB(outbox_rows or [])

    async def insert_human_message(
        self,
        direction: str,
        body: str,
        channel: str = "system",
        source_agent_type: str | None = None,
        context_type: str = "",
        **_,
    ) -> int:
        self._next_id += 1
        self.inserted_human.append({
            "id": self._next_id,
            "direction": direction,
            "body": body,
            "channel": channel,
            "context_type": context_type,
            "source_agent_type": source_agent_type,
        })
        return self._next_id

    async def insert_message(self, from_agent: str, to_agent: str, body: str) -> int:
        self._next_id += 1
        self.inserted_p2p.append({
            "id": self._next_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "body": body,
        })
        return self._next_id

    async def mark_human_message_processed(self, message_id: int) -> bool:
        self.processed_ids.append(message_id)
        return True


class _StubClient:
    """Stub SQLiteTaskClient — only the methods bridge.py touches."""

    def __init__(self, *, status_labels_ok: bool = True):
        self._status_labels_ok = status_labels_ok
        self.add_comment_calls: list[tuple] = []
        self.update_ticket_calls: list[tuple] = []

    async def get_status_labels(self):
        if not self._status_labels_ok:
            raise RuntimeError("simulated DB failure")
        return [{"id": 0, "label": "Done"}]


def _build_app(
    *,
    store: _StubStore | None = None,
    client: _StubClient | None = None,
    cfg: dict | None = None,
) -> tuple[Starlette, _StubStore, _StubClient]:
    """Construct a Starlette app with the bridge routes mounted at /api."""
    store = store or _StubStore()
    client = client or _StubClient()
    cfg = cfg or {"tmux_session": "agents"}

    def get_client():
        return client

    async def get_store():
        return store

    def get_config():
        return cfg

    def resolve_agents(_cfg):
        return {}

    routes = create_bridge_router(get_client, get_store, get_config, resolve_agents)
    app = Starlette(routes=[Mount("/api", routes=[Mount("/", app=Router(routes=routes))])])
    return app, store, client


# ── GET /api/v1/health ─────────────────────────────────────────────────


def test_health_returns_200_with_expected_shape():
    app, _store, _client = _build_app()
    with TestClient(app) as tc:
        r = tc.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["task_db"] is True
        # tmux_active / tmux_session were removed on 2026-05-03 along with
        # the v1 named-tmux-window agent model. Confirm they don't sneak
        # back in (anything new should land via a fresh test).
        assert "tmux_active" not in body
        assert "tmux_session" not in body


def test_health_reports_task_db_false_on_failure():
    client = _StubClient(status_labels_ok=False)
    app, _store, _client = _build_app(client=client)
    with TestClient(app) as tc:
        r = tc.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["task_db"] is False  # caught the exception, did not 500


# ── GET /api/v1/brief ──────────────────────────────────────────────────


def test_brief_returns_markdown_text(monkeypatch):
    """Brief endpoint should call generate_brief and return its text."""

    async def _fake_generate_brief(client, store, config=None):
        return "# Morning Brief\n\nTest body."

    import agents_mcp.morning_brief as mb
    monkeypatch.setattr(mb, "generate_brief", _fake_generate_brief)

    app, _store, _client = _build_app()
    with TestClient(app) as tc:
        r = tc.get("/api/v1/brief")
        assert r.status_code == 200
        # PlainTextResponse with text/markdown
        assert r.headers["content-type"].startswith("text/markdown")
        assert "Morning Brief" in r.text


# ── Smoke: create_bridge_router can be imported and called ─────────────


def test_bridge_router_factory_is_importable():
    """Catches import-time errors that would crash the daemon at boot."""
    from agents_mcp.web.bridge import create_bridge_router as factory
    routes = factory(
        get_client=lambda: None,
        get_store=lambda: None,
        get_config=lambda: {},
        resolve_agents=lambda _c: {},
    )
    assert isinstance(routes, list)
    paths = {r.path for r in routes}
    # Phase 5b cleanup (#27): the three /v1/human/* routes were removed
    # after Phase 4 retired the v1 Telegram bot. Only the two
    # consumer-facing endpoints (`/brief` for the bot's slash command,
    # `/health` for proxy + bot status) remain.
    assert paths == {"/v1/brief", "/v1/health"}
