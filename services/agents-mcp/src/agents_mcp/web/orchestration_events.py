"""Orchestration v1 — in-process event bus + SSE endpoint + replay buffer.

This module pushes orchestration-v1 events to the Web UI over Server-Sent
Events (SSE). The design avoids the failure modes documented in
``projects/agent-hub/research/paperclip-review-2026-05-02.md`` §"Heartbeat
fragility":

- **Replay buffer**: every published event gets a monotonic id and is
  retained in a ring buffer (last ``MAX_BUFFER`` = 1000). Subscribers may
  pass the standard ``Last-Event-ID`` HTTP header on connect to receive
  any events they missed. Browsers' native ``EventSource`` sends this
  header automatically on auto-reconnect — no client-side reconnect logic
  required.
- **Native auto-reconnect**: ``EventSource`` reconnects on its own with
  exponential backoff. The replay buffer + ``Last-Event-ID`` give us a
  gap-free experience after transient network blips, OS suspends, or
  proxy idle-timeouts without writing any reconnect logic on the client.
- **Keep-alive comments**: every 20s the server emits a comment line
  (``: keepalive\\n\\n``) so misbehaving proxies don't idle-kill the
  connection. SSE comments are no-ops for the browser parser.
- **No state cleanup on disconnect**: the bus owns the buffer; the SSE
  handler is just a transport. Reconnects with ``Last-Event-ID`` close
  any gap.

Event shape (kept narrow on purpose; future kinds are additive):

- ``id``: monotonically increasing int (starts at 1; 0 is "before any
  event so replay everything you can").
- ``kind``: one of the enumerated string constants below.
- ``ts``: ISO-8601 UTC string (``datetime.now(timezone.utc).isoformat()``).
- ``payload``: kind-specific dict.

Currently emitted kinds (Phase 3 Part E):

- ``session.created`` — payload is the session row from the store.
- ``session.message_appended`` — ``{session_id, role, text, tokens_in,
  tokens_out, native_handle}``. Fired post-Adapter return for the
  assistant role; pre-Adapter for the user role (so the UI can show the
  user's turn immediately while Claude takes 5-30s).
- ``session.cost_updated`` — ``{session_id, cost_tokens_in,
  cost_tokens_out}`` after each successful turn. Values are the
  *cumulative* totals on the session row, not the delta.
- ``session.closed`` — ``{session_id}``.

The bus is a process-local singleton — there is exactly one daemon, so
in-memory pub/sub is sufficient for v1.

Why SSE rather than WebSocket: every client→server action in
orchestration v1 already has a REST POST endpoint
(``/sessions/{id}/messages``, ``/sessions/{id}/close``, etc.). The
bidirectional channel a WebSocket gives us would have been unused. SSE
also has built-in browser auto-reconnect via ``EventSource``,
``Last-Event-ID`` replay, simpler debugging (``curl -N`` works), simpler
proxy traversal, and simpler future auth.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from starlette.requests import Request
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


# ── Event kind constants ──────────────────────────────────────────────────
EVENT_SESSION_CREATED = "session.created"
EVENT_SESSION_MESSAGE_APPENDED = "session.message_appended"
EVENT_SESSION_COST_UPDATED = "session.cost_updated"
EVENT_SESSION_CLOSED = "session.closed"

# Maximum events retained in the in-memory ring buffer for replay. 1000
# events is roughly an hour of brisk activity; subscribers reconnecting
# after longer gaps will silently miss the oldest events. Acceptable —
# the daemon REST endpoints are still the source of truth on full state.
MAX_BUFFER = 1000

# Keep-alive comment cadence. Every KEEPALIVE_INTERVAL_S we emit a comment
# line so idle proxies don't terminate the connection. SSE comments are
# silent to the browser parser.
KEEPALIVE_INTERVAL_S = 20.0

# Per-subscriber queue cap. An obscenely slow consumer should not pin
# arbitrary memory; if the queue overflows we drop the event for that
# subscriber rather than buffer unboundedly. The browser's auto-reconnect
# + Last-Event-ID will recover any dropped events from the ring buffer.
SUBSCRIBER_QUEUE_MAX = 1024


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class OrchestrationEventBus:
    """In-process pub/sub with monotonic ids and a ring buffer.

    Thread/async-safety: this is single-event-loop pub/sub. ``publish`` is
    sync (callable from any context); ``subscribe`` returns an
    :class:`asyncio.Queue` to be consumed by a single coroutine. The
    buffer + counter can be touched without a lock because Python's GIL
    plus the single-threaded event loop give us atomicity on the
    operations we care about (deque append, dict mutation, integer
    increment).

    Tests of behavior live in
    ``services/agents-mcp/tests/test_orchestration_events.py``.
    """

    def __init__(self, max_buffer: int = MAX_BUFFER):
        self._next_id: int = 1
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_buffer)
        self._subscribers: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._sub_seq: int = 0

    # ── Pub/sub API ──────────────────────────────────────────────────────

    def publish(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append an event to the buffer and fan it out to subscribers.

        Sync method so it can be called from any place that emits events
        (typically inside an ``async`` function but without needing to
        ``await``). Returns the constructed event dict for callers that
        want to log / introspect it.

        Subscriber queues that have overflowed (slow consumer) silently
        drop events for that one subscriber — we don't unsubscribe them
        here; the SSE handler handles its own teardown. The browser's
        ``EventSource`` will reconnect with ``Last-Event-ID`` and replay
        the dropped events from the ring buffer.
        """
        event = {
            "id": self._next_id,
            "kind": kind,
            "ts": _now_iso(),
            "payload": payload,
        }
        self._next_id += 1
        self._buffer.append(event)
        for client_id, queue in list(self._subscribers.items()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop this event for this subscriber; they'll recover on
                # the next Last-Event-ID reconnect. We log so operators can
                # see a slow client without it taking down the daemon.
                logger.warning(
                    "EventBus: dropping event %d for slow subscriber %s",
                    event["id"],
                    client_id,
                )
        return event

    def subscribe(self) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        """Register a new subscriber.

        Returns a ``(client_id, queue)`` pair. The caller is responsible
        for calling :meth:`unsubscribe` with the same id on disconnect.
        """
        self._sub_seq += 1
        client_id = f"sse-{self._sub_seq}"
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=SUBSCRIBER_QUEUE_MAX
        )
        self._subscribers[client_id] = queue
        return client_id, queue

    def unsubscribe(self, client_id: str) -> None:
        """Remove a subscriber. Idempotent."""
        self._subscribers.pop(client_id, None)

    def replay(self, since_id: int) -> list[dict[str, Any]]:
        """Return buffered events with id strictly greater than ``since_id``.

        Used on connect: if the client passes ``Last-Event-ID: <id>`` we
        flush everything newer that's still in the ring before flowing
        live events. ``since_id <= 0`` means "send me the whole buffer".
        """
        if since_id <= 0:
            return list(self._buffer)
        return [e for e in self._buffer if e["id"] > since_id]

    # ── Introspection ────────────────────────────────────────────────────

    @property
    def latest_event_id(self) -> int:
        """The id that will be assigned to the *next* event minus 1."""
        return self._next_id - 1

    @property
    def subscriber_count(self) -> int:
        """Number of currently-attached subscribers (introspection)."""
        return len(self._subscribers)

    @property
    def buffer_size(self) -> int:
        """Number of events currently in the ring buffer."""
        return len(self._buffer)


