"""VoiceHost: hermes.text sentences → TTS (in order, prosody from character) → voice.speech events.
Real NullTTS (silent WAV), real bus; no mocks."""
import asyncio

import pytest

from heren_core.bus import EventBus
from heren_core.voice.host import VoiceHost
from heren_core.voice.providers import NullSTT, NullTTS, Prosody


class SlowTTS(NullTTS):
    """Records what it was asked, with the prosody; optionally delays to expose ordering."""

    def __init__(self, delay_s=0.0):
        self.calls = []
        self.delay_s = delay_s

    def synthesize(self, text, prosody):
        import time
        time.sleep(self.delay_s)
        self.calls.append((text, prosody))
        return super().synthesize(text, prosody)


@pytest.fixture
def rig():
    bus = EventBus()
    tts = SlowTTS()
    character = {"mood": "neutral", "energy": 1.0}
    host = VoiceHost(bus=bus, tts=tts, stt=NullSTT(), character_state=lambda: character)
    out = []
    bus.subscribe("voice.*", lambda e: out.append(e))
    host.attach()
    return host, bus, tts, character, out


async def _settle(host):
    await host.drain()


async def test_each_sentence_becomes_a_speech_clip_in_order(rig):
    host, bus, tts, _, out = rig
    await bus.emit("hermes.text", run_id="r1", text="Birinci cümle.")
    await bus.emit("hermes.text", run_id="r1", text="İkinci cümle.")
    await _settle(host)
    speech = [e for e in out if e.type == "voice.speech"]
    assert [e.payload["text"] for e in speech] == ["Birinci cümle.", "İkinci cümle."]
    assert [e.payload["seq"] for e in speech] == [0, 1]
    assert all(e.payload["run_id"] == "r1" for e in speech)
    clip = host.clip(speech[0].payload["clip_id"])
    assert clip is not None and clip.wav.startswith(b"RIFF")
    assert speech[0].payload["duration_s"] == pytest.approx(clip.duration_s)
    assert speech[0].payload["url"].endswith(speech[0].payload["clip_id"] + ".wav")


async def test_prosody_follows_character_mood(rig):
    host, bus, tts, character, out = rig
    character.update(mood="sleepy", energy=0.2)
    await bus.emit("hermes.text", run_id="r1", text="Uykulu cümle.")
    await _settle(host)
    assert tts.calls[-1][1].length_scale > 1.2


async def test_interrupt_drops_pending_sentences_and_announces_it(rig):
    host, bus, tts, _, out = rig
    tts.delay_s = 0.05
    for i in range(5):
        await bus.emit("hermes.text", run_id="r1", text=f"Cümle {i}.")
    await asyncio.sleep(0.02)  # "Cümle 0" is mid-synthesis
    await bus.emit("voice.interrupt", run_id="r1")
    await _settle(host)
    speech = [e for e in out if e.type == "voice.speech"]
    assert speech == [], "a sentence mid-synthesis at interrupt time must not be announced"
    assert len(tts.calls) == 1, "queued sentences after the interrupt must not be synthesized"
    stopped = [e for e in out if e.type == "voice.stopped"]
    assert stopped and stopped[0].payload["run_id"] == "r1"
    # a new run afterwards speaks normally, numbering restarts
    await bus.emit("hermes.text", run_id="r2", text="Yeni tur.")
    await _settle(host)
    r2 = [e for e in out if e.type == "voice.speech" and e.payload["run_id"] == "r2"]
    assert [(e.payload["text"], e.payload["seq"]) for e in r2] == [("Yeni tur.", 0)]


async def test_clips_are_bounded_oldest_evicted(rig):
    host, bus, tts, _, out = rig
    host.max_clips = 3
    for i in range(5):
        await bus.emit("hermes.text", run_id="r1", text=f"C{i}.")
    await _settle(host)
    ids = [e.payload["clip_id"] for e in out if e.type == "voice.speech"]
    assert host.clip(ids[0]) is None and host.clip(ids[1]) is None
    assert all(host.clip(i) is not None for i in ids[2:])


async def test_tts_failure_is_reported_not_fatal(rig):
    host, bus, tts, _, out = rig

    def boom(text, prosody):
        raise RuntimeError("engine died")
    tts.synthesize = boom
    await bus.emit("hermes.text", run_id="r1", text="Patla.")
    await _settle(host)
    err = [e for e in out if e.type == "voice.error"]
    assert err and "engine died" in err[0].payload["error"]


async def test_transcribe_goes_through_stt_and_emits_transcript(rig):
    host, bus, tts, _, out = rig

    class EchoSTT(NullSTT):
        def transcribe(self, wav, language):
            from heren_core.voice.providers import Transcript
            return Transcript(text="sunucu nasıl", language=language, confidence=0.9)
    host.stt = EchoSTT()
    t = await host.transcribe(b"RIFF....", "tr")
    assert t.text == "sunucu nasıl"
    tr = [e for e in out if e.type == "voice.transcript"]
    assert tr and tr[0].payload["text"] == "sunucu nasıl"


async def test_empty_or_whitespace_sentences_are_skipped(rig):
    host, bus, tts, _, out = rig
    await bus.emit("hermes.text", run_id="r1", text="   ")
    await _settle(host)
    assert not [e for e in out if e.type == "voice.speech"]
    assert tts.calls == []


async def test_prosody_default_is_neutral(rig):
    host, bus, tts, _, out = rig
    await bus.emit("hermes.text", run_id="r1", text="Düz.")
    await _settle(host)
    assert tts.calls[-1][1] == Prosody(length_scale=1.0)
