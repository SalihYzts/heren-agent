"""FastAPI application factory.

Routes:
    GET  /health                          public liveness
    GET  /api/devices                     list devices
    POST /api/devices/pairing-code        mint a one-time 6-digit pairing code
    POST /api/actions                     submit an action (200 done, 202 awaiting approval)
    GET  /api/actions/{id}                action status
    GET  /api/approvals                   pending approvals
    POST /api/approvals/{id}/approve      {approved_by}
    POST /api/approvals/{id}/deny         {denied_by}
    GET  /api/audit                       newest first
    GET  /api/state                       character + counts snapshot (phase 4 fills this)
    WS   /ws/agent                        device agents (hello → signed envelopes)
    WS   /ws/events?token=                UI event stream (every bus event as JSON)
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from nero_core.actions import ActionService, ApprovalNotFound
from nero_core.bus import EventBus
from nero_core.character_host import CharacterHost
from nero_core.config import Settings
from nero_core.gateway import DeviceGateway
from nero_core.protocol import ActionRequest, ActionStatus, Event
from nero_core.security import KeyPair
from nero_core.storage import Storage

log = logging.getLogger("nero.app")


class Core:
    """Everything the routes need, built once per app."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bus = EventBus()
        self.store = Storage(settings.db_path)
        self.core_key: KeyPair | None = None
        self.gateway: DeviceGateway | None = None
        self.actions: ActionService | None = None
        self.character: CharacterHost | None = None
        self._tasks: list[asyncio.Task[Any]] = []

    async def start(self) -> None:
        await self.store.open()
        seed = self.settings.core_seed_hex or await self.store.get_setting("core_seed_hex")
        if seed is None:
            seed = KeyPair.generate().seed_hex
            await self.store.set_setting("core_seed_hex", seed)
        self.core_key = KeyPair.from_seed_hex(seed)
        s = self.settings
        self.gateway = DeviceGateway(store=self.store, bus=self.bus, core_key=self.core_key,
                                     heartbeat_timeout_s=s.heartbeat_timeout_s,
                                     action_timeout_s=s.action_timeout_s,
                                     pairing_code_ttl_s=s.pairing_code_ttl_s)
        self.actions = ActionService(store=self.store, bus=self.bus, dispatcher=self.gateway,
                                     approval_ttl_s=s.approval_ttl_s, critical_enabled=s.critical_enabled)
        self.character = CharacterHost(bus=self.bus, cfg=s.character_config(),
                                       tick_interval_s=s.character_tick_s)
        self.character.attach()
        self.character.start()
        self._tasks.append(asyncio.create_task(self._housekeeping()))

    async def stop(self) -> None:
        if self.character:
            await self.character.stop()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await self.store.close()

    async def _housekeeping(self) -> None:
        assert self.gateway and self.actions
        interval = max(1.0, min(self.settings.heartbeat_timeout_s / 3, self.settings.approval_ttl_s / 3))
        while True:
            await asyncio.sleep(interval)
            try:
                await self.gateway.reap_dead_sessions()
                await self.actions.expire_stale()
            except Exception:
                log.exception("housekeeping failed")


# ------------------------------------------------------------------ request models


class ActionIn(BaseModel):
    device_id: str
    action: str
    params: dict[str, Any] = {}
    requested_by: str = "ui"


class ApproveIn(BaseModel):
    approved_by: str


class DenyIn(BaseModel):
    denied_by: str


# ------------------------------------------------------------------ WS conn adapter


