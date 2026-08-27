from __future__ import annotations

import asyncio
from typing import Any


class EventHub:
    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subs:
            self._subs.remove(queue)

    def publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subs):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:
                    pass
