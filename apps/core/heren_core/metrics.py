"""MetricsCollector — the server's vital signs over time.

Every `interval_s` it runs `get_metrics` on each online device that declares it (through the same
dispatcher the UI uses, so audit/risk rules apply — get_metrics is LOW), stores the numeric fields
in SQLite (`metrics` table, pruned to `keep_s`) and emits `device.metrics` on the bus so the panel
updates live. Failures are logged, never fatal: a broken device just has a gap in its history.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from heren_core.actions import Dispatcher
from heren_core.bus import EventBus
from heren_core.protocol import ActionRequest, ActionStatus, DeviceStatus
from heren_core.storage import Storage

log = logging.getLogger("heren.metrics")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    device_id TEXT NOT NULL,
    ts        REAL NOT NULL,
    data      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS metrics_device_ts ON metrics(device_id, ts);
"""


def _numeric_only(sample: dict[str, Any]) -> dict[str, float | int]:
    """Only numbers are worth a time series (disks list etc. live in `latest`, not history)."""
    return {k: v for k, v in sample.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


class MetricsCollector:
    def __init__(self, *, store: Storage, bus: EventBus, dispatcher: Dispatcher,
                 interval_s: float = 30.0, keep_s: float = 24 * 3600.0,
                 now: Callable[[], float] = time.time) -> None:
        self.store = store
        self.bus = bus
        self.dispatcher = dispatcher
        self.interval_s = interval_s
        self.keep_s = keep_s
        self._now = now
        self._latest: dict[str, dict[str, Any]] = {}
        self._ready = False

    async def _ensure_schema(self) -> None:
        if not self._ready:
            await self.store.db.executescript(_SCHEMA)
            await self.store.db.commit()
            self._ready = True

    async def latest(self) -> dict[str, dict[str, Any]]:
        """Full last sample per device (including non-numeric fields like `disks`)."""
        return dict(self._latest)

    async def poll_once(self) -> None:
        await self._ensure_schema()
        for d in await self.store.list_devices():
            if d.status != DeviceStatus.ONLINE or "get_metrics" not in d.capabilities:
                continue
            try:
                res = await self.dispatcher.dispatch(ActionRequest(device_id=d.device_id, action="get_metrics", requested_by="metrics"))
            except Exception as e:  # dispatcher-level failure (timeout, disconnect)
                log.info("metrics %s: %s", d.device_id, e)
                continue
            if res.status != ActionStatus.COMPLETED:
                log.info("metrics %s failed: %s", d.device_id, res.error)
                continue
            ts = self._now()
            sample = dict(res.output)
            self._latest[d.device_id] = sample | {"ts": ts}
            await self.store.db.execute("INSERT INTO metrics(device_id, ts, data) VALUES(?,?,?)",
                                        (d.device_id, ts, json.dumps(_numeric_only(sample))))
            await self.bus.emit("device.metrics", device_id=d.device_id, ts=ts, metrics=sample)
        await self.store.db.execute("DELETE FROM metrics WHERE ts < ?", (self._now() - self.keep_s,))
        await self.store.db.commit()

    async def history(self, device_id: str, since_s: float = 3600.0) -> list[dict[str, Any]]:
        await self._ensure_schema()
        cur = await self.store.db.execute(
            "SELECT ts, data FROM metrics WHERE device_id=? AND ts>=? ORDER BY ts",
            (device_id, self._now() - since_s))
        return [{"ts": row["ts"], **json.loads(row["data"])} for row in await cur.fetchall()]

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                log.exception("metrics poll failed")
            await asyncio.sleep(self.interval_s)
