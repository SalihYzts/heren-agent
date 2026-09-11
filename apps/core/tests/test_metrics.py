"""MetricsCollector: polls get_metrics on online devices, keeps a bounded history in SQLite."""
import asyncio

import pytest

from heren_core.bus import EventBus
from heren_core.metrics import MetricsCollector
from heren_core.protocol import ActionRequest, ActionResult, ActionStatus, Device, DeviceStatus
from heren_core.storage import Storage


class FakeDispatcher:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.sample = {"cpu_pct": 12, "ram_pct": 59, "disk_pct": 53, "temp_c": 70, "load1": 1.0,
                       "net_rx_bytes": 1000, "net_tx_bytes": 500, "disks": [{"mount": "/", "pct": 53}]}

    async def dispatch(self, req: ActionRequest) -> ActionResult:
        self.calls.append((req.device_id, req.action))
        if req.device_id == "broken":
            return ActionResult(request_id=req.request_id, status=ActionStatus.FAILED, error="boom")
        return ActionResult(request_id=req.request_id, status=ActionStatus.COMPLETED, output=dict(self.sample))


@pytest.fixture
async def env(tmp_path):
    store = Storage(tmp_path / "m.db")
    await store.open()
    await store.upsert_device(Device(device_id="srv", name="Srv", platform="linux", status=DeviceStatus.ONLINE, public_key="k", capabilities=["get_metrics"]))
    await store.upsert_device(Device(device_id="off", name="Off", platform="linux", status=DeviceStatus.OFFLINE, public_key="k", capabilities=["get_metrics"]))
    await store.upsert_device(Device(device_id="nometrics", name="NoM", platform="linux", status=DeviceStatus.ONLINE, public_key="k", capabilities=["get_status"]))
    await store.upsert_device(Device(device_id="broken", name="Broken", platform="linux", status=DeviceStatus.ONLINE, public_key="k", capabilities=["get_metrics"]))
    bus = EventBus()
    disp = FakeDispatcher()
    clock = {"t": 1000.0}
    col = MetricsCollector(store=store, bus=bus, dispatcher=disp, interval_s=30, keep_s=3600, now=lambda: clock["t"])
    yield store, bus, disp, col, clock
    await store.close()


async def test_poll_samples_only_online_devices_that_can_report_and_emits_on_bus(env):
    store, bus, disp, col, clock = env
    seen = []
    bus.subscribe("device.metrics", lambda e: seen.append(e.payload))
    await col.poll_once()
    assert sorted(disp.calls) == [("broken", "get_metrics"), ("srv", "get_metrics")]
    assert len(seen) == 1 and seen[0]["device_id"] == "srv" and seen[0]["metrics"]["cpu_pct"] == 12
    latest = await col.latest()
    assert latest["srv"]["cpu_pct"] == 12 and "broken" not in latest


async def test_history_is_stored_per_device_and_pruned(env):
    store, bus, disp, col, clock = env
    for i in range(5):
        disp.sample["cpu_pct"] = i * 10
        await col.poll_once()
        clock["t"] += 600                      # 10 min apart
    rows = await col.history("srv", since_s=3600)
    assert [r["cpu_pct"] for r in rows] == [0, 10, 20, 30, 40]
    assert rows[0]["ts"] == 1000.0 and rows[-1]["ts"] == 1000.0 + 4 * 600
    # keep_s=3600: after another hour the first samples fall off
    clock["t"] += 3600
    await col.poll_once()
    rows = await col.history("srv", since_s=10 * 3600)
    assert rows[0]["cpu_pct"] >= 30, "samples older than keep_s pruned"
    assert await col.history("nobody", since_s=3600) == []


async def test_history_only_keeps_numeric_fields_and_disks_summary(env):
    store, bus, disp, col, clock = env
    disp.sample["hostname"] = "srv"           # strings are not plotted
    await col.poll_once()
    row = (await col.history("srv", since_s=60))[0]
    assert "hostname" not in row and row["disk_pct"] == 53 and "disks" not in row


async def test_run_loop_polls_on_interval_and_survives_failures(env):
    store, bus, disp, col, clock = env
    col.interval_s = 0.02
    task = asyncio.create_task(col.run())
    await asyncio.sleep(0.11)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert len([c for c in disp.calls if c[0] == "srv"]) >= 3