# ── Singleton glue ───────────────────────────────────────────────────────

_bus: Optional[OrchestrationEventBus] = None


def get_event_bus() -> OrchestrationEventBus:
    """Return (lazily creating) the process-wide event bus singleton.

    Tests that want isolation can construct their own
    :class:`OrchestrationEventBus` directly; only daemon hot paths go
    through this getter.
    """
    global _bus
    if _bus is None:
        _bus = OrchestrationEventBus()
    return _bus


def reset_event_bus_for_tests() -> None:
    """Reset the singleton — call from tests that share state by accident."""
    global _bus
    _bus = None


# ── SSE wire format ──────────────────────────────────────────────────────


def _format_sse_event(event: dict[str, Any]) -> bytes:
    """Format an event dict as an SSE frame.

    Wire format per W3C SSE spec:

        id: 43\\n
        event: session.message_appended\\n
        data: {"...": "..."}\\n
        \\n

    The trailing blank line is mandatory — it's the frame separator. Each
    field is one line, terminated by ``\\n``. ``data:`` carries the JSON
    body; ``id:`` is what the browser stores and echoes back as
    ``Last-Event-ID`` on reconnect.
    """
    payload = json.dumps(
        {
            "id": event["id"],
            "kind": event["kind"],
            "ts": event["ts"],
            "payload": event["payload"],
        },
        separators=(",", ":"),
    )
    return (
        f"id: {event['id']}\n"
        f"event: {event['kind']}\n"
        f"data: {payload}\n"
        "\n"
    ).encode("utf-8")


