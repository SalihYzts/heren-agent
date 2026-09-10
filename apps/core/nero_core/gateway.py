"""Device gateway — agents connect *to* core (outbound WS), never listen.

Session lifecycle:
    connect(conn) → sid
    hello {device_id, name, platform, public_key, capabilities, pairing_code?}
        unknown device + valid code → register; unknown without code → close
        known device: public_key must match the registered one
    → welcome {core_public_key}
    signed Envelope frames: heartbeat, action.result, event
    core → agent: signed Envelope action.request

Transport is abstracted behind `Conn` (send_json/close) so the policy is testable in-memory.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from nero_core.bus import EventBus
from nero_core.protocol import ActionRequest, ActionResult, ActionStatus, Device, DeviceStatus, Envelope
from nero_core.security import KeyPair, ReplayError, ReplayGuard, SignatureError, sign, verify
from nero_core.storage import Storage

log = logging.getLogger("nero.gateway")


class Conn(Protocol):
    async def send_json(self, data: dict) -> None: ...
    async def close(self, code: int = 1000, reason: str = "") -> None: ...


class PairingError(Exception):
    pass


@dataclass
class Session:
    sid: str
    conn: Conn
    device_id: str | None = None
    public_key: str | None = None
    last_seen: float = 0.0
    pending: dict[str, asyncio.Future[ActionResult]] = field(default_factory=dict)


class DeviceGateway:
    def __init__(self, *, store: Storage, bus: EventBus, core_key: KeyPair,
                 heartbeat_timeout_s: float, action_timeout_s: float,
                 pairing_code_ttl_s: float = 300.0,
                 _now: Callable[[], float] = time.time) -> None:
        self.store = store
        self.bus = bus
        self.core_key = core_key
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.action_timeout_s = action_timeout_s
        self.pairing_code_ttl_s = pairing_code_ttl_s
        self._now = _now
        self._sessions: dict[str, Session] = {}
        self._by_device: dict[str, str] = {}  # device_id → sid
        self._pairing_codes: dict[str, float] = {}  # code → expires_at
        self._replay = ReplayGuard(_now=_now)

    # ----------------------------------------------------------------- pairing

    def new_pairing_code(self) -> str:
        code = f"{secrets.randbelow(10**6):06d}"
        self._pairing_codes[code] = self._now() + self.pairing_code_ttl_s
        return code

    def _consume_pairing_code(self, code: str | None) -> bool:
        if not code:
            return False
        exp = self._pairing_codes.pop(code, None)
        return exp is not None and exp >= self._now()

    # ----------------------------------------------------------------- sessions

    async def connect(self, conn: Conn) -> str:
        sid = secrets.token_urlsafe(8)
        self._sessions[sid] = Session(sid=sid, conn=conn, last_seen=self._now())
        return sid

    async def disconnect(self, sid: str) -> None:
        s = self._sessions.pop(sid, None)
        if s is None:
            return
        for fut in s.pending.values():
            if not fut.done():
                fut.set_result(ActionResult(request_id="?", status=ActionStatus.DEVICE_OFFLINE,
                                            error="agent disconnected"))
        if s.device_id and self._by_device.get(s.device_id) == sid:
            del self._by_device[s.device_id]
            await self.store.set_device_status(s.device_id, DeviceStatus.OFFLINE)
            await self.bus.emit("device.offline", device_id=s.device_id)

    def is_online(self, device_id: str) -> bool:
        return device_id in self._by_device

    def session_count(self, device_id: str) -> int:
        return 1 if device_id in self._by_device else 0

    async def reap_dead_sessions(self) -> int:
        cutoff = self._now() - self.heartbeat_timeout_s
        dead = [s for s in self._sessions.values() if s.last_seen < cutoff]
        for s in dead:
            await s.conn.close(4000, "heartbeat timeout")
            await self.disconnect(s.sid)
        return len(dead)

    # ----------------------------------------------------------------- inbound

    async def handle_message(self, sid: str, data: dict[str, Any]) -> None:
        s = self._sessions.get(sid)
        if s is None:
            return
        if s.device_id is None:
            if data.get("type") != "hello":
                await self._reject(s, "expected hello")
                return
            await self._handle_hello(s, data)
            return
        try:
            env = Envelope.model_validate(data)
        except ValidationError:
            await s.conn.send_json({"type": "error", "reason": "malformed envelope"})
            return
        if env.device_id != s.device_id:
            await s.conn.send_json({"type": "error", "reason": "device_id mismatch"})
            return
        try:
            verify(env, s.public_key or "")
        except SignatureError:
            await s.conn.send_json({"type": "error", "reason": "bad signature"})
            return
        try:
            self._replay.check(env)
        except ReplayError as e:
            await s.conn.send_json({"type": "error", "reason": f"replay rejected: {e}"})
            return
        s.last_seen = self._now()
        await self._dispatch_inbound(s, env)

    async def _handle_hello(self, s: Session, h: dict[str, Any]) -> None:
        device_id = h.get("device_id")
        public_key = h.get("public_key")
        if not device_id or not public_key:
            await self._reject(s, "hello missing device_id/public_key")
            return
        known = await self.store.get_device(device_id)
        if known is None:
            if not self._consume_pairing_code(h.get("pairing_code")):
                await self._reject(s, "unknown device: valid pairing code required")
                return
            try:
                known = Device(device_id=device_id, name=h.get("name", device_id),
                               platform=h.get("platform", "unknown"), public_key=public_key,
                               capabilities=list(h.get("capabilities", [])))
            except ValidationError as e:
                await self._reject(s, f"invalid hello: {e}")
                return
            await self.store.upsert_device(known)
            await self.bus.emit("device.paired", device_id=device_id, name=known.name)
        elif known.public_key != public_key:
            await self._reject(s, "public key does not match registered device key")
            return

        # replace any stale session for this device
        old_sid = self._by_device.get(device_id)
        if old_sid and old_sid != s.sid:
            old = self._sessions.pop(old_sid, None)
            if old:
                await old.conn.close(4001, "replaced by new session")

        s.device_id = device_id
        s.public_key = public_key
        s.last_seen = self._now()
        self._by_device[device_id] = s.sid
        await self.store.set_device_status(device_id, DeviceStatus.ONLINE, last_seen=s.last_seen)
        await s.conn.send_json({"type": "welcome", "core_public_key": self.core_key.public_key_hex,
                                "heartbeat_interval_s": max(1.0, self.heartbeat_timeout_s / 3)})
        await self.bus.emit("device.online", device_id=device_id, platform=known.platform)

    async def _reject(self, s: Session, reason: str) -> None:
        await s.conn.close(4003, reason)
        self._sessions.pop(s.sid, None)

    async def _dispatch_inbound(self, s: Session, env: Envelope) -> None:
        assert s.device_id
        if env.type == "heartbeat":
            await self.store.set_device_status(s.device_id, DeviceStatus.ONLINE, last_seen=s.last_seen)
            await self.bus.emit("device.metrics", device_id=s.device_id, **env.payload)
        elif env.type == "action.result":
            rid = env.payload.get("request_id", "")
            fut = s.pending.pop(rid, None)
            if fut is None or fut.done():
                log.debug("result for unknown/finished request %s", rid)
                return
            try:
                fut.set_result(ActionResult(
                    request_id=rid, status=ActionStatus(env.payload.get("status", "failed")),
                    output=env.payload.get("output") or {}, error=env.payload.get("error"),
                    duration_ms=env.payload.get("duration_ms")))
            except (ValueError, ValidationError) as e:
                fut.set_result(ActionResult(request_id=rid, status=ActionStatus.FAILED,
                                            error=f"malformed result: {e}"))
        elif env.type == "event":
            await self.bus.emit("device.event", device_id=s.device_id, **env.payload)
        else:
            await s.conn.send_json({"type": "error", "reason": f"unknown envelope type {env.type}"})

    # ----------------------------------------------------------------- outbound

    async def dispatch(self, req: ActionRequest) -> ActionResult:
        sid = self._by_device.get(req.device_id)
        s = self._sessions.get(sid) if sid else None
        if s is None:
            return ActionResult(request_id=req.request_id, status=ActionStatus.DEVICE_OFFLINE,
                                error="device offline")
        fut: asyncio.Future[ActionResult] = asyncio.get_running_loop().create_future()
        s.pending[req.request_id] = fut
        env = sign(Envelope(device_id=req.device_id, type="action.request",
                            payload={"request_id": req.request_id, "action": req.action,
                                     "params": req.params}), self.core_key)
        await s.conn.send_json(env.model_dump())
        try:
            return await asyncio.wait_for(fut, timeout=self.action_timeout_s)
        except TimeoutError:
            s.pending.pop(req.request_id, None)
            return ActionResult(request_id=req.request_id, status=ActionStatus.FAILED,
                                error=f"agent timeout after {self.action_timeout_s}s")
