"""SSE event broadcaster for real-time Hub updates."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator


class EventBroadcaster:
    """Publishes network events to connected Hub browsers via SSE."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Push an event to all connected SSE subscribers."""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        dead: list[asyncio.Queue] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(queue)
        for q in dead:
            self._subscribers.remove(q)

    async def subscribe(self) -> AsyncIterator[str]:
        """Yield SSE-formatted events as they arrive."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield (
                    f"event: {event['type']}\n"
                    f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
                )
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
