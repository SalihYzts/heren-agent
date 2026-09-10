"""Voice providers — STT and TTS behind minimal interfaces.

    TTSProvider.synthesize(text, prosody) -> AudioClip (mono 16-bit WAV bytes)
    STTProvider.transcribe(wav_bytes, language) -> Transcript

Built-ins: none (silent/empty, always available), piper (local TTS), faster_whisper
(local STT). Cloud providers plug in the same way. Selection by name via
resolve_tts / resolve_stt; unknown names fall back to the null provider (logged).
"""
from __future__ import annotations

import io
import logging
import wave
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger("heren.voice")


@dataclass(frozen=True)
class Prosody:
    length_scale: float = 1.0  # >1 slower, <1 faster
    noise_scale: float | None = None


@dataclass(frozen=True)
class AudioClip:
    wav: bytes
    sample_rate: int
    duration_s: float


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None
    confidence: float | None = None


class TTSProvider(Protocol):
    name: str
    def synthesize(self, text: str, prosody: Prosody) -> AudioClip: ...


class STTProvider(Protocol):
    name: str
    def transcribe(self, wav: bytes, language: str) -> Transcript: ...


def prosody_for(mood: str, energy: float) -> Prosody:
    """Mood/energy → speech rate. Deterministic; facts are untouched (only pace changes)."""
    scale = 1.0
    if mood == "sleepy":
        scale = 1.25 + (1.0 - max(0.0, min(1.0, energy))) * 0.2
    elif mood == "happy":
        scale = 0.95
    elif mood == "annoyed":
        scale = 0.98
    elif energy < 0.35:
        scale = 1.15
    return Prosody(length_scale=round(scale, 3))


# ----------------------------------------------------------------- null


def _wav_bytes(samples: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples)
    return buf.getvalue()


class NullTTS:
    """Silent clip whose length approximates speaking time — keeps the pipeline testable."""

    name = "none"
    rate = 16000

    def synthesize(self, text: str, prosody: Prosody) -> AudioClip:
        words = max(1, len(text.split()))
        dur = max(0.3, words * 0.35 * prosody.length_scale)
        n = int(dur * self.rate)
        return AudioClip(_wav_bytes(b"\x00\x00" * n, self.rate), self.rate, dur)


class NullSTT:
    name = "none"

    def transcribe(self, wav: bytes, language: str) -> Transcript:
        return Transcript(text="", language=language)


# ----------------------------------------------------------------- piper


class PiperTTS:
    name = "piper"

    def __init__(self, model: str, **_: Any) -> None:
        from piper import PiperVoice  # local import: optional dependency

        self._voice = PiperVoice.load(model)
        self.rate = self._voice.config.sample_rate

    def synthesize(self, text: str, prosody: Prosody) -> AudioClip:
        from piper import SynthesisConfig

        cfg = SynthesisConfig(length_scale=prosody.length_scale,
                              **({"noise_scale": prosody.noise_scale} if prosody.noise_scale is not None else {}))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self._voice.synthesize_wav(text, w, syn_config=cfg)
        data = buf.getvalue()
        with wave.open(io.BytesIO(data)) as w:
            dur = w.getnframes() / w.getframerate()
        return AudioClip(data, self.rate, dur)


# ----------------------------------------------------------------- faster-whisper


class FasterWhisperSTT:
    name = "faster_whisper"

    def __init__(self, model: str = "small", device: str = "cpu", compute_type: str = "int8", **_: Any) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model, device=device, compute_type=compute_type)

    def transcribe(self, wav: bytes, language: str) -> Transcript:
        segs, info = self._model.transcribe(io.BytesIO(wav), language=language or None, beam_size=1,
                                            vad_filter=True)
        text = " ".join(s.text.strip() for s in segs).strip()
        return Transcript(text=text, language=info.language, confidence=float(info.language_probability))


# ----------------------------------------------------------------- registry

_TTS: dict[str, type] = {"none": NullTTS, "piper": PiperTTS}
_STT: dict[str, type] = {"none": NullSTT, "faster_whisper": FasterWhisperSTT}


def register_tts(name: str, cls: type) -> None:
    _TTS[name] = cls


def register_stt(name: str, cls: type) -> None:
    _STT[name] = cls


def resolve_tts(name: str, options: dict[str, Any]) -> TTSProvider:
    cls = _TTS.get(name)
    if cls is None:
        log.warning("unknown tts provider %r — using none", name)
        return NullTTS()
    try:
        return cls(**options) if cls is not NullTTS else NullTTS()
    except Exception as e:
        log.error("tts provider %r failed to start (%s) — using none", name, e)
        return NullTTS()


def resolve_stt(name: str, options: dict[str, Any]) -> STTProvider:
    cls = _STT.get(name)
    if cls is None:
        log.warning("unknown stt provider %r — using none", name)
        return NullSTT()
    try:
        return cls(**options) if cls is not NullSTT else NullSTT()
    except Exception as e:
        log.error("stt provider %r failed to start (%s) — using none", name, e)
        return NullSTT()

