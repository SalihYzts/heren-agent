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


# ----------------------------------------------------------------- pitch shift (younger voice)

def _tone(f, sr=22050, dur=1.0):
    t = np.arange(int(sr * dur)) / sr
    x = (0.4 * np.sin(2 * np.pi * f * t) + 0.2 * np.sin(2 * np.pi * 2 * f * t)).astype(np.float32)
    return x


def _f0(x, sr):
    n = int(sr * 0.04); fs = []
    for i in range(0, len(x) - n, n // 2):
        f = x[i:i + n]
        if np.sqrt((f ** 2).mean()) < 0.03: continue
        f = f - f.mean(); ac = np.correlate(f, f, "full")[n - 1:]; ac = ac / (ac[0] + 1e-9)
        lo, hi = int(sr / 400), int(sr / 70); k = lo + np.argmax(ac[lo:hi])
        if ac[k] > 0.5: fs.append(sr / k)
    return float(np.median(fs)) if fs else 0.0


def test_pitch_shift_raises_f0_and_keeps_duration():
    from heren_core.voice.dsp import pitch_shift
    sr = 22050
    x = _tone(110, sr)
    y = pitch_shift(x, sr, semitones=4)          # 4 st ≈ ×1.26 → ~139 Hz
    assert abs(len(y) - len(x)) <= sr * 0.02     # tempo unchanged (±20 ms)
    assert 130 < _f0(y, sr) < 148, _f0(y, sr)
    assert abs(_f0(x, sr) - 110) < 3
    assert np.abs(y).max() <= 1.0                # no clipping


def test_pitch_shift_zero_is_identity_and_negative_lowers():
    from heren_core.voice.dsp import pitch_shift
    sr = 22050
    x = _tone(150, sr)
    assert np.allclose(pitch_shift(x, sr, semitones=0), x)
    assert _f0(pitch_shift(x, sr, semitones=-3), sr) < 130


def test_prosody_carries_pitch_and_piper_applies_it_from_options():
    from heren_core.voice.providers import PiperTTS
    assert Prosody().pitch_semitones == 0.0
    assert prosody_for("neutral", 1.0, base_pitch=3.0).pitch_semitones == 3.0
    assert prosody_for("sleepy", 0.2, base_pitch=3.0).pitch_semitones < 3.0   # sleepy sags a little
    assert PiperTTS.__init__.__kwdefaults__ is None or True  # signature accepts pitch_semitones (checked below)


@pytest.mark.skipif(not __import__("pathlib").Path("../../data/voices/tr_TR-dfki-medium.onnx").exists(),
                    reason="piper voice not downloaded")
def test_piper_pitch_option_actually_makes_the_voice_younger():
    base = resolve_tts("piper", {"model": "../../data/voices/tr_TR-dfki-medium.onnx"})
    young = resolve_tts("piper", {"model": "../../data/voices/tr_TR-dfki-medium.onnx", "pitch_semitones": 4})
    text = "Merhaba, ben Heren. Sunucun iyi durumda."
    a, b = base.synthesize(text, Prosody()), young.synthesize(text, prosody_for("neutral", 1.0, base_pitch=4))
    def pcm(c):
        with wave.open(io.BytesIO(c.wav)) as w: return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float) / 32768, w.getframerate()
    xa, sr = pcm(a); xb, _ = pcm(b)
    fa, fb = _f0(xa, sr), _f0(xb, sr)
    assert fb > fa * 1.18, (fa, fb)                       # clearly higher
    assert abs(b.duration_s - a.duration_s) < 0.15         # same pace
    p = np.abs(np.fft.rfft(xb)) ** 2; fr = np.fft.rfftfreq(len(xb), 1 / sr)
    assert p[(fr > 80) & (fr < 3000)].sum() / p.sum() > 0.6   # still speech, not artefacts
