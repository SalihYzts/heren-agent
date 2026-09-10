"""Tiny DSP for the voice pipeline — pitch shift with tempo preserved.

WSOLA time-stretch (overlap-add with waveform-similarity alignment) followed by
linear resampling: stretch by `r`, then resample by `1/r` → same length, pitch × r.
numpy only. Good enough for ±6 semitones on speech; not a studio vocoder.
"""
from __future__ import annotations

import numpy as np


def _resample(x: np.ndarray, factor: float) -> np.ndarray:
    """Resample by `factor` (>1 = more samples). Linear interpolation."""
    n_out = max(1, int(round(len(x) * factor)))
    src = np.linspace(0, len(x) - 1, n_out)
    return np.interp(src, np.arange(len(x)), x).astype(np.float32)


def time_stretch(x: np.ndarray, sr: int, rate: float, frame_ms: float = 40.0, seek_ms: float = 8.0) -> np.ndarray:
    """WSOLA: output length ≈ len(x) * rate, pitch unchanged."""
    if abs(rate - 1.0) < 1e-6 or len(x) < sr // 20:
        return x.astype(np.float32, copy=True)
    n = int(sr * frame_ms / 1000)          # frame
    hop_out = n // 2                       # synthesis hop
    hop_in = hop_out / rate                # analysis hop
    seek = int(sr * seek_ms / 1000)
    win = np.hanning(n).astype(np.float32)
    out_len = int(len(x) * rate) + n
    out = np.zeros(out_len, dtype=np.float32)
    norm = np.zeros(out_len, dtype=np.float32)

    pos_out = 0
    pos_in = 0.0
    prev_tail: np.ndarray | None = None    # the part of the last frame that overlaps the next
    while pos_out + n <= out_len and int(pos_in) + n <= len(x):
        center = int(pos_in)
        if prev_tail is None:
            best = center
        else:
            lo, hi = max(0, center - seek), min(len(x) - n, center + seek)
            best, best_score = center, -np.inf
            cand = x[lo:hi + n]
            for k in range(lo, hi + 1):
                seg = cand[k - lo:k - lo + hop_out]
                score = float(np.dot(seg, prev_tail))
                if score > best_score:
                    best_score, best = score, k
        frame = x[best:best + n] * win
        out[pos_out:pos_out + n] += frame
        norm[pos_out:pos_out + n] += win
        prev_tail = x[best + hop_out:best + n]      # what should follow, un-windowed
        pos_out += hop_out
        pos_in += hop_in
    norm[norm < 1e-3] = 1.0
    y = out / norm
    return y[:int(len(x) * rate)]


def pitch_shift(x: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """Shift pitch by `semitones`, keep duration (±one frame). Input float32 in [-1, 1]."""
    if abs(semitones) < 1e-6:
        return x.astype(np.float32, copy=True)
    r = 2.0 ** (semitones / 12.0)
    stretched = time_stretch(x.astype(np.float32), sr, r)       # longer (r>1) at same pitch
    y = _resample(stretched, 1.0 / r)                           # back to original length → pitch × r
    # keep exact length and headroom
    if len(y) < len(x):
        y = np.pad(y, (0, len(x) - len(y)))
    y = y[:len(x)]
    peak = float(np.abs(y).max()) if len(y) else 0.0
    if peak > 0.99:
        y = y * (0.99 / peak)
    return y.astype(np.float32)
