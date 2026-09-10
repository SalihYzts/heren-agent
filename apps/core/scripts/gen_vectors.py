"""Generate cross-language test vectors for envelope signing (consumed by the Go agent tests)."""
import json
import sys

from heren_core.protocol import Envelope
from heren_core.security import KeyPair, sign

kp = KeyPair.from_seed_hex("00" * 31 + "01")
cases = []
for i, (type_, payload, ts) in enumerate([
    ("heartbeat", {"cpu": 21.5, "ram": 43}, 1789000000.25),
    ("action.result", {"request_id": "req_abc", "status": "completed", "output": {"uptime_s": 12, "nested": {"z": 1, "a": [1, 2, "x"]}}}, 1789000001.0),
    ("event", {"msg": "türkçe ünıcode ✓", "flag": True, "none": None}, 1789000002.125),
    ("action.result", {"request_id": "req_x", "status": "failed", "error": "boom", "output": {}}, 1789000003.0),
]):
    env = Envelope(id=f"msg_{i}", ts=ts, nonce=f"nonce{i:02d}" * 2, device_id="dev-1", type=type_, payload=payload)
    signed = sign(env, kp)
    cases.append({
        "seed_hex": kp.seed_hex,
        "public_key_hex": kp.public_key_hex,
        "envelope": json.loads(signed.model_dump_json()),
        "canonical": env.canonical_bytes().decode(),
        "sig": signed.sig,
    })
json.dump(cases, sys.stdout, indent=1, ensure_ascii=False)
