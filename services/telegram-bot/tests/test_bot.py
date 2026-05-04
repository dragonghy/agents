"""Unit tests for the Telegram channel-adapter bot.

Covers:
- channel_id <-> chat_id round-trip helpers
- inbound: spawn-or-reuse session, append message
- slash command dispatch (/start, /list, /new, /profile, /help, unknown)
- SSE block parsing (id / event / data lines, comments, malformed JSON)
- outbound SSE relay logic — assistant turn for telegram channel is sent;
  user turns / non-telegram channels / role=user / unrelated kinds are not

aiohttp is fully mocked — no network. We use a hand-rolled fake session
class that records calls and lets each test wire the responses it cares
about. The real bot uses aiohttp.ClientSession directly so this stub is
narrow and only implements the methods the bot calls (.get / .post,
async context manager, .json / .text).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from unittest.mock import patch

import pytest

import bot


# ── Fake aiohttp ─────────────────────────────────────────────────────────


class _FakeResponse:
    """Minimal aiohttp ClientResponse stand-in used by tests."""

    def __init__(
        self,
        *,
        status: int = 200,
        json_body: Any = None,
        text_body: str = "",
    ):
        self.status = status
        self._json = json_body
        self._text = text_body

    async def json(self) -> Any:
        return self._json if self._json is not None else {}

    async def text(self) -> str:
        if self._text:
            return self._text
        if self._json is not None:
            return json.dumps(self._json)
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Stub ClientSession that returns scripted responses by URL."""

    def __init__(self):
        # Each entry is a list of _FakeResponse, drained in order; the last
        # element is reused if the test exhausts it.
        self.get_responses: dict[str, list[_FakeResponse]] = {}
        self.post_responses: dict[str, list[_FakeResponse]] = {}
        self.calls: list[tuple[str, str, dict, dict]] = []  # (verb, url, params/json, extras)

    def _next(self, table: dict[str, list[_FakeResponse]], url: str) -> _FakeResponse:
        bucket = table.get(url) or table.get("*")
        if bucket is None:
            return _FakeResponse(status=200, json_body={})
        if len(bucket) == 1:
            return bucket[0]
        return bucket.pop(0)

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, dict(params or {}), {"headers": dict(headers or {})}))
        return self._next(self.get_responses, url)

    def post(self, url, *, json=None, timeout=None):
        self.calls.append(("POST", url, dict(json or {}), {}))
        return self._next(self.post_responses, url)


# ── Helpers ──────────────────────────────────────────────────────────────


def url(path: str) -> str:
    return f"{bot.DAEMON_URL}{path}"


def telegram_url(method: str) -> str:
    return f"{bot.TELEGRAM_API}/{method}"


# ── Channel id helpers ───────────────────────────────────────────────────


class TestChannelIdHelpers:
    def test_channel_id_for_chat(self):
        assert bot._channel_id_for_chat("12345") == "telegram:12345"

    def test_chat_id_from_channel_id_telegram(self):
        assert bot._chat_id_from_channel_id("telegram:12345") == "12345"

    def test_chat_id_from_channel_id_other_returns_none(self):
        assert bot._chat_id_from_channel_id("slack:C123") is None
        assert bot._chat_id_from_channel_id("") is None
        assert bot._chat_id_from_channel_id(None) is None
        assert bot._chat_id_from_channel_id("telegram:") is None


# ── Inbound: find / spawn / append ────────────────────────────────────────


class TestFindActiveSession:
    async def test_returns_first_session_when_present(self):
        session = FakeSession()
        session.get_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(json_body={"sessions": [{"id": "sess_a"}, {"id": "sess_b"}]}),
        ]
        row = await bot.find_active_session("12345", session)
        assert row == {"id": "sess_a"}
        # Should have requested with channel_id + status filters.
        verb, u, params, _ = session.calls[0]
        assert verb == "GET"
        assert params["channel_id"] == "telegram:12345"
        assert params["status"] == "active"

    async def test_returns_none_when_empty(self):
        session = FakeSession()
        session.get_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(json_body={"sessions": []}),
        ]
        row = await bot.find_active_session("12345", session)
        assert row is None

    async def test_returns_none_on_error_status(self):
        session = FakeSession()
        session.get_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(status=500, text_body="boom"),
        ]
        row = await bot.find_active_session("12345", session)
        assert row is None


