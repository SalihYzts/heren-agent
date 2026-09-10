"""Envelope signing (ed25519) and replay protection.

Agents sign every envelope with their device key; core verifies against the
public key registered at pairing time. Core signs its own outbound envelopes with
the core key so agents can pin it.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from heren_core.protocol import Envelope


class SignatureError(Exception):
    pass


class ReplayError(Exception):
    pass


@dataclass(frozen=True)
class KeyPair:
    signing_key: SigningKey

    @classmethod
    def generate(cls) -> KeyPair:
        return cls(SigningKey.generate())

    @classmethod
    def from_seed_hex(cls, seed_hex: str) -> KeyPair:
        return cls(SigningKey(bytes.fromhex(seed_hex)))

    @property
    def seed_hex(self) -> str:
        return bytes(self.signing_key).hex()

    @property
    def public_key_hex(self) -> str:
        return bytes(self.signing_key.verify_key).hex()


def sign(env: Envelope, kp: KeyPair) -> Envelope:
    sig = kp.signing_key.sign(env.canonical_bytes()).signature
    return env.model_copy(update={"sig": sig.hex()})


def verify(env: Envelope, public_key_hex: str) -> None:
    if not env.sig:
        raise SignatureError("envelope is unsigned")
    try:
        VerifyKey(bytes.fromhex(public_key_hex)).verify(env.canonical_bytes(), bytes.fromhex(env.sig))
    except (BadSignatureError, ValueError) as e:
        raise SignatureError("bad signature") from e


@dataclass
class ReplayGuard:
    """Reject envelopes whose (device_id, nonce) was seen inside the window, or whose
    timestamp is outside [now - window_s, now + clock_skew_s]."""

    window_s: float = 300.0
    clock_skew_s: float = 30.0
    _now: Callable[[], float] = time.time
    _seen: dict[tuple[str, str], float] = field(default_factory=dict)

    def check(self, env: Envelope) -> None:
        now = self._now()
        self._evict(now)
        if env.ts < now - self.window_s:
            raise ReplayError("stale timestamp")
        if env.ts > now + self.clock_skew_s:
            raise ReplayError("timestamp in the future")
        key = (env.device_id, env.nonce)
        if key in self._seen:
            raise ReplayError("duplicate nonce")
        self._seen[key] = env.ts

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_s
        for k in [k for k, ts in self._seen.items() if ts < cutoff]:
            del self._seen[k]
