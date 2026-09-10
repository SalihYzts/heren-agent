"""In-process async event bus.

Patterns: exact ("device.online"), namespace prefix ("device.*"), or "*".
Handlers may be sync or async; a failing handler is logged and never blocks others.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from heren_core.protocol import Event

log = logging.getLogger("heren.bus")

Handler = Callable[[Event], Any]


def _matches(pattern: str, event_type: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


class EventBus:
    def __init__(self) -> None:
        self._subs: list[tuple[str, Handler]] = []

    def subscribe(self, pattern: str, handler: Handler) -> Callable[[], None]:
        entry = (pattern, handler)
        self._subs.append(entry)

        def unsubscribe() -> None:
            if entry in self._subs:
                self._subs.remove(entry)

        return unsubscribe

    async def publish(self, event: Event) -> None:
        for pattern, handler in list(self._subs):
            if not _matches(pattern, event.type):
                continue
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("event handler failed for %s", event.type)

    async def emit(self, event_type: str, **payload: Any) -> Event:
        event = Event(type=event_type, payload=payload)
        await self.publish(event)
        return event

    def emit_nowait(self, event_type: str, **payload: Any) -> None:
        asyncio.get_running_loop().create_task(self.emit(event_type, **payload))