class TestSpawnSession:
    async def test_posts_correct_body(self):
        session = FakeSession()
        session.post_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(status=201, json_body={"id": "sess_new", "profile_name": "secretary"}),
        ]
        row = await bot.spawn_session("12345", "secretary", session)
        assert row == {"id": "sess_new", "profile_name": "secretary"}
        verb, u, body, _ = session.calls[0]
        assert verb == "POST"
        assert body["profile_name"] == "secretary"
        assert body["binding_kind"] == "human-channel"
        assert body["channel_id"] == "telegram:12345"

    async def test_returns_none_on_failure(self):
        session = FakeSession()
        session.post_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(status=400, text_body="bad"),
        ]
        row = await bot.spawn_session("12345", "secretary", session)
        assert row is None


class TestAppendMessage:
    async def test_success_returns_true(self):
        session = FakeSession()
        session.post_responses[url("/api/v1/orchestration/sessions/sess_a/messages")] = [
            _FakeResponse(status=200, json_body={"assistant_text": "ok"}),
        ]
        ok = await bot.append_message("sess_a", "hi", session)
        assert ok is True
        verb, _, body, _ = session.calls[0]
        assert verb == "POST"
        assert body == {"text": "hi"}

    async def test_failure_returns_false(self):
        session = FakeSession()
        session.post_responses[url("/api/v1/orchestration/sessions/sess_a/messages")] = [
            _FakeResponse(status=500, text_body="oops"),
        ]
        ok = await bot.append_message("sess_a", "hi", session)
        assert ok is False


class TestHandleHumanMessage:
    """Integration of the inbound flow: find → spawn-if-needed → append."""

    async def test_uses_existing_active_session(self):
        session = FakeSession()
        # Active session exists.
        session.get_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(json_body={"sessions": [{"id": "sess_existing"}]}),
        ]
        # append_message returns OK.
        session.post_responses[url("/api/v1/orchestration/sessions/sess_existing/messages")] = [
            _FakeResponse(status=200, json_body={}),
        ]
        await bot.handle_human_message("12345", "hi there", session)
        # No spawn POST.
        spawn_calls = [
            c for c in session.calls
            if c[0] == "POST" and c[1] == url("/api/v1/orchestration/sessions")
        ]
        assert spawn_calls == []
        # Append did fire.
        append_calls = [c for c in session.calls if "messages" in c[1]]
        assert len(append_calls) == 1
        assert append_calls[0][2] == {"text": "hi there"}

    async def test_spawns_when_no_active_session(self):
        session = FakeSession()
        # No active session.
        session.get_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(json_body={"sessions": []}),
        ]
        # Spawn returns a new row.
        session.post_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(status=201, json_body={"id": "sess_new"}),
        ]
        # Append succeeds.
        session.post_responses[url("/api/v1/orchestration/sessions/sess_new/messages")] = [
            _FakeResponse(status=200, json_body={}),
        ]
        await bot.handle_human_message("12345", "hi", session)
        spawn_calls = [
            c for c in session.calls
            if c[0] == "POST" and c[1] == url("/api/v1/orchestration/sessions")
        ]
        assert len(spawn_calls) == 1
        assert spawn_calls[0][2]["profile_name"] == bot.DEFAULT_PROFILE
        append_calls = [c for c in session.calls if "messages" in c[1]]
        assert len(append_calls) == 1

    async def test_sends_error_message_when_spawn_fails(self):
        session = FakeSession()
        session.get_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(json_body={"sessions": []}),
        ]
        session.post_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(status=500, text_body="boom"),
        ]
        # Telegram send. Use wildcard for sendMessage.
        session.post_responses[telegram_url("sendMessage")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]
        await bot.handle_human_message("12345", "hi", session)
        # Should have called Telegram with an error apology.
        tg_calls = [c for c in session.calls if telegram_url("sendMessage") in c[1]]
        assert tg_calls
        assert "Failed" in tg_calls[0][2]["text"]


# ── Slash command dispatch ───────────────────────────────────────────────


