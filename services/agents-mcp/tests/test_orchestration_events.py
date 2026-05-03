"""Tests for ``agents_mcp.web.orchestration_events`` (Phase 3 Part E).

Two layers:

1. **EventBus unit tests** — pure in-memory pub/sub semantics: monotonic
   ids, ring-buffer eviction at MAX_BUFFER, replay via ``since_id``,
   multiple subscribers, slow-consumer overflow handling.

2. **SSE integration tests** — drive the route via
   :class:`starlette.testclient.TestClient`'s HTTP transport. The
   tests assert: connect → live event arrives, replay via
   ``Last-Event-ID`` header on connect, replay via ``?since=`` query
   param fallback, ring-buffer eviction visible to the stream, content
   type is ``text/event-stream``.

Style mirrors ``test_orchestration_api.py``: sync test functions, no
pytest-asyncio dep. The async EventBus methods are awaited via a
trampoline ``run()`` helper.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from agents_mcp.web.orchestration_events import (
    EVENT_SESSION_CLOSED,
    EVENT_SESSION_COST_UPDATED,
    EVENT_SESSION_CREATED,
    EVENT_SESSION_MESSAGE_APPENDED,
    MAX_BUFFER,
    OrchestrationEventBus,
    create_sse_endpoint,
    reset_event_bus_for_tests,
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── EventBus unit tests ────────────────────────────────────────────────────


class TestPublishMonotonicIds:
    def test_first_event_id_is_one(self):
        bus = OrchestrationEventBus()
        ev = bus.publish(EVENT_SESSION_CREATED, {"session_id": "sess_a"})
        assert ev["id"] == 1

    def test_ids_increment_monotonically(self):
        bus = OrchestrationEventBus()
        ids = [
            bus.publish(EVENT_SESSION_CREATED, {"i": i})["id"]
            for i in range(5)
        ]
        assert ids == [1, 2, 3, 4, 5]

    def test_event_shape(self):
        bus = OrchestrationEventBus()
        ev = bus.publish("session.created", {"x": 1})
        assert set(ev.keys()) == {"id", "kind", "ts", "payload"}
        assert ev["kind"] == "session.created"
        assert ev["payload"] == {"x": 1}
        # ts is a non-empty string (ISO8601)
        assert isinstance(ev["ts"], str) and len(ev["ts"]) > 10

    def test_all_four_event_kinds_constants_exist(self):
        # These are the public API surface — guard against accidental rename.
        assert EVENT_SESSION_CREATED == "session.created"
        assert EVENT_SESSION_MESSAGE_APPENDED == "session.message_appended"
        assert EVENT_SESSION_COST_UPDATED == "session.cost_updated"
        assert EVENT_SESSION_CLOSED == "session.closed"


class TestSubscribe:
    def test_subscriber_receives_events(self):
        async def _t():
            bus = OrchestrationEventBus()
            client_id, queue = bus.subscribe()
            assert client_id.startswith("sse-")
            bus.publish("session.created", {"id": 1})
            bus.publish("session.closed", {"id": 1})
            ev1 = await asyncio.wait_for(queue.get(), 1.0)
            ev2 = await asyncio.wait_for(queue.get(), 1.0)
            assert ev1["kind"] == "session.created"
            assert ev2["kind"] == "session.closed"
            bus.unsubscribe(client_id)

        run(_t())

    def test_multiple_subscribers_each_get_event(self):
        async def _t():
            bus = OrchestrationEventBus()
            _, q1 = bus.subscribe()
            _, q2 = bus.subscribe()
            _, q3 = bus.subscribe()
            bus.publish("session.created", {"k": "v"})
            for q in (q1, q2, q3):
                ev = await asyncio.wait_for(q.get(), 1.0)
                assert ev["kind"] == "session.created"

        run(_t())

    def test_subscriber_after_publish_does_not_get_old_event(self):
        async def _t():
            bus = OrchestrationEventBus()
            bus.publish("session.created", {})  # before subscribe
            _, q = bus.subscribe()
            # No live event in queue — buffer is in the bus, not in this queue.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(q.get(), 0.1)

        run(_t())

    def test_unsubscribe_stops_delivery(self):
        async def _t():
            bus = OrchestrationEventBus()
            cid, q = bus.subscribe()
            bus.publish("session.created", {"a": 1})
            await asyncio.wait_for(q.get(), 1.0)  # delivered
            bus.unsubscribe(cid)
            bus.publish("session.created", {"b": 2})  # nobody listening
            # Subscriber set should not have the id anymore.
            assert bus.subscriber_count == 0

        run(_t())

    def test_unsubscribe_is_idempotent(self):
        bus = OrchestrationEventBus()
        cid, _ = bus.subscribe()
        bus.unsubscribe(cid)
        bus.unsubscribe(cid)  # no raise

    def test_subscriber_count_introspection(self):
        bus = OrchestrationEventBus()
        assert bus.subscriber_count == 0
        c1, _ = bus.subscribe()
        assert bus.subscriber_count == 1
        c2, _ = bus.subscribe()
        assert bus.subscriber_count == 2
        bus.unsubscribe(c1)
        assert bus.subscriber_count == 1
        bus.unsubscribe(c2)
        assert bus.subscriber_count == 0


class TestReplay:
    def test_replay_since_zero_returns_all(self):
        bus = OrchestrationEventBus()
        bus.publish("session.created", {"a": 1})
        bus.publish("session.closed", {"a": 1})
        bus.publish("session.created", {"a": 2})
        events = bus.replay(0)
        assert len(events) == 3
        assert [e["id"] for e in events] == [1, 2, 3]

    def test_replay_since_id_returns_only_newer(self):
        bus = OrchestrationEventBus()
        for i in range(5):
            bus.publish("session.created", {"i": i})
        # since=2 → should get ids 3, 4, 5
        events = bus.replay(2)
        assert [e["id"] for e in events] == [3, 4, 5]

    def test_replay_since_latest_returns_empty(self):
        bus = OrchestrationEventBus()
        bus.publish("session.created", {"a": 1})
        bus.publish("session.created", {"a": 2})
        assert bus.replay(2) == []
        # And one past the end is also empty.
        assert bus.replay(99) == []

    def test_replay_negative_since_returns_all(self):
        bus = OrchestrationEventBus()
        bus.publish("session.created", {"a": 1})
        # since <= 0 means "give me whatever's in the buffer".
        assert len(bus.replay(-1)) == 1
        assert len(bus.replay(0)) == 1


class TestRingBufferEviction:
    def test_buffer_caps_at_max(self):
        bus = OrchestrationEventBus(max_buffer=5)
        for i in range(10):
            bus.publish("session.created", {"i": i})
        assert bus.buffer_size == 5
        # The oldest events were evicted; only ids 6..10 remain.
        events = bus.replay(0)
        assert [e["id"] for e in events] == [6, 7, 8, 9, 10]

    def test_replay_after_eviction_skips_dropped(self):
        bus = OrchestrationEventBus(max_buffer=3)
        for i in range(6):
            bus.publish("session.created", {"i": i})
        # Buffer holds ids 4, 5, 6. Replay since=2 should return what's
        # available (4, 5, 6) — it cannot resurrect 3.
        events = bus.replay(2)
        assert [e["id"] for e in events] == [4, 5, 6]

    def test_default_buffer_size(self):
        bus = OrchestrationEventBus()
        # Push 1500 events into the default 1000-buffer.
        for i in range(1500):
            bus.publish("session.created", {"i": i})
        assert bus.buffer_size == MAX_BUFFER == 1000


class TestSlowConsumerOverflow:
    def test_overflow_drops_event_for_one_subscriber_only(self):
        """A slow subscriber's queue overflowing should NOT crash publish or
        affect other subscribers.
        """

        async def _t():
            bus = OrchestrationEventBus()
            # Tight queue for the "slow" subscriber.
            _, slow = bus.subscribe()
            bus._subscribers[next(iter(bus._subscribers))] = (
                asyncio.Queue(maxsize=2)
            )
            slow_cid = next(iter(bus._subscribers))
            slow = bus._subscribers[slow_cid]

            _, fast = bus.subscribe()
            for i in range(10):
                bus.publish("session.created", {"i": i})

            # Fast subscriber drains all 10 fine.
            for i in range(10):
                ev = await asyncio.wait_for(fast.get(), 1.0)
                assert ev["payload"]["i"] == i

            # Slow subscriber got at most maxsize events.
            drained = []
            try:
                while True:
                    drained.append(slow.get_nowait())
            except asyncio.QueueEmpty:
                pass
            assert len(drained) <= 2

        run(_t())


# ── SSE wire format / endpoint tests ──────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Each test starts with a fresh bus singleton."""
    reset_event_bus_for_tests()
    yield
    reset_event_bus_for_tests()


