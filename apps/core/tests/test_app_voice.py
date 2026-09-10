"""Voice over HTTP: clips served by id, transcription upload → ask, stop = interrupt."""
import asyncio
import io
import wave

import pytest
from httpx import ASGITransport, AsyncClient

from heren_core.app import create_app
from heren_core.config import Settings
from heren_core.security import KeyPair
from heren_core.voice.providers import Transcript, register_stt

H = {"Authorization": "Bearer test-key"}


class FixedSTT:
    name = "fixed"

    def __init__(self, **_):
        pass

    def transcribe(self, wav, language):
        assert wav.startswith(b"RIFF")
        return Transcript(text="sunucu nasıl", language=language, confidence=0.99)


register_stt("fixed", FixedSTT)


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "heren.db", api_key="test-key", core_seed_hex=KeyPair.generate().seed_hex,
                    stt_provider="fixed", tts_provider="none", hermes_endpoint="http://127.0.0.1:1")


def _wav(seconds=0.2, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


async def test_sentence_events_become_servable_wav_clips(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        core = app.state.core
        seen = []
        core.bus.subscribe("voice.speech", lambda e: seen.append(e.payload))
        await core.bus.emit("hermes.text", run_id="r1", text="Merhaba dünya.")
        await core.voice.drain()
        assert len(seen) == 1
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(seen[0]["url"], headers=H)
            assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
            assert r.content.startswith(b"RIFF")
            assert (await c.get("/api/voice/audio/nope.wav", headers=H)).status_code == 404
            assert (await c.get(seen[0]["url"])).status_code == 401  # auth required


async def test_transcribe_upload_returns_text_and_can_ask(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        core = app.state.core
        events = []
        core.bus.subscribe("*", lambda e: events.append(e.type))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/voice/transcribe", headers=H, content=_wav(),
                             params={"ask": "false"})
            assert r.status_code == 200, r.text
            assert r.json()["text"] == "sunucu nasıl" and r.json()["asked"] is False
            assert "voice.transcript" in events
            # ask=true forwards to Hermes (unreachable here → clean unavailable, not 500)
            r = await c.post("/api/voice/transcribe", headers=H, content=_wav(), params={"ask": "true"})
            assert r.status_code == 200, r.text
            assert r.json()["asked"] is True and r.json()["ask"]["ok"] is False
            assert "hermes.unavailable" in events


async def test_transcribe_rejects_non_wav(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/voice/transcribe", headers=H, content=b"not audio at all")
            assert r.status_code == 400


async def test_stop_interrupts_speech_and_is_visible_on_the_bus(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        core = app.state.core
        events = []
        core.bus.subscribe("voice.*", lambda e: events.append(e.type))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/voice/stop", headers=H)
            assert r.status_code == 200
        assert "voice.interrupt" in events and "voice.stopped" in events


async def test_state_snapshot_reports_voice_providers(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            s = (await c.get("/api/state", headers=H)).json()
            assert s["voice"] == {"tts": "none", "stt": "fixed", "language": "tr"}


async def test_ui_playback_reports_reach_the_character(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        core = app.state.core
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await core.bus.emit("hermes.speaking", run_id="r1")
            r = await c.post("/api/voice/playback", headers=H, json={"state": "started", "clip_id": "c1"})
            assert r.status_code == 200
            await core.bus.emit("hermes.done", run_id="r1", ok=True)
            assert core.character.snapshot()["activity"] == "speaking"
            r = await c.post("/api/voice/playback", headers=H, json={"state": "finished"})
            assert r.status_code == 200
            assert core.character.snapshot()["activity"] == "idle"
            assert (await c.post("/api/voice/playback", headers=H, json={"state": "bogus"})).status_code == 422
