"""CharacterHost — glue between the event bus and the pure CharacterEngine.

Inbound (bus → engine):
    character.touch / wakeword.detected   → touch / wake_word
    hermes.thinking / hermes.speaking / hermes.done
    hermes.tool.started / .completed / .failed
    device.action.completed, device.offline
    ui.approval.needed / ui.approval.resolved
Outbound (engine → bus):
    character.state {schema, activity, mood, attention, energy}   — only on change

The engine never sees the bus; the bus never sees engine internals.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from collections.abc import Awaitable
from datetime import datetime
from typing import Any

from heren_core.bus import EventBus
from heren_core.character import CharacterConfig, CharacterEngine
from heren_core.protocol import Event

log = logging.getLogger("heren.character")


class CharacterHost:
    def __init__(self, *, bus: EventBus, cfg: CharacterConfig | None = None,
                 now: Callable[[], datetime] = datetime.now, tick_interval_s: float = 1.0,
                 save_state: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
                 load_state: Callable[[], Awaitable[dict[str, Any] | None]] | None = None) -> None:
        self.bus = bus
        self.engine = CharacterEngine(cfg, now=now)
        self.tick_interval_s = tick_interval_s
        self._save = save_state
        self._load = load_state
        self._saved: dict[str, Any] | None = None
        self._published: dict[str, Any] | None = None
        self._unsub: Callable[[], None] | None = None
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ wiring

    _HANDLERS: dict[str, str] = {
        "character.touch": "touch",
        "wakeword.detected": "wake_word",
        "hermes.thinking": "assistant_thinking",
        "hermes.speaking": "assistant_speaking",
        "hermes.done": "assistant_done",
        "hermes.tool.started": "tool_started",
        "hermes.tool.completed": "tool_finished",
        "hermes.tool.failed": "tool_failed",
        "device.action.completed": "device_action_completed",
        "device.offline": "device_offline",
        "ui.approval.needed": "approval_needed",
        "ui.approval.resolved": "approval_resolved",
        "voice.playback.started": "speech_started",
        "voice.playback.finished": "speech_finished",
    }

    def attach(self) -> None:
        self._unsub = self.bus.subscribe("*", self._on_event)

    async def restore(self) -> None:
        """Load the persisted slow state (energy, sleep debt, asleep?) before the first tick."""
        if self._load is None:
            return
        try:
            saved = await self._load()
        except Exception:
            log.exception("character state load failed; starting fresh")
            return
        self.engine.restore_state(saved)
        self._saved = self.engine.export_state()

    async def _persist_if_changed(self) -> None:
        if self._save is None:
            return
        d = self.engine.export_state()
        if d != self._saved:
            self._saved = d
            try:
                await self._save(d)
            except Exception:
                log.exception("character state save failed")

    def detach(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _on_event(self, e: Event) -> None:
        method = self._HANDLERS.get(e.type)
        if method is None:
            return  # includes our own character.* output
        getattr(self.engine, method)()
        await self.publish_if_changed()
        await self._persist_if_changed()

    # ------------------------------------------------------------ output

    def snapshot(self) -> dict[str, Any]:
        return self.engine.state().to_dict()

    async def publish_if_changed(self) -> None:
        d = self.snapshot()
        if d != self._published:
            self._published = d
            await self.bus.emit("character.state", **d)

    # ------------------------------------------------------------ periodic tick

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.detach()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick_interval_s)
            try:
                self.engine.tick()
                await self.publish_if_changed()
                await self._persist_if_changed()
            except Exception:
                log.exception("character tick failed")
