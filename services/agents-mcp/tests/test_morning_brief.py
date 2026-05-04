"""Tests for the Phase 4 morning-brief refactor.

The refactor adds two delivery paths to ``brief_loop`` /
``deliver_brief_via_secretary``:

1. **Secretary-driven** (path b in the design): when a SessionManager is
   available AND ``HUMAN_TELEGRAM_CHAT_ID`` is set, the loop spawns a
   ``secretary`` session bound to ``telegram:<chat>`` and asks it to
   compose the brief; the Telegram bot's SSE listener relays the
   assistant turn back.
2. **Legacy admin-notify**: when either is missing, the loop posts an
   admin P2P message pointing at the saved data file.

These tests exercise ``deliver_brief_via_secretary`` directly with a
fake SessionManager, plus the env-var-driven branch selection in
``brief_loop`` (no time travel — we patch save_brief and the inner
``insert_message``/``deliver_brief_via_secretary`` calls).
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents_mcp import morning_brief


# ── deliver_brief_via_secretary ──────────────────────────────────────────


class _FakeSessionManager:
    """SessionManager-shaped stub. Records spawn / append calls."""

    def __init__(self, spawn_row=None, fail_spawn=False, fail_append=False):
        self.spawn_calls: list[dict] = []
        self.append_calls: list[tuple[str, str]] = []
        self._spawn_row = spawn_row or {"id": "sess_brief_1"}
        self._fail_spawn = fail_spawn
        self._fail_append = fail_append

    async def spawn(self, **kwargs):
        self.spawn_calls.append(kwargs)
        if self._fail_spawn:
            raise RuntimeError("spawn failed")
        return self._spawn_row

    async def append_message(self, session_id, text):
        self.append_calls.append((session_id, text))
        if self._fail_append:
            raise RuntimeError("append failed")
        return None


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestDeliverBriefViaSecretary:
    def test_spawns_session_with_telegram_channel(self):
        sm = _FakeSessionManager(spawn_row={"id": "sess_x"})

        async def go():
            return await morning_brief.deliver_brief_via_secretary(sm, "12345")

        sid = asyncio.run(go())
        assert sid == "sess_x"
        assert len(sm.spawn_calls) == 1
        call = sm.spawn_calls[0]
        assert call["profile_name"] == "secretary"
        assert call["binding_kind"] == "human-channel"
        assert call["channel_id"] == "telegram:12345"

    def test_appends_default_prompt(self):
        sm = _FakeSessionManager()

        async def go():
            await morning_brief.deliver_brief_via_secretary(sm, "12345")

        asyncio.run(go())
        assert len(sm.append_calls) == 1
        sid, text = sm.append_calls[0]
        assert sid == "sess_brief_1"
        assert "morning brief" in text.lower()
        assert "executive-brief" in text.lower()

    def test_appends_custom_prompt(self):
        sm = _FakeSessionManager()

        async def go():
            await morning_brief.deliver_brief_via_secretary(
                sm, "12345", prompt="custom-brief"
            )

        asyncio.run(go())
        assert sm.append_calls[0][1] == "custom-brief"

    def test_returns_none_when_chat_id_empty(self):
        sm = _FakeSessionManager()

        async def go():
            return await morning_brief.deliver_brief_via_secretary(sm, "")

        sid = asyncio.run(go())
        assert sid is None
        assert sm.spawn_calls == []

    def test_returns_none_when_session_manager_is_none(self):
        async def go():
            return await morning_brief.deliver_brief_via_secretary(None, "12345")

        sid = asyncio.run(go())
        assert sid is None

    def test_returns_none_on_spawn_failure(self):
        sm = _FakeSessionManager(fail_spawn=True)

        async def go():
            return await morning_brief.deliver_brief_via_secretary(sm, "12345")

        sid = asyncio.run(go())
        assert sid is None
        assert sm.append_calls == []

    def test_returns_none_on_append_failure(self):
        sm = _FakeSessionManager(fail_append=True)

        async def go():
            return await morning_brief.deliver_brief_via_secretary(sm, "12345")

        sid = asyncio.run(go())
        # Spawn succeeded; append failed → still None (wrapped in try/except).
        assert sid is None
        assert len(sm.spawn_calls) == 1
        assert len(sm.append_calls) == 1

    def test_returns_none_when_spawn_returns_no_id(self):
        sm = _FakeSessionManager(spawn_row={"profile_name": "secretary"})  # missing id

        async def go():
            return await morning_brief.deliver_brief_via_secretary(sm, "12345")

        sid = asyncio.run(go())
        assert sid is None

    def test_uses_alternate_profile_name(self):
        sm = _FakeSessionManager()

        async def go():
            await morning_brief.deliver_brief_via_secretary(
                sm, "12345", profile_name="housekeeper"
            )

        asyncio.run(go())
        assert sm.spawn_calls[0]["profile_name"] == "housekeeper"


# ── brief_loop env / sm branching ────────────────────────────────────────


class _FakeStore:
    """AgentStore-shaped stub for brief_loop. Records inserted P2P rows."""

    def __init__(self):
        self.inserted: list[dict] = []

    async def insert_message(self, **kwargs):
        self.inserted.append(kwargs)
        return 1


class TestBriefLoopBranchSelection:
    """Verify brief_loop picks the right delivery path.

    We patch ``save_brief`` (so it doesn't read SQLite) and
    ``deliver_brief_via_secretary`` (so we can assert on the call).
    The loop normally runs forever; we drive exactly one iteration by
    patching ``asyncio.sleep`` to raise CancelledError after the first
    iteration's work has completed.
    """

    @staticmethod
    async def _drive_once(monkeypatch, **kwargs):
        """Run brief_loop for one iteration then cancel.

        Patches save_brief to a no-op, asyncio.sleep to raise after a
        single completed iteration. Returns the store for assertions.
        """
        store = _FakeStore()

        async def fake_save(*args, **kw):
            return "/tmp/brief.md"

        # Force the time-window check to pass (set hour=23 so always >=).
        # We rely on the loop's hour comparison; using 0 makes it always true.
        cancelled = []

        async def fake_sleep(_):
            cancelled.append(True)
            raise asyncio.CancelledError()

        monkeypatch.setattr(morning_brief, "save_brief", fake_save)
        monkeypatch.setattr(morning_brief.asyncio, "sleep", fake_sleep)

        try:
            await morning_brief.brief_loop(
                client=None,
                store=store,
                target_hour=0,
                target_minute=0,
                output_dir="/tmp",
                **kwargs,
            )
        except asyncio.CancelledError:
            pass

        return store

    def test_secretary_path_when_chat_and_sm_present(self, monkeypatch):
        """When HUMAN_TELEGRAM_CHAT_ID is set AND session_manager is given,
        deliver_brief_via_secretary is called and the legacy admin-notify
        path is skipped."""
        sm = _FakeSessionManager(spawn_row={"id": "sess_brief"})
        monkeypatch.setenv("HUMAN_TELEGRAM_CHAT_ID", "55555")
        # Cover the legacy alias too.
        monkeypatch.delenv("TELEGRAM_HUMAN_CHAT_ID", raising=False)

        async def go():
            return await self._drive_once(monkeypatch, session_manager=sm)

        store = asyncio.run(go())

        # Secretary spawn happened.
        assert len(sm.spawn_calls) == 1
        assert sm.spawn_calls[0]["channel_id"] == "telegram:55555"
        # No admin-notify P2P message.
        assert store.inserted == []

    def test_admin_notify_when_chat_id_missing(self, monkeypatch):
        """No env var → legacy admin-notify path runs."""
        monkeypatch.delenv("HUMAN_TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("TELEGRAM_HUMAN_CHAT_ID", raising=False)
        sm = _FakeSessionManager()

        async def go():
            return await self._drive_once(monkeypatch, session_manager=sm)

        store = asyncio.run(go())

        # Secretary NOT spawned.
        assert sm.spawn_calls == []
        # Legacy admin-notify did fire.
        assert len(store.inserted) == 1
        assert store.inserted[0]["to_agent"] == "admin"
        assert "Morning Brief" in store.inserted[0]["body"]

    def test_admin_notify_when_session_manager_missing(self, monkeypatch):
        """env var set but no session_manager → falls back to admin-notify."""
        monkeypatch.setenv("HUMAN_TELEGRAM_CHAT_ID", "55555")

        async def go():
            return await self._drive_once(monkeypatch, session_manager=None)

        store = asyncio.run(go())

        assert len(store.inserted) == 1
        assert store.inserted[0]["to_agent"] == "admin"

    def test_falls_back_to_admin_notify_on_secretary_failure(self, monkeypatch):
        """When deliver_brief_via_secretary returns None (e.g. spawn fails),
        the loop falls back to the legacy admin-notify path so the daemon
        always produces SOME signal that it ran."""
        sm = _FakeSessionManager(fail_spawn=True)
        monkeypatch.setenv("HUMAN_TELEGRAM_CHAT_ID", "55555")

        async def go():
            return await self._drive_once(monkeypatch, session_manager=sm)

        store = asyncio.run(go())

        # Secretary tried + failed.
        assert len(sm.spawn_calls) == 1
        # Legacy admin-notify ran as fallback.
        assert len(store.inserted) == 1
        assert store.inserted[0]["to_agent"] == "admin"
