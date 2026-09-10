"""Envelope signing and replay protection (ed25519 + nonce + clock window)."""
import time

import pytest

from heren_core.protocol import Envelope
from heren_core.security import KeyPair, ReplayError, ReplayGuard, SignatureError, sign, verify


def _env(device_id="dev-1", **kw):
    return Envelope(device_id=device_id, type="action.result", payload={"ok": True}, **kw)


def test_sign_then_verify_roundtrip():
    kp = KeyPair.generate()
    env = sign(_env(), kp)
    assert env.sig is not None
    verify(env, kp.public_key_hex)  # no raise


def test_tampered_payload_fails_verification():
    kp = KeyPair.generate()
    env = sign(_env(), kp)
    tampered = env.model_copy(update={"payload": {"ok": False}})
    with pytest.raises(SignatureError):
        verify(tampered, kp.public_key_hex)


def test_wrong_key_fails_verification():
    kp1, kp2 = KeyPair.generate(), KeyPair.generate()
    env = sign(_env(), kp1)
    with pytest.raises(SignatureError):
        verify(env, kp2.public_key_hex)


def test_unsigned_envelope_fails_verification():
    kp = KeyPair.generate()
    with pytest.raises(SignatureError):
        verify(_env(), kp.public_key_hex)


def test_replay_guard_rejects_duplicate_nonce():
    guard = ReplayGuard(window_s=300, clock_skew_s=30)
    env = _env()
    guard.check(env)
    with pytest.raises(ReplayError):
        guard.check(env)


def test_replay_guard_rejects_stale_timestamp():
    guard = ReplayGuard(window_s=300, clock_skew_s=30)
    old = _env(ts=time.time() - 400)
    with pytest.raises(ReplayError):
        guard.check(old)


def test_replay_guard_rejects_future_timestamp_beyond_skew():
    guard = ReplayGuard(window_s=300, clock_skew_s=30)
    future = _env(ts=time.time() + 90)
    with pytest.raises(ReplayError):
        guard.check(future)


def test_replay_guard_forgets_nonces_after_window():
    guard = ReplayGuard(window_s=1, clock_skew_s=30, _now=lambda: 1000.0)
    env = _env(ts=1000.0)
    guard.check(env)
    guard._now = lambda: 1002.5
    # same nonce, but window elapsed — it's a *stale timestamp* now, not a duplicate
    with pytest.raises(ReplayError, match="stale"):
        guard.check(env)
    assert env.nonce not in guard._seen


def test_replay_guard_is_per_device():
    guard = ReplayGuard(window_s=300, clock_skew_s=30)
    a = _env("dev-a")
    b = a.model_copy(update={"device_id": "dev-b"})
    guard.check(a)
    guard.check(b)  # same nonce, different device — allowed
