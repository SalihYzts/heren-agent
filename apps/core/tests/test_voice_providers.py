"""Voice providers: swappable TTS/STT behind small interfaces. No vendor lock-in."""
import io
import wave

import numpy as np
import pytest

from heren_core.voice.providers import (
    NullSTT,
    NullTTS,
    Prosody,
    prosody_for,
    resolve_stt,
    resolve_tts,
)


def test_prosody_derives_from_mood_and_energy():
    assert prosody_for("neutral", 1.0) == Prosody(length_scale=1.0)
    assert prosody_for("sleepy", 0.2).length_scale > 1.2       # slower when sleepy
    assert prosody_for("happy", 1.0).length_scale < 1.0        # a bit quicker when happy
    assert prosody_for("sleepy", 0.9).length_scale > prosody_for("neutral", 0.9).length_scale
    assert prosody_for("annoyed", 1.0).length_scale <= 1.0


def test_null_tts_produces_valid_silent_wav_with_duration_proportional_to_text():
    tts = NullTTS()
    short = tts.synthesize("Merhaba.", Prosody())
    long = tts.synthesize("Merhaba, bu çok daha uzun bir cümle ve süresi daha fazla olmalı.", Prosody())
    for clip in (short, long):
        with wave.open(io.BytesIO(clip.wav), "rb") as w:
            assert w.getnchannels() == 1 and w.getsampwidth() == 2
            assert w.getframerate() == clip.sample_rate
    assert long.duration_s > short.duration_s
    assert short.duration_s > 0


def test_null_stt_returns_empty_transcript():
    assert NullSTT().transcribe(b"", "tr").text == ""


def test_resolve_by_name_and_unknown_falls_back_to_null(caplog):
    assert isinstance(resolve_tts("none", {}), NullTTS)
    assert isinstance(resolve_stt("none", {}), NullSTT)
    assert isinstance(resolve_tts("does-not-exist", {}), NullTTS)
    assert "unknown tts provider" in caplog.text


@pytest.mark.skipif(not __import__("pathlib").Path("../../data/voices/tr_TR-dfki-medium.onnx").exists(),
                    reason="piper voice not downloaded")
def test_piper_tts_real_voice_speech_band_and_prosody():
    tts = resolve_tts("piper", {"model": "../../data/voices/tr_TR-dfki-medium.onnx"})
    a = tts.synthesize("Merhaba, ben Heren.", Prosody(length_scale=1.0))
    b = tts.synthesize("Merhaba, ben Heren.", Prosody(length_scale=1.4))
    assert b.duration_s > a.duration_s * 1.2  # prosody actually applied
    with wave.open(io.BytesIO(a.wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
        fr = np.fft.rfftfreq(len(x), 1 / w.getframerate())
    p = np.abs(np.fft.rfft(x)) ** 2
    assert p[(fr > 80) & (fr < 3000)].sum() / p.sum() > 0.6  # speech band, not noise
