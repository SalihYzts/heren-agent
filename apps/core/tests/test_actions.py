"""Action pipeline: risk gate → (approval) → dispatch → result → audit.

The dispatcher is injected so this file tests the *policy* with a fake transport,
not the WebSocket plumbing.
"""
import asyncio

import pytest

from heren_core.actions import ActionService, ApprovalNotFound
from heren_core.bus import EventBus
from heren_core.protocol import ActionRequest, ActionResult, ActionStatus, Device, DeviceStatus
from heren_core.storage import Storage


class FakeDispatcher:
    """Stands in for the device gateway. Records what it was asked to run."""

    def __init__(self):
        self.calls: list[ActionRequest] = []
        self.online: set[str] = {"dev-1"}
        self.fail_next = False

    def is_online(self, device_id: str) -> bool:
        return device_id in self.online

    async def dispatch(self, req: ActionRequest) -> ActionResult:
        self.calls.append(req)
        if self.fail_next:
            self.fail_next = False
            return ActionResult(request_id=req.request_id, status=ActionStatus.FAILED, error="agent said no")
        return ActionResult(request_id=req.request_id, status=ActionStatus.COMPLETED, output={"ok": True})


@pytest.fixture
async def svc(tmp_path):
    store = Storage(tmp_path / "t.db")
    await store.open()
    await store.upsert_device(Device(device_id="dev-1", name="PC", platform="linux", public_key="ab" * 32))
    await store.set_device_status("dev-1", DeviceStatus.ONLINE)
    bus = EventBus()
    disp = FakeDispatcher()
    s = ActionService(store=store, bus=bus, dispatcher=disp, approval_ttl_s=60, critical_enabled=False)
    s._disp = disp  # test handle
    s._events = []
    bus.subscribe("*", lambda e: s._events.append(e.type))
    yield s
    await store.close()


async def test_low_risk_runs_immediately_and_is_audited(svc):
    res = await svc.submit(ActionRequest(device_id="dev-1", action="get_status"))
    assert res.status == ActionStatus.COMPLETED
    assert len(svc._disp.calls) == 1
    rows = await svc.store.list_audit()
    assert rows[0]["action"] == "get_status" and rows[0]["approved_by"] is None
    assert "device.action.started" in svc._events and "device.action.completed" in svc._events


async def test_medium_risk_runs_without_approval(svc):
    res = await svc.submit(ActionRequest(device_id="dev-1", action="restart_service", params={"name": "nginx"}))
    assert res.status == ActionStatus.COMPLETED


async def test_high_risk_waits_for_approval_and_does_not_dispatch(svc):
    res = await svc.submit(ActionRequest(device_id="dev-1", action="shutdown"))
    assert res.status == ActionStatus.AWAITING_APPROVAL
    assert svc._disp.calls == []
    assert "ui.approval.needed" in svc._events
    pending = await svc.list_pending_approvals()
    assert [p.action for p in pending] == ["shutdown"]


async def test_approving_high_risk_dispatches_and_records_approver(svc):
    res = await svc.submit(ActionRequest(device_id="dev-1", action="shutdown"))
    final = await svc.approve(res.request_id, approved_by="ui:salih")
    assert final.status == ActionStatus.COMPLETED
    assert svc._disp.calls[0].action == "shutdown"
    row = (await svc.store.list_audit())[0]
    assert row["approved_by"] == "ui:salih" and row["risk"] == "high"


async def test_denying_high_risk_never_dispatches(svc):
    res = await svc.submit(ActionRequest(device_id="dev-1", action="shutdown"))
    final = await svc.deny(res.request_id, denied_by="ui:salih")
    assert final.status == ActionStatus.DENIED
    assert svc._disp.calls == []
    assert (await svc.store.get_action(res.request_id)).status == ActionStatus.DENIED


async def test_approving_unknown_or_already_resolved_request_raises(svc):
    with pytest.raises(ApprovalNotFound):
        await svc.approve("req_nope", approved_by="ui")
    res = await svc.submit(ActionRequest(device_id="dev-1", action="shutdown"))
    await svc.deny(res.request_id, denied_by="ui")
    with pytest.raises(ApprovalNotFound):
        await svc.approve(res.request_id, approved_by="ui")


async def test_approval_expires_after_ttl(tmp_path):
    store = Storage(tmp_path / "t.db")
    await store.open()
    await store.upsert_device(Device(device_id="dev-1", name="PC", platform="linux", public_key="ab" * 32))
    disp = FakeDispatcher()
    clock = [1000.0]
    svc = ActionService(store=store, bus=EventBus(), dispatcher=disp, approval_ttl_s=60,
                        critical_enabled=False, _now=lambda: clock[0])
    res = await svc.submit(ActionRequest(device_id="dev-1", action="shutdown"))
    clock[0] += 61
    await svc.expire_stale()
    assert (await store.get_action(res.request_id)).status == ActionStatus.EXPIRED
    with pytest.raises(ApprovalNotFound):
        await svc.approve(res.request_id, approved_by="ui")
    assert disp.calls == []
    await store.close()


async def test_critical_is_rejected_while_disabled(svc):
    res = await svc.submit(ActionRequest(device_id="dev-1", action="format_disk"))
    assert res.status == ActionStatus.DENIED
    assert "critical" in (res.error or "").lower()
    assert svc._disp.calls == []


async def test_offline_device_returns_device_offline_without_dispatch(svc):
    svc._disp.online.clear()
    res = await svc.submit(ActionRequest(device_id="dev-1", action="get_status"))
    assert res.status == ActionStatus.DEVICE_OFFLINE
    assert svc._disp.calls == []


async def test_unknown_device_is_rejected(svc):
    res = await svc.submit(ActionRequest(device_id="ghost", action="get_status"))
    assert res.status == ActionStatus.FAILED
    assert "unknown device" in res.error


async def test_agent_failure_is_audited_with_error(svc):
    svc._disp.fail_next = True
    res = await svc.submit(ActionRequest(device_id="dev-1", action="get_status"))
    assert res.status == ActionStatus.FAILED
    row = (await svc.store.list_audit())[0]
    assert row["result"] == "failed" and row["error"] == "agent said no"
    assert "device.action.failed" in svc._events


async def test_hermes_cannot_self_approve(svc):
    res = await svc.submit(ActionRequest(device_id="dev-1", action="shutdown", requested_by="hermes"))
    with pytest.raises(PermissionError):
        await svc.approve(res.request_id, approved_by="hermes")
    assert svc._disp.calls == []
