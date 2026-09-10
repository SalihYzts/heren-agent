"""HermesBridge: talks to the Hermes API server (/v1/runs + SSE) and turns its
lifecycle into bus events. Tested against a fake Hermes (FastAPI app served in-process)."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from heren_core.bus import EventBus
from heren_core.hermes_bridge import HermesBridge, sentences


# ------------------------------------------------------------------ fake hermes


class FakeHermes:
    """Minimal /v1/runs implementation: records requests, streams scripted events."""

    def __init__(self):
        self.app = FastAPI()
        self.requests: list[dict] = []
        self.script: list[dict] = []  # events to stream, in order
        self.delay_s = 0.0
        self.approvals: list[dict] = []

        @self.app.get("/health")
        async def health():
            return {"status": "ok"}

        @self.app.post("/v1/runs")
        async def create(req: Request):
            if req.headers.get("authorization") != "Bearer hermes-key":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            body = await req.json()
            self.requests.append(body)
            return JSONResponse({"run_id": f"run_{len(self.requests)}", "status": "started"}, status_code=202)

        @self.app.get("/v1/runs/{run_id}/events")
        async def events(run_id: str):
            async def gen():
                yield b": keepalive\n\n"
                for ev in self.script:
                    if self.delay_s:
                        await asyncio.sleep(self.delay_s)
                    yield f"data: {json.dumps({'run_id': run_id, 'timestamp': 1.0, **ev})}\n\n".encode()
                yield b": stream closed\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")

        @self.app.post("/v1/runs/{run_id}/approval")
        async def approval(run_id: str, req: Request):
            self.approvals.append({"run_id": run_id, **(await req.json())})
            return {"ok": True}


@pytest.fixture
def hermes():
    return FakeHermes()


@pytest.fixture
def bridge(hermes):
    bus = EventBus()
    events: list[tuple[str, dict]] = []
    bus.subscribe("hermes.*", lambda e: events.append((e.type, e.payload)))
    transport = httpx.ASGITransport(app=hermes.app)
    b = HermesBridge(bus=bus, endpoint="http://hermes", api_key="hermes-key",
                     client_factory=lambda: httpx.AsyncClient(transport=transport, base_url="http://hermes"),
                     session_id="heren-main")
    b._events = events
    return b


# ------------------------------------------------------------------ tests


async def test_ask_streams_lifecycle_events_and_returns_final_text(bridge, hermes):
    hermes.script = [
        {"event": "tool.started", "tool": "terminal", "preview": "uptime"},
        {"event": "tool.completed", "tool": "terminal", "duration": 0.2, "error": False},
        {"event": "message.delta", "delta": "Sunucu 3 gündür açık. "},
        {"event": "message.delta", "delta": "Yük düşük."},
        {"event": "run.completed", "output": "Sunucu 3 gündür açık. Yük düşük.", "usage": {}},
    ]
    result = await bridge.ask("sunucu nasıl?")
    assert result.text == "Sunucu 3 gündür açık. Yük düşük."
    assert result.ok
    types = [t for t, _ in bridge._events]
    assert types[0] == "hermes.thinking"
    assert "hermes.tool.started" in types and "hermes.tool.completed" in types
    assert types.index("hermes.speaking") < types.index("hermes.done")
    # text is delivered sentence by sentence for TTS / character speech
    texts = [p["text"] for t, p in bridge._events if t == "hermes.text"]
    assert texts == ["Sunucu 3 gündür açık.", "Yük düşük."]


async def test_request_carries_input_session_and_character_instructions(bridge, hermes):
    hermes.script = [{"event": "run.completed", "output": "ok", "usage": {}}]
    await bridge.ask("selam", character={"activity": "speaking", "mood": "sleepy", "energy": 0.2, "time": "00:43"})
    body = hermes.requests[0]
    assert body["input"] == "selam"
    assert body["session_id"] == "heren-main"
    assert "sleepy" in body["instructions"] and "00:43" in body["instructions"]
    assert "device_action" in body["instructions"]  # tells hermes how to control devices


async def test_tool_failure_emits_tool_failed(bridge, hermes):
    hermes.script = [
        {"event": "tool.started", "tool": "terminal"},
        {"event": "tool.completed", "tool": "terminal", "duration": 0.1, "error": True},
        {"event": "run.completed", "output": "olmadı", "usage": {}},
    ]
    await bridge.ask("x")
    assert "hermes.tool.failed" in [t for t, _ in bridge._events]


async def test_run_failed_reports_error_and_still_emits_done(bridge, hermes):
    hermes.script = [{"event": "run.failed", "error": "model overloaded"}]
    result = await bridge.ask("x")
    assert not result.ok and "overloaded" in result.error
    types = [t for t, _ in bridge._events]
    assert types[-1] == "hermes.done"
    assert "hermes.error" in types


async def test_hermes_unreachable_is_reported_not_raised(bridge):
    bridge.client_factory = lambda: httpx.AsyncClient(base_url="http://127.0.0.1:9")  # nothing listens
    result = await bridge.ask("x")
    assert not result.ok and result.error
    types = [t for t, _ in bridge._events]
    assert "hermes.unavailable" in types and types[-1] == "hermes.done"


async def test_wrong_api_key_is_reported(bridge, hermes):
    bridge.api_key = "nope"
    result = await bridge.ask("x")
    assert not result.ok and "401" in result.error


async def test_approval_request_from_hermes_is_forwarded_and_can_be_answered(bridge, hermes):
    hermes.script = [
        {"event": "approval.request", "approval_id": "ap_1", "command": "rm -rf /tmp/x", "risk": "high"},
        {"event": "run.completed", "output": "done", "usage": {}},
    ]
    hermes.delay_s = 0.01
    task = asyncio.create_task(bridge.ask("temizle"))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if any(t == "hermes.approval.request" for t, _ in bridge._events):
            break
    p = next(p for t, p in bridge._events if t == "hermes.approval.request")
    assert p["approval_id"] == "ap_1" and "rm -rf" in p["command"]
    await bridge.respond_approval(p["run_id"], "ap_1", approve=False)
    await task
    assert hermes.approvals[0]["choice"] == "deny"


async def test_health_probe(bridge):
    assert await bridge.healthy() is True
    bridge.client_factory = lambda: httpx.AsyncClient(base_url="http://127.0.0.1:9")
    assert await bridge.healthy() is False


async def test_concurrent_asks_are_serialised_per_session(bridge, hermes):
    hermes.script = [{"event": "run.completed", "output": "ok", "usage": {}}]
    hermes.delay_s = 0.02
    await asyncio.gather(bridge.ask("a"), bridge.ask("b"))
    assert [r["input"] for r in hermes.requests] == ["a", "b"]
    types = [t for t, _ in bridge._events]
    # first run fully finishes before second starts
    assert types.index("hermes.done") < types.index("hermes.thinking", 1)


def test_sentence_splitter_handles_turkish_and_abbreviations():
    buf = ""
    out = []
    for chunk in ["Merhaba! Nasıl", "sın? Dr. Ali geldi. Saat 10.30'da", " bitti"]:
        buf += chunk
        done, buf = sentences(buf)
        out += done
    out += [buf] if buf.strip() else []
    assert out == ["Merhaba!", "Nasılsın?", "Dr. Ali geldi.", "Saat 10.30'da bitti"]