class TestDispatchCommand:
    async def test_non_slash_returns_false(self):
        session = FakeSession()
        handled = await bot.dispatch_command("12345", "hello there", session)
        assert handled is False
        # No Telegram send fired.
        assert session.calls == []

    async def test_help_command(self):
        session = FakeSession()
        session.post_responses[telegram_url("sendMessage")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]
        handled = await bot.dispatch_command("12345", "/help", session)
        assert handled is True
        tg_calls = [c for c in session.calls if telegram_url("sendMessage") in c[1]]
        assert tg_calls
        assert "Commands" in tg_calls[0][2]["text"]

    async def test_unknown_command_surfaces_help_hint(self):
        session = FakeSession()
        session.post_responses[telegram_url("sendMessage")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]
        handled = await bot.dispatch_command("12345", "/bogus", session)
        assert handled is True
        text = session.calls[-1][2]["text"]
        assert "Unknown command" in text
        assert "/help" in text

    async def test_profile_command_without_arg(self):
        session = FakeSession()
        session.post_responses[telegram_url("sendMessage")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]
        await bot.dispatch_command("12345", "/profile", session)
        text = session.calls[-1][2]["text"]
        assert "/profile" in text  # usage hint

    async def test_profile_command_switches_session(self):
        session = FakeSession()
        # find_active_session returns a current session.
        session.get_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(json_body={"sessions": [{"id": "old", "profile_name": "secretary"}]}),
        ]
        # close_session
        session.post_responses[url("/api/v1/orchestration/sessions/old/close")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]
        # spawn_session
        session.post_responses[url("/api/v1/orchestration/sessions")] = [
            _FakeResponse(status=201, json_body={"id": "new", "profile_name": "housekeeper"}),
        ]
        # Telegram confirmation.
        session.post_responses[telegram_url("sendMessage")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]
        await bot.dispatch_command("12345", "/profile housekeeper", session)
        # close was called
        close_calls = [c for c in session.calls if "close" in c[1]]
        assert len(close_calls) == 1
        # spawn was called with housekeeper
        spawn_calls = [
            c for c in session.calls
            if c[0] == "POST" and c[1] == url("/api/v1/orchestration/sessions")
        ]
        assert spawn_calls[0][2]["profile_name"] == "housekeeper"

    async def test_session_command_punts(self):
        """v1: /session <id> says resume not supported."""
        session = FakeSession()
        session.post_responses[telegram_url("sendMessage")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]
        await bot.dispatch_command("12345", "/session abc", session)
        text = session.calls[-1][2]["text"]
        assert "not yet supported" in text.lower()


# ── SSE parsing ──────────────────────────────────────────────────────────


class TestParseSseBlock:
    def test_full_frame(self):
        block = (
            "id: 42\n"
            "event: session.message_appended\n"
            "data: {\"id\":42,\"kind\":\"session.message_appended\","
            "\"payload\":{\"role\":\"assistant\",\"text\":\"hi\"}}"
        )
        ev = bot._parse_sse_block(block)
        assert ev is not None
        assert ev["id"] == 42
        assert ev["kind"] == "session.message_appended"
        assert ev["payload"]["role"] == "assistant"
        assert ev["payload"]["text"] == "hi"

    def test_keepalive_returns_none(self):
        ev = bot._parse_sse_block(": keepalive")
        assert ev is None

    def test_no_data_returns_none(self):
        ev = bot._parse_sse_block("id: 1\nevent: foo")
        assert ev is None

    def test_malformed_json_returns_none(self):
        ev = bot._parse_sse_block("id: 1\nevent: x\ndata: not-json")
        assert ev is None

    def test_id_falls_back_to_payload(self):
        block = (
            "event: session.created\n"
            "data: {\"id\":99,\"kind\":\"session.created\",\"payload\":{}}"
        )
        ev = bot._parse_sse_block(block)
        assert ev is not None
        assert ev["id"] == 99


# ── Outbound SSE relay logic ──────────────────────────────────────────────


class _StubStream:
    """Replace _stream_sse with an async generator yielding scripted events."""

    def __init__(self, events: list[dict], raise_after: bool = False):
        self.events = events
        self.raise_after = raise_after

    def __call__(self, session, last_event_id):  # noqa: ARG002
        async def gen():
            for ev in self.events:
                yield ev
            if self.raise_after:
                raise RuntimeError("stream broke")
        return gen()


