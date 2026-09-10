"""ActionService — the single path every action takes (UI button, Hermes MCP, macro).

    submit(req)
      ├─ unknown device            → FAILED
      ├─ risk CRITICAL & disabled  → DENIED
      ├─ risk HIGH/CRITICAL        → AWAITING_APPROVAL  (ui.approval.needed)
      └─ LOW/MEDIUM                → _run(req)
    approve(id, by) / deny(id, by) → _run / DENIED
    _run: device offline → DEVICE_OFFLINE, else dispatcher.dispatch → audit + events
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from heren_core.bus import EventBus
from heren_core.protocol import ActionRequest, ActionResult, ActionStatus, RiskLevel
from heren_core.storage import Storage

log = logging.getLogger("heren.actions")

NEEDS_APPROVAL = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})


class Dispatcher(Protocol):
    def is_online(self, device_id: str) -> bool: ...
    async def dispatch(self, req: ActionRequest) -> ActionResult: ...


class ApprovalNotFound(Exception):
    pass


class ActionService:
    def __init__(self, *, store: Storage, bus: EventBus, dispatcher: Dispatcher,
                 approval_ttl_s: float, critical_enabled: bool,
                 _now: Callable[[], float] = time.time) -> None:
        self.store = store
        self.bus = bus
        self.dispatcher = dispatcher
        self.approval_ttl_s = approval_ttl_s
        self.critical_enabled = critical_enabled
        self._now = _now
        self._approval_deadlines: dict[str, float] = {}

    # ----------------------------------------------------------------- entry

    async def submit(self, req: ActionRequest) -> ActionResult:
        if await self.store.get_device(req.device_id) is None:
            return await self._finish(req, ActionResult(
                request_id=req.request_id, status=ActionStatus.FAILED, error="unknown device"))

        await self.store.save_action(req)
        risk = req.risk

        if risk == RiskLevel.CRITICAL and not self.critical_enabled:
            return await self._finish(req, ActionResult(
                request_id=req.request_id, status=ActionStatus.DENIED,
                error="critical actions are disabled"))

        if risk in NEEDS_APPROVAL:
            expires_at = self._now() + self.approval_ttl_s
            self._approval_deadlines[req.request_id] = expires_at
            await self.store.update_action_status(req.request_id, ActionStatus.AWAITING_APPROVAL)
            await self.bus.emit("ui.approval.needed", request_id=req.request_id,
                                device_id=req.device_id, action=req.action, params=req.params,
                                risk=risk, requested_by=req.requested_by,
                                expires_at=expires_at)
            return ActionResult(request_id=req.request_id, status=ActionStatus.AWAITING_APPROVAL)

        return await self._run(req)

    # ----------------------------------------------------------------- approvals

    async def list_pending_approvals(self) -> list[ActionRequest]:
        return await self.store.list_actions(status=ActionStatus.AWAITING_APPROVAL)

    async def approve(self, request_id: str, *, approved_by: str) -> ActionResult:
        if approved_by.startswith("hermes"):
            raise PermissionError("the agent cannot approve its own requests")
        req = await self._take_pending(request_id)
        req = req.model_copy(update={"approved_by": approved_by, "status": ActionStatus.APPROVED})
        await self.store.update_action_status(request_id, ActionStatus.APPROVED, approved_by=approved_by)
        await self.bus.emit("ui.approval.resolved", request_id=request_id, approved=True, by=approved_by)
        return await self._run(req)

    async def deny(self, request_id: str, *, denied_by: str) -> ActionResult:
        req = await self._take_pending(request_id)
        await self.bus.emit("ui.approval.resolved", request_id=request_id, approved=False, by=denied_by)
        return await self._finish(req, ActionResult(
            request_id=request_id, status=ActionStatus.DENIED, error=f"denied by {denied_by}"),
            approved_by=denied_by)

    async def expire_stale(self) -> int:
        now = self._now()
        n = 0
        for req in await self.list_pending_approvals():
            deadline = self._approval_deadlines.get(req.request_id, req.created_at + self.approval_ttl_s)
            if deadline < now:
                self._approval_deadlines.pop(req.request_id, None)
                await self._finish(req, ActionResult(
                    request_id=req.request_id, status=ActionStatus.EXPIRED, error="approval timed out"))
                n += 1
        return n

    async def _take_pending(self, request_id: str) -> ActionRequest:
        self._approval_deadlines.pop(request_id, None)
        req = await self.store.get_action(request_id)
        if req is None or req.status != ActionStatus.AWAITING_APPROVAL:
            raise ApprovalNotFound(request_id)
        return req

    # ----------------------------------------------------------------- run

    async def _run(self, req: ActionRequest) -> ActionResult:
        if not self.dispatcher.is_online(req.device_id):
            return await self._finish(req, ActionResult(
                request_id=req.request_id, status=ActionStatus.DEVICE_OFFLINE, error="device offline"))

        await self.store.update_action_status(req.request_id, ActionStatus.RUNNING)
        await self.bus.emit("device.action.started", request_id=req.request_id,
                            device_id=req.device_id, action=req.action)
        t0 = self._now()
        try:
            result = await self.dispatcher.dispatch(req)
        except Exception as e:  # transport failure — never leak as a crash
            log.exception("dispatch failed")
            result = ActionResult(request_id=req.request_id, status=ActionStatus.FAILED, error=str(e))
        if result.duration_ms is None:
            result = result.model_copy(update={"duration_ms": int((self._now() - t0) * 1000)})
        return await self._finish(req, result)

    async def _finish(self, req: ActionRequest, result: ActionResult,
                      approved_by: str | None = None) -> ActionResult:
        await self.store.update_action_status(req.request_id, result.status)
        await self.store.audit(
            req.request_id, req.device_id, req.action, risk=req.risk,
            approved_by=approved_by or req.approved_by, result=result.status,
            duration_ms=result.duration_ms, error=result.error, params=req.params,
        )
        topic = {
            ActionStatus.COMPLETED: "device.action.completed",
            ActionStatus.FAILED: "device.action.failed",
            ActionStatus.DEVICE_OFFLINE: "device.action.failed",
            ActionStatus.DENIED: "device.action.denied",
            ActionStatus.EXPIRED: "device.action.expired",
        }.get(result.status, "device.action.failed")
        await self.bus.emit(topic, request_id=req.request_id, device_id=req.device_id,
                            action=req.action, status=result.status, error=result.error,
                            output=result.output)
        return result