class _WsConn:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def send_json(self, data: dict) -> None:
        await self.ws.send_json(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        with contextlib.suppress(Exception):
            await self.ws.close(code=code, reason=reason)


# ------------------------------------------------------------------ factory


def create_app(settings: Settings) -> FastAPI:
    core = Core(settings)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await core.start()
        try:
            yield
        finally:
            await core.stop()

    app = FastAPI(title="nero-core", lifespan=lifespan)
    app.state.core = core
    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_methods=["*"], allow_headers=["*"])

    def auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        if header != f"Bearer {settings.api_key}":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")

    def svc() -> ActionService:
        assert core.actions
        return core.actions

    def gw() -> DeviceGateway:
        assert core.gateway
        return core.gateway

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/devices", dependencies=[Depends(auth)])
    async def list_devices() -> list[dict[str, Any]]:
        return [d.model_dump() for d in await core.store.list_devices()]

    @app.post("/api/devices/pairing-code", dependencies=[Depends(auth)])
    async def pairing_code() -> dict[str, Any]:
        return {"code": gw().new_pairing_code(), "ttl_s": settings.pairing_code_ttl_s}

    @app.post("/api/actions", dependencies=[Depends(auth)])
    async def submit_action(body: ActionIn) -> JSONResponse:
        if await core.store.get_device(body.device_id) is None:
            raise HTTPException(404, "unknown device")
        try:
            req = ActionRequest(**body.model_dump())
        except ValidationError as e:
            raise HTTPException(422, str(e)) from e
        res = await svc().submit(req)
        code = 202 if res.status == ActionStatus.AWAITING_APPROVAL else 200
        return JSONResponse(res.model_dump(), status_code=code)

    @app.get("/api/actions", dependencies=[Depends(auth)])
    async def list_actions(limit: int = 50) -> list[dict[str, Any]]:
        return [r.model_dump() | {"risk": r.risk} for r in await core.store.list_actions(limit=limit)]

    @app.get("/api/actions/{request_id}", dependencies=[Depends(auth)])
    async def get_action(request_id: str) -> dict[str, Any]:
        req = await core.store.get_action(request_id)
        if req is None:
            raise HTTPException(404, "unknown request")
        return req.model_dump() | {"risk": req.risk}

    @app.get("/api/approvals", dependencies=[Depends(auth)])
    async def list_approvals() -> list[dict[str, Any]]:
        return [r.model_dump() | {"risk": r.risk} for r in await svc().list_pending_approvals()]

    @app.post("/api/approvals/{request_id}/approve", dependencies=[Depends(auth)])
    async def approve(request_id: str, body: ApproveIn) -> dict[str, Any]:
        try:
            return (await svc().approve(request_id, approved_by=body.approved_by)).model_dump()
        except ApprovalNotFound as e:
            raise HTTPException(404, "no pending approval") from e
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e

    @app.post("/api/approvals/{request_id}/deny", dependencies=[Depends(auth)])
    async def deny(request_id: str, body: DenyIn) -> dict[str, Any]:
        try:
            return (await svc().deny(request_id, denied_by=body.denied_by)).model_dump()
        except ApprovalNotFound as e:
            raise HTTPException(404, "no pending approval") from e

    @app.get("/api/audit", dependencies=[Depends(auth)])
    async def audit(limit: int = 100) -> list[dict[str, Any]]:
        return await core.store.list_audit(limit=limit)

    async def _snapshot() -> dict[str, Any]:
        assert core.character
        return {
            "devices": [d.model_dump() for d in await core.store.list_devices()],
            "approvals": [r.model_dump() | {"risk": r.risk} for r in await svc().list_pending_approvals()],
            "character": core.character.snapshot(),
        }

    @app.get("/api/state", dependencies=[Depends(auth)])
    async def state() -> dict[str, Any]:
        return await _snapshot()

    @app.post("/api/character/touch", dependencies=[Depends(auth)])
    async def character_touch() -> dict[str, Any]:
        await core.bus.emit("character.touch", source="ui")
        assert core.character
        return core.character.snapshot()

    @app.websocket("/ws/agent")
    async def agent_ws(ws: WebSocket) -> None:
        await ws.accept()
        g = gw()
        sid = await g.connect(_WsConn(ws))
        try:
            while True:
                data = await ws.receive_json()
                await g.handle_message(sid, data)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("agent ws error")
        finally:
            await g.disconnect(sid)

    @app.websocket("/ws/events")
    async def events_ws(ws: WebSocket, token: str = "") -> None:
        if token != settings.api_key:
            await ws.close(code=4401, reason="invalid token")
            return
        await ws.accept()
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)

        def on_event(e: Event) -> None:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(e)

        unsub = core.bus.subscribe("*", on_event)
        # initial snapshot so a (re)connecting UI never starts from a blank state
        snapshot = Event(type="ui.snapshot", payload=await _snapshot())
        await ws.send_json(snapshot.model_dump())

        async def pump() -> None:
            while True:
                e = await queue.get()
                await ws.send_json(e.model_dump())

        async def watch_close() -> None:
            # the only way to notice a client going away is to keep receiving
            while True:
                await ws.receive_text()

        pump_task = asyncio.create_task(pump())
        watch_task = asyncio.create_task(watch_close())
        try:
            await asyncio.wait({pump_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            unsub()
            for t in (pump_task, watch_task):
                t.cancel()
            for t in (pump_task, watch_task):
                with contextlib.suppress(BaseException):
                    await t

    if settings.ui_dir and settings.ui_dir.is_dir():
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        ui_dir = settings.ui_dir
        assets = ui_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path.startswith(("api/", "ws/")):
                raise HTTPException(404)
            candidate = (ui_dir / path).resolve()
            if path and candidate.is_file() and ui_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(ui_dir / "index.html")

    return app
