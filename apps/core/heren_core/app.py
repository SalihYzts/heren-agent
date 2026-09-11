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
    GET  /api/state                       devices/approvals/character/hermes/voice snapshot
    POST /api/ask                         {text} → Hermes (events stream on the bus)
    GET  /api/voice/audio/{id}.wav        synthesized sentence clip (announced by voice.speech)
    POST /api/voice/transcribe?ask=       WAV body → STT → optional ask
    POST /api/voice/stop                  barge-in: drop pending speech
    ANY  /mcp                             MCP server for Hermes (separate bearer)
    WS   /ws/agent                        device agents (hello → signed envelopes)
    WS   /ws/events?token=                UI event stream (every bus event as JSON)
"""
from __future__ import annotations

import asyncio
import io
import json
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError
from starlette.types import Receive, Scope, Send

from heren_core.actions import ActionService, ApprovalNotFound
from heren_core.bus import EventBus
from heren_core.character_host import CharacterHost
from heren_core.config import Settings
from heren_core.netaccess import access_urls
from heren_core.gateway import DeviceGateway
from heren_core.hermes_bridge import HermesBridge
from heren_core.mcp_server import BearerGate, build_mcp_server
from heren_core.protocol import ActionRequest, ActionStatus, Event
from heren_core.security import KeyPair
from heren_core.storage import Storage
from heren_core.voice.host import VoiceHost
from heren_core.voice.providers import resolve_stt, resolve_tts

log = logging.getLogger("heren.app")


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
        self.hermes: HermesBridge | None = None
        self.voice: VoiceHost | None = None
        self.mcp_app: Any = None
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
        async def _save_character(d: dict[str, Any]) -> None:
            await self.store.set_setting("character_state", json.dumps(d))

        async def _load_character() -> dict[str, Any] | None:
            raw = await self.store.get_setting("character_state")
            return json.loads(raw) if raw else None

        self.character = CharacterHost(bus=self.bus, cfg=s.character_config(),
                                       tick_interval_s=s.character_tick_s,
                                       save_state=_save_character, load_state=_load_character)
        self.character.attach()
        await self.character.restore()   # energy / sleep debt / asleep? from the last run
        self.character.start()
        self.hermes = HermesBridge(bus=self.bus, endpoint=s.hermes_endpoint, api_key=s.hermes_api_key,
                                   session_id=s.hermes_session_id, language=s.hermes_language,
                                   request_timeout_s=s.hermes_request_timeout_s)
        tts = await asyncio.to_thread(resolve_tts, s.tts_provider, s.tts_options)
        stt = await asyncio.to_thread(resolve_stt, s.stt_provider, s.stt_options)
        log.info("voice: tts=%s stt=%s", tts.name, stt.name)
        self.voice = VoiceHost(bus=self.bus, tts=tts, stt=stt, character_state=self.character.snapshot,
                               language=s.language, max_clips=s.voice_max_clips)
        self.voice.attach()
        self._tasks.append(asyncio.create_task(self._housekeeping()))

    async def stop(self) -> None:
        if self.voice:
            await self.voice.stop()
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


class PlaybackIn(BaseModel):
    state: Literal["started", "finished"]
    clip_id: str | None = None


class AskIn(BaseModel):
    text: str
    model: str | None = None      # per-request Hermes model override (None = gateway default)
    provider: str | None = None


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

    # MCP server is built once; its tool handlers reach core.store/core.actions lazily
    # through the proxies below, because Core starts inside the lifespan.
    class _StoreProxy:
        def __getattr__(self, n: str) -> Any: return getattr(core.store, n)

    class _ActionsProxy:
        def __getattr__(self, n: str) -> Any:
            assert core.actions, "core not started"
            return getattr(core.actions, n)

    mcp = build_mcp_server(store=_StoreProxy(), actions=_ActionsProxy())  # type: ignore[arg-type]
    from mcp.server.transport_security import TransportSecuritySettings

    # Auth is our Bearer gate; DNS-rebinding host pinning is optional (mcp_allowed_hosts).
    sec = (TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=settings.mcp_allowed_hosts)
           if settings.mcp_allowed_hosts else
           TransportSecuritySettings(enable_dns_rebinding_protection=False))
    mcp_asgi = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                       transport_security=sec)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await core.start()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            await core.stop()

    app = FastAPI(title="heren-core", lifespan=lifespan)
    app.state.core = core

    # /mcp is served by a path-scoped ASGI shim rather than app.mount(): Starlette's
    # Mount only matches "/mcp/…", while MCP clients POST to exactly "/mcp", which
    # would otherwise fall into the SPA catch-all route.
    mcp_gate = BearerGate(mcp_asgi, settings.mcp_key)

    class _McpShim:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http" and scope["path"].rstrip("/") == "/mcp":
                scope = dict(scope, path="/", root_path=scope.get("root_path", "") + "/mcp")
                await mcp_gate(scope, receive, send)
                return
            await self.inner(scope, receive, send)

    app.add_middleware(_McpShim)
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
        assert core.character and core.hermes
        return {
            "devices": [d.model_dump() for d in await core.store.list_devices()],
            "approvals": [r.model_dump() | {"risk": r.risk} for r in await svc().list_pending_approvals()],
            "character": core.character.snapshot(),
            "hermes": {"endpoint": settings.hermes_endpoint, "reachable": await core.hermes.healthy()},
            "voice": {"tts": core.voice.tts.name if core.voice else "none",
                      "stt": core.voice.stt.name if core.voice else "none", "language": settings.language},
            "access": {"urls": access_urls(settings), "tls": settings.tls},
        }

    @app.get("/api/state", dependencies=[Depends(auth)])
    async def state() -> dict[str, Any]:
        return await _snapshot()

    @app.get("/api/access/qr.svg", dependencies=[Depends(auth)])
    async def access_qr(url: str | None = None) -> Response:
        """QR for the phone: encodes the first LAN url (or ?url=…, restricted to our own urls)."""
        urls = access_urls(settings)
        if not urls:
            raise HTTPException(404, "not reachable from the LAN (bound to loopback)")
        target = url if url in urls else urls[0]
        import segno
        buf = io.BytesIO()
        # full document (xmlns + xml decl): it is served as an image, not pasted inline
        segno.make(target, error="m").save(buf, kind="svg", scale=6, dark="#000", light=None, border=2)
        svg = buf.getvalue()
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=60"})

    from heren_core.models_catalog import ModelCatalog
    catalog = ModelCatalog(settings.hermes_home, settings.hermes_root, ttl_s=settings.models_cache_s)

    @app.get("/api/models", dependencies=[Depends(auth)])
    async def models(refresh: bool = False) -> dict[str, Any]:
        """Providers with credentials in the Hermes install + the models each can run (cached)."""
        return await asyncio.to_thread(catalog.get, refresh)

    async def _ask(text: str, model: str | None = None, provider: str | None = None) -> dict[str, Any]:
        assert core.hermes and core.character
        char = core.character.snapshot() | {"time": time.strftime("%H:%M")}
        # Dashboard context: what Hermes needs to understand "that button", "this app".
        devices = [{"device_id": d.device_id, "name": d.name, "status": d.status}
                   for d in await core.store.list_devices()]
        recent = [{"action": a["action"], "device_id": a["device_id"], "result": a["result"], "error": a["error"]}
                  for a in await core.store.list_audit(limit=5)]
        context = {"app": {"name": "Heren", "role": "control panel"}, "devices": devices, "recent_actions": recent}
        res = await core.hermes.ask(text, character=char, context=context, model=model, provider=provider)
        return {"ok": res.ok, "text": res.text, "error": res.error, "run_id": res.run_id}

    @app.post("/api/ask", dependencies=[Depends(auth)])
    async def ask(body: AskIn) -> dict[str, Any]:
        return await _ask(body.text, body.model, body.provider)

    # ---- voice -------------------------------------------------------------

    @app.get("/api/voice/audio/{clip_id}.wav", dependencies=[Depends(auth)])
    async def voice_audio(clip_id: str) -> Response:
        clip = core.voice.clip(clip_id) if core.voice else None
        if clip is None:
            raise HTTPException(404, "no such clip")
        return Response(clip.wav, media_type="audio/wav", headers={"Cache-Control": "private, max-age=600"})

    @app.post("/api/voice/transcribe", dependencies=[Depends(auth)])
    async def voice_transcribe(request: Request, ask: bool = False,
                               model: str | None = None, provider: str | None = None) -> dict[str, Any]:
        assert core.voice
        wav = await request.body()
        if not wav.startswith(b"RIFF"):
            raise HTTPException(400, "expected a WAV body (RIFF)")
        t = await core.voice.transcribe(wav)
        out: dict[str, Any] = {"text": t.text, "language": t.language, "confidence": t.confidence, "asked": False}
        if ask and t.text.strip():
            out["asked"] = True
            out["ask"] = await _ask(t.text, model, provider)
        return out

    @app.post("/api/voice/stop", dependencies=[Depends(auth)])
    async def voice_stop() -> dict[str, Any]:
        await core.bus.emit("voice.interrupt", source="ui")
        return {"ok": True}

    @app.post("/api/voice/playback", dependencies=[Depends(auth)])
    async def voice_playback(body: PlaybackIn) -> dict[str, Any]:
        # the browser is the only one who knows when audio actually plays; the character follows it
        await core.bus.emit(f"voice.playback.{body.state}", clip_id=body.clip_id, source="ui")
        return {"ok": True}

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
            if path.startswith(("api/", "ws/", "mcp")):
                raise HTTPException(404)
            candidate = (ui_dir / path).resolve()
            if path and candidate.is_file() and ui_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(ui_dir / "index.html")

    return app