def _parse_sse_frames(body: str) -> list[dict]:
    """Parse SSE wire format → list of {id, event, data} dicts.

    Skips comment lines (``: ...``) — those are keep-alives. Each frame
    is separated by a blank line.
    """
    frames: list[dict] = []
    current: dict[str, str] = {}
    for raw_line in body.split("\n"):
        line = raw_line.rstrip("\r")
        if line == "":
            if current:
                frames.append(current)
                current = {}
            continue
        if line.startswith(":"):
            # Comment — skip (keep-alive).
            continue
        if ":" in line:
            field, _, value = line.partition(":")
            value = value.lstrip(" ")
            current[field] = value
    if current:
        frames.append(current)
    return frames


class TestSSEEndpoint:
    """Drive the SSE async generator directly.

    We deliberately avoid Starlette's :class:`TestClient` for SSE because
    its synchronous transport keeps the streaming response open until the
    server-side generator returns — and our generator is intentionally
    infinite (it's a live event stream). Instead, we drive the
    :class:`StreamingResponse`'s body iterator directly under
    ``asyncio``, simulating a client disconnect by setting
    ``is_disconnected`` to ``True`` after we've seen what we expect.
    """

    def _make_request(
        self,
        last_event_id: str | None = None,
        since: str | None = None,
    ):
        """Build a fake Starlette ``Request`` for direct invocation.

        Returns ``(request, set_disconnected)`` where ``set_disconnected``
        flips the request's disconnect flag so the async generator
        cleanly exits.
        """
        from starlette.requests import Request

        disconnected = {"v": False}

        async def receive():
            # Block forever until disconnected, then return the
            # ``http.disconnect`` event Starlette uses for is_disconnected().
            while not disconnected["v"]:
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        headers = []
        if last_event_id is not None:
            headers.append((b"last-event-id", last_event_id.encode()))

        path = "/events"
        query = b""
        if since is not None:
            query = f"since={since}".encode()

        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "headers": headers,
        }
        req = Request(scope, receive=receive)

        def set_disconnected():
            disconnected["v"] = True

        return req, set_disconnected

    async def _drain(
        self,
        bus: OrchestrationEventBus,
        last_event_id: str | None = None,
        since: str | None = None,
        wait_for_frames: int = 1,
        idle_timeout_s: float = 2.0,
    ) -> list[dict]:
        """Run the SSE endpoint long enough to collect at least ``wait_for_frames``
        non-keepalive frames, then disconnect and return parsed frames.
        """
        endpoint = create_sse_endpoint(bus)
        request, set_disconnected = self._make_request(
            last_event_id=last_event_id, since=since
        )
        response = await endpoint(request)
        body_iter = response.body_iterator
        chunks: list[bytes] = []
        try:
            # Consume chunks until we see enough frames or hit the timeout.
            async def reader():
                async for chunk in body_iter:
                    chunks.append(chunk)
                    body = b"".join(chunks).decode("utf-8")
                    # Count non-comment frames (each ends with \n\n; comment
                    # lines start with ':' and are filtered post-parse).
                    frames_so_far = _parse_sse_frames(body)
                    if len(frames_so_far) >= wait_for_frames:
                        return

            try:
                await asyncio.wait_for(reader(), timeout=idle_timeout_s)
            except asyncio.TimeoutError:
                # Fine — caller may be intentionally checking that no
                # frames arrive (e.g. the keepalive-only path).
                pass
        finally:
            set_disconnected()
            # Give the generator's finally{} a moment to clean up.
            try:
                await asyncio.wait_for(body_iter.aclose(), timeout=1.0)
            except (asyncio.TimeoutError, Exception):
                pass

        body = b"".join(chunks).decode("utf-8")
        return _parse_sse_frames(body)

    def test_replay_with_no_last_event_id_returns_full_buffer(self):
        async def _t():
            bus = OrchestrationEventBus()
            bus.publish(EVENT_SESSION_CREATED, {"i": 1})
            bus.publish(EVENT_SESSION_CREATED, {"i": 2})
            frames = await self._drain(bus, wait_for_frames=2)
            assert len(frames) >= 2
            assert frames[0]["id"] == "1"
            assert frames[0]["event"] == EVENT_SESSION_CREATED
            data1 = json.loads(frames[0]["data"])
            assert data1["payload"] == {"i": 1}
            assert frames[1]["id"] == "2"
            data2 = json.loads(frames[1]["data"])
            assert data2["payload"] == {"i": 2}

        run(_t())

    def test_replay_with_last_event_id_header_skips_older(self):
        async def _t():
            bus = OrchestrationEventBus()
            for i in range(5):
                bus.publish(EVENT_SESSION_CREATED, {"i": i})
            frames = await self._drain(
                bus, last_event_id="3", wait_for_frames=2
            )
            assert len(frames) >= 2
            assert frames[0]["id"] == "4"
            assert frames[1]["id"] == "5"

        run(_t())

    def test_replay_with_query_param_since_fallback(self):
        """Without Last-Event-ID, ``?since=`` is the curl-friendly knob."""

        async def _t():
            bus = OrchestrationEventBus()
            for i in range(3):
                bus.publish(EVENT_SESSION_CREATED, {"i": i})
            frames = await self._drain(bus, since="2", wait_for_frames=1)
            assert len(frames) >= 1
            assert frames[0]["id"] == "3"

        run(_t())

    def test_invalid_last_event_id_treated_as_zero(self):
        async def _t():
            bus = OrchestrationEventBus()
            bus.publish(EVENT_SESSION_CREATED, {"i": 1})
            frames = await self._drain(
                bus, last_event_id="not-an-int", wait_for_frames=1
            )
            assert len(frames) >= 1
            assert frames[0]["id"] == "1"

        run(_t())

    def test_event_data_is_valid_json(self):
        """Each `data:` line is a single-line JSON object the browser parses."""

        async def _t():
            bus = OrchestrationEventBus()
            bus.publish(
                EVENT_SESSION_MESSAGE_APPENDED,
                {"session_id": "sess_xyz", "role": "user", "text": "hi"},
            )
            frames = await self._drain(bus, wait_for_frames=1)
            assert len(frames) >= 1
            data = json.loads(frames[0]["data"])
            assert data["kind"] == EVENT_SESSION_MESSAGE_APPENDED
            assert data["payload"]["session_id"] == "sess_xyz"
            assert data["payload"]["role"] == "user"
            assert data["payload"]["text"] == "hi"
            # ts is also present for clients that want it.
            assert "ts" in data

        run(_t())

    def test_response_headers_are_sse_compliant(self):
        """The response sets the right Cache-Control / X-Accel-Buffering headers."""

        async def _t():
            bus = OrchestrationEventBus()
            endpoint = create_sse_endpoint(bus)
            request, _ = self._make_request()
            response = await endpoint(request)
            assert response.media_type == "text/event-stream"
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["connection"] == "keep-alive"
            assert response.headers["x-accel-buffering"] == "no"
            # Close the iterator we never started consuming.
            try:
                await response.body_iterator.aclose()
            except Exception:
                pass

        run(_t())

    def test_subscriber_registers_during_connection_and_unsubscribes_after(
        self,
    ):
        """Bus subscriber count goes up while the stream is being consumed
        and back to zero after the disconnect."""

        async def _t():
            bus = OrchestrationEventBus()
            bus.publish(EVENT_SESSION_CREATED, {"i": 1})
            assert bus.subscriber_count == 0

            endpoint = create_sse_endpoint(bus)
            request, set_disconnected = self._make_request()
            response = await endpoint(request)
            body_iter = response.body_iterator

            # Begin consuming; the very first chunk is the replayed event,
            # by which time the subscriber is registered.
            first_chunk = await asyncio.wait_for(body_iter.__anext__(), 2.0)
            assert b"id: 1" in first_chunk
            assert bus.subscriber_count == 1

            set_disconnected()
            try:
                await asyncio.wait_for(body_iter.aclose(), timeout=1.0)
            except Exception:
                pass
            # finally{} of the generator unsubscribes.
            assert bus.subscriber_count == 0

        run(_t())

    def test_live_publish_after_subscribe_is_streamed(self):
        """An event published *after* the client connects is delivered."""

        async def _t():
            bus = OrchestrationEventBus()
            endpoint = create_sse_endpoint(bus)
            request, set_disconnected = self._make_request()
            response = await endpoint(request)
            body_iter = response.body_iterator

            # Spin up a reader that collects the next frame. We publish
            # AFTER the reader is awaiting — that's the live-streaming
            # path (no replay).
            collected: list[bytes] = []

            async def collect_one():
                async for chunk in body_iter:
                    collected.append(chunk)
                    if b"\n\n" in b"".join(collected):
                        return

            reader = asyncio.create_task(collect_one())
            # Yield to let the endpoint subscribe before we publish.
            await asyncio.sleep(0.05)
            bus.publish(EVENT_SESSION_COST_UPDATED, {"session_id": "s1"})
            try:
                await asyncio.wait_for(reader, timeout=2.0)
            finally:
                set_disconnected()
                try:
                    await asyncio.wait_for(body_iter.aclose(), timeout=1.0)
                except Exception:
                    pass

            body = b"".join(collected).decode("utf-8")
            frames = _parse_sse_frames(body)
            assert len(frames) >= 1
            assert frames[0]["event"] == EVENT_SESSION_COST_UPDATED
            data = json.loads(frames[0]["data"])
            assert data["payload"] == {"session_id": "s1"}

        run(_t())
