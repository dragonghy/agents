"""WebSocket event bus for real-time push to Display UI clients."""

import asyncio
import json
import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class EventBus:
    """Manages WebSocket connections and broadcasts events to all clients."""

    def __init__(self):
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)
        logger.info(f"WebSocket client connected ({len(self._clients)} total)")

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)
        logger.info(f"WebSocket client disconnected ({len(self._clients)} total)")

    async def broadcast(self, event_type: str, data: Any = None):
        """Broadcast an event to all connected clients."""
        if not self._clients:
            return
        message = json.dumps({"type": event_type, "data": data})
        disconnected = set()
        for ws in self._clients:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Global singleton
event_bus = EventBus()


async def websocket_endpoint(ws: WebSocket):
    """WebSocket handler for /ws route."""
    await event_bus.connect(ws)
    try:
        while True:
            # Keep connection alive, ignore incoming messages
            await ws.receive_text()
    except WebSocketDisconnect:
        event_bus.disconnect(ws)
    except Exception:
        event_bus.disconnect(ws)