class TestOutboundSseLoop:
    async def test_relays_assistant_for_telegram_session(self):
        """A session.message_appended w/ role=assistant whose session is
        bound to telegram:<chat> gets relayed; user turns / others don't."""
        events = [
            {  # user turn — should NOT be relayed
                "id": 1,
                "kind": "session.message_appended",
                "payload": {
                    "session_id": "sess_a",
                    "role": "user",
                    "text": "hi human",
                },
            },
            {  # assistant turn — relayed
                "id": 2,
                "kind": "session.message_appended",
                "payload": {
                    "session_id": "sess_a",
                    "role": "assistant",
                    "text": "hello back",
                },
            },
            {  # session.created — wrong kind
                "id": 3,
                "kind": "session.created",
                "payload": {"id": "sess_a"},
            },
        ]

        session = FakeSession()
        # get_session_meta returns the channel binding.
        session.get_responses[url("/api/v1/orchestration/sessions/sess_a")] = [
            _FakeResponse(json_body={"id": "sess_a", "channel_id": "telegram:55555"}),
        ]
        # Telegram sendMessage success.
        session.post_responses[telegram_url("sendMessage")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]

        # We need the loop to terminate; patch _stream_sse to yield then
        # raise CancelledError to stop the outer while-True.
        async def fake_stream(s, last_event_id):  # noqa: ARG001
            for ev in events:
                yield ev
            raise asyncio.CancelledError()

        with patch.object(bot, "_stream_sse", fake_stream):
            with pytest.raises(asyncio.CancelledError):
                await bot.outbound_sse_loop(session)

        # Exactly one Telegram send for the assistant turn.
        tg_calls = [c for c in session.calls if telegram_url("sendMessage") in c[1]]
        assert len(tg_calls) == 1
        assert tg_calls[0][2]["text"] == "hello back"
        assert tg_calls[0][2]["chat_id"] == "55555"

    async def test_skips_non_telegram_channel(self):
        events = [
            {
                "id": 1,
                "kind": "session.message_appended",
                "payload": {
                    "session_id": "sess_w",
                    "role": "assistant",
                    "text": "should not deliver",
                },
            },
        ]
        session = FakeSession()
        session.get_responses[url("/api/v1/orchestration/sessions/sess_w")] = [
            _FakeResponse(json_body={"id": "sess_w", "channel_id": "web:abc"}),
        ]

        async def fake_stream(s, last_event_id):  # noqa: ARG001
            for ev in events:
                yield ev
            raise asyncio.CancelledError()

        with patch.object(bot, "_stream_sse", fake_stream):
            with pytest.raises(asyncio.CancelledError):
                await bot.outbound_sse_loop(session)

        tg_calls = [c for c in session.calls if telegram_url("sendMessage") in c[1]]
        assert tg_calls == []

    async def test_caches_channel_lookup(self):
        events = [
            {
                "id": 1,
                "kind": "session.message_appended",
                "payload": {"session_id": "sess_x", "role": "assistant", "text": "one"},
            },
            {
                "id": 2,
                "kind": "session.message_appended",
                "payload": {"session_id": "sess_x", "role": "assistant", "text": "two"},
            },
        ]
        session = FakeSession()
        session.get_responses[url("/api/v1/orchestration/sessions/sess_x")] = [
            _FakeResponse(json_body={"id": "sess_x", "channel_id": "telegram:55555"}),
        ]
        session.post_responses[telegram_url("sendMessage")] = [
            _FakeResponse(status=200, json_body={"ok": True}),
        ]

        async def fake_stream(s, last_event_id):  # noqa: ARG001
            for ev in events:
                yield ev
            raise asyncio.CancelledError()

        with patch.object(bot, "_stream_sse", fake_stream):
            with pytest.raises(asyncio.CancelledError):
                await bot.outbound_sse_loop(session)

        # Only one session-meta GET despite two assistant turns.
        meta_calls = [
            c for c in session.calls
            if c[0] == "GET" and c[1] == url("/api/v1/orchestration/sessions/sess_x")
        ]
        assert len(meta_calls) == 1
        # Two telegram sends.
        tg_calls = [c for c in session.calls if telegram_url("sendMessage") in c[1]]
        assert len(tg_calls) == 2
