"""SQLite storage: devices, action requests, audit log, settings."""
import pytest

from heren_core.protocol import ActionRequest, ActionStatus, Device, DeviceStatus
from heren_core.storage import Storage


@pytest.fixture
async def store(tmp_path):
    s = Storage(tmp_path / "heren.db")
    await s.open()
    yield s
    await s.close()


def _device(i="dev-1"):
    return Device(device_id=i, name="MAIN PC", platform="linux", public_key="ab" * 32)


async def test_device_upsert_and_get(store):
    await store.upsert_device(_device())
    got = await store.get_device("dev-1")
    assert got is not None
    assert got.name == "MAIN PC"
    assert got.status == DeviceStatus.OFFLINE
    assert await store.get_device("nope") is None


async def test_device_upsert_updates_existing(store):
    await store.upsert_device(_device())
    await store.upsert_device(_device().model_copy(update={"name": "RENAMED"}))
    assert (await store.get_device("dev-1")).name == "RENAMED"
    assert len(await store.list_devices()) == 1


async def test_set_device_status_records_last_seen(store):
    await store.upsert_device(_device())
    await store.set_device_status("dev-1", DeviceStatus.ONLINE, last_seen=1234.5)
    d = await store.get_device("dev-1")
    assert d.status == DeviceStatus.ONLINE
    assert d.last_seen == 1234.5


async def test_action_request_roundtrip(store):
    req = ActionRequest(device_id="dev-1", action="shutdown", requested_by="hermes")
    await store.save_action(req)
    got = await store.get_action(req.request_id)
    assert got == req


async def test_action_status_update_and_list_by_status(store):
    a = ActionRequest(device_id="dev-1", action="shutdown")
    b = ActionRequest(device_id="dev-1", action="get_status")
    await store.save_action(a)
    await store.save_action(b)
    await store.update_action_status(a.request_id, ActionStatus.AWAITING_APPROVAL)
    pending = await store.list_actions(status=ActionStatus.AWAITING_APPROVAL)
    assert [p.request_id for p in pending] == [a.request_id]


async def test_audit_log_appends_and_reads_newest_first(store):
    await store.audit("req_1", "dev-1", "shutdown", risk="high", approved_by="ui", result="completed", duration_ms=10)
    await store.audit("req_2", "dev-1", "get_status", risk="low", approved_by=None, result="completed", duration_ms=3)
    rows = await store.list_audit(limit=10)
    assert [r["request_id"] for r in rows] == ["req_2", "req_1"]
    assert rows[1]["approved_by"] == "ui"


async def test_audit_redacts_secret_looking_params(store):
    await store.audit(
        "req_1", "dev-1", "launch_app", risk="medium", approved_by=None, result="completed",
        duration_ms=1, params={"app": "code", "password": "hunter2", "api_token": "x"},
    )
    row = (await store.list_audit(limit=1))[0]
    assert row["params"]["app"] == "code"
    assert row["params"]["password"] == "[redacted]"
    assert row["params"]["api_token"] == "[redacted]"


async def test_settings_get_set_with_default(store):
    assert await store.get_setting("wake_word", "Heren") == "Heren"
    await store.set_setting("wake_word", "Hermes")
    assert await store.get_setting("wake_word", "Heren") == "Hermes"