def _format_keepalive() -> bytes:
    """Return an SSE comment line that browsers silently ignore.

    Comments start with ``:`` and are useful for keeping the connection
    open through proxies that idle-kill silent streams.
    """
    return b": keepalive\n\n"


# ── SSE endpoint factory ─────────────────────────────────────────────────


def create_sse_endpoint(bus: Optional[OrchestrationEventBus] = None):
    """Return a Starlette endpoint coroutine for the SSE stream.

    Passing a ``bus`` is optional; if omitted we use the process-wide
    singleton via :func:`get_event_bus`. Tests that need an isolated bus
    should pass one in.

    The endpoint:

    1. Reads ``Last-Event-ID`` from the request headers (browsers set this
       automatically on ``EventSource`` reconnect).
    2. Replays buffered events with ``id > last_event_id`` before
       subscribing live.
    3. Streams live events as SSE frames forever, with a comment-line
       keep-alive every ``KEEPALIVE_INTERVAL_S`` seconds.
    4. On client disconnect, cleans up its subscriber from the bus.
    """

    async def sse_endpoint(request: Request) -> StreamingResponse:
        active_bus = bus if bus is not None else get_event_bus()

        # Parse Last-Event-ID. Browsers set this header on reconnect. We
        # also accept a ``?since=`` query param as a back-compat / curl
        # convenience knob.
        last_event_id = 0
        header_val = request.headers.get("last-event-id")
        if header_val:
            try:
                last_event_id = int(header_val)
            except ValueError:
                last_event_id = 0
        else:
            qs_val = request.query_params.get("since")
            if qs_val:
                try:
                    last_event_id = int(qs_val)
                except ValueError:
                    last_event_id = 0

        client_id, queue = active_bus.subscribe()
        logger.info(
            "EventBus SSE: client %s connected (last_event_id=%d, latest=%d)",
            client_id,
            last_event_id,
            active_bus.latest_event_id,
        )

        async def stream() -> AsyncIterator[bytes]:
            try:
                # 1. Replay any events the client missed.
                replay = active_bus.replay(last_event_id)
                for event in replay:
                    yield _format_sse_event(event)

                # 2. Stream live events forever, with periodic keep-alives.
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        event = await asyncio.wait_for(
                            queue.get(), timeout=KEEPALIVE_INTERVAL_S
                        )
                    except asyncio.TimeoutError:
                        # Idle period — emit a keep-alive comment so the
                        # connection doesn't get reaped by intermediaries.
                        yield _format_keepalive()
                        continue
                    yield _format_sse_event(event)
            finally:
                active_bus.unsubscribe(client_id)
                logger.info("EventBus SSE: client %s disconnected", client_id)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                # No caching — SSE is a live stream.
                "Cache-Control": "no-cache",
                # Persistent connection.
                "Connection": "keep-alive",
                # nginx-friendly: don't buffer the response.
                "X-Accel-Buffering": "no",
            },
        )

    return sse_endpoint


__all__ = [
    "EVENT_SESSION_CLOSED",
    "EVENT_SESSION_COST_UPDATED",
    "EVENT_SESSION_CREATED",
    "EVENT_SESSION_MESSAGE_APPENDED",
    "KEEPALIVE_INTERVAL_S",
    "MAX_BUFFER",
    "OrchestrationEventBus",
    "create_sse_endpoint",
    "get_event_bus",
    "reset_event_bus_for_tests",
]
