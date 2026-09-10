"""Device gateway: agent sessions, pairing, signed envelopes, heartbeat, dispatch.

Transport-agnostic — tests use an in-memory connection; the WebSocket route is a thin wrapper.
"""
import asyncio

import pytest

from nero_core.bus import EventBus
from nero_core.gateway import DeviceGateway, PairingError
from nero_core.protocol import ActionRequest, ActionStatus, DeviceStatus, Envelope
from nero_core.security import KeyPair, sign, verify
from nero_core.storage import Storage


class FakeConn:
    def __init__(self):
        self.sent: asyncio.Queue[dict] = asyncio.Queue()
        self.closed: tuple[int, str] | None = None

    async def send_json(self, data: dict) -> None:
        await self.sent.put(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


class FakeAgent:
    """Minimal agent behaviour: signs envelopes, answers action.request."""

    def __init__(self, device_id="dev-1", name="PC", platform="linux"):
        self.kp = KeyPair.generate()
        self.device_id = device_id
        self.name = name
        self.platform = platform
        self.conn = FakeConn()

    def hello(self, pairing_code: str | None = None) -> dict:
        h = {"type": "hello", "device_id": self.device_id, "name": self.name,
             "platform": self.platform, "public_key": self.kp.public_key_hex,
             "capabilities": ["get_status", "shutdown"]}
        if pairing_code:
            h["pairing_code"] = pairing_code
        return h

    def envelope(self, type_: str, **payload) -> dict:
        return sign(Envelope(device_id=self.device_id, type=type_, payload=payload), self.kp).model_dump()


@pytest.fixture
async def gw(tmp_path):
    store = Storage(tmp_path / "t.db")
    await store.open()
    bus = EventBus()
    g = DeviceGateway(store=store, bus=bus, core_key=KeyPair.generate(),
                      heartbeat_timeout_s=5, action_timeout_s=2)
    g._events = []
    bus.subscribe("*", lambda e: g._events.append((e.type, e.payload)))
    yield g
    await store.close()


async def _connect(gw, agent, code=None):
    sid = await gw.connect(agent.conn)
    await gw.handle_message(sid, agent.hello(code))
    return sid


# ------------------------------------------------------------------ pairing


async def test_unknown_device_without_pairing_code_is_rejected(gw):
    a = FakeAgent()
    sid = await gw.connect(a.conn)
    await gw.handle_message(sid, a.hello())
    assert a.conn.closed is not None and "pairing" in a.conn.closed[1]
    assert await gw.store.get_device("dev-1") is None


async def test_pairing_code_registers_device_and_marks_online(gw):
    code = gw.new_pairing_code()
    a = FakeAgent()
    await _connect(gw, a, code)
    d = await gw.store.get_device("dev-1")
    assert d is not None and d.public_key == a.kp.public_key_hex
    assert d.status == DeviceStatus.ONLINE
    assert gw.is_online("dev-1")
    assert ("device.online", {"device_id": "dev-1"}) in [(t, {"device_id": p.get("device_id")}) for t, p in gw._events]
    welcome = await a.conn.sent.get()
    assert welcome["type"] == "welcome" and welcome["core_public_key"] == gw.core_key.public_key_hex


async def test_pairing_code_is_single_use(gw):
    code = gw.new_pairing_code()
    await _connect(gw, FakeAgent("dev-1"), code)
    b = FakeAgent("dev-2")
    await _connect(gw, b, code)
    assert b.conn.closed is not None


async def test_known_device_reconnects_without_code_if_key_matches(gw):
    code = gw.new_pairing_code()
    a = FakeAgent()
    sid = await _connect(gw, a, code)
    await gw.disconnect(sid)
    assert not gw.is_online("dev-1")
    a.conn = FakeConn()
    await _connect(gw, a)
    assert gw.is_online("dev-1")


async def test_known_device_with_different_key_is_rejected(gw):
    code = gw.new_pairing_code()
    await _connect(gw, FakeAgent("dev-1"), code)
    impostor = FakeAgent("dev-1")  # fresh key pair, same id
    await _connect(gw, impostor)
    assert impostor.conn.closed is not None and "key" in impostor.conn.closed[1]
    assert not gw.is_online("dev-1") or gw.session_count("dev-1") == 1


# ------------------------------------------------------------------ envelopes


async def test_unsigned_or_badly_signed_envelope_is_dropped(gw):
    a = FakeAgent()
    sid = await _connect(gw, a, gw.new_pairing_code())
    await a.conn.sent.get()  # welcome
    bad = Envelope(device_id="dev-1", type="heartbeat", payload={}).model_dump()
    await gw.handle_message(sid, bad)
    err = await a.conn.sent.get()
    assert err["type"] == "error" and "signature" in err["reason"]


async def test_replayed_envelope_is_dropped(gw):
    a = FakeAgent()
    sid = await _connect(gw, a, gw.new_pairing_code())
    await a.conn.sent.get()
    hb = a.envelope("heartbeat", cpu=1)
    await gw.handle_message(sid, hb)
    await gw.handle_message(sid, hb)
    err = await a.conn.sent.get()
    assert err["type"] == "error" and "replay" in err["reason"]


async def test_heartbeat_updates_last_seen_and_publishes_metrics(gw):
    a = FakeAgent()
    sid = await _connect(gw, a, gw.new_pairing_code())
    await gw.handle_message(sid, a.envelope("heartbeat", cpu=21, ram=43))
    d = await gw.store.get_device("dev-1")
    assert d.last_seen is not None
    assert any(t == "device.metrics" and p["cpu"] == 21 for t, p in gw._events)


async def test_missed_heartbeats_mark_device_offline(tmp_path):
    store = Storage(tmp_path / "t.db")
    await store.open()
    bus = EventBus()
    clock = [1000.0]
    gw = DeviceGateway(store=store, bus=bus, core_key=KeyPair.generate(),
                       heartbeat_timeout_s=5, action_timeout_s=2, _now=lambda: clock[0])
    a = FakeAgent()
    await _connect(gw, a, gw.new_pairing_code())
    clock[0] += 6
    await gw.reap_dead_sessions()
    assert not gw.is_online("dev-1")
    assert (await store.get_device("dev-1")).status == DeviceStatus.OFFLINE
    assert a.conn.closed is not None
    await store.close()


# ------------------------------------------------------------------ dispatch


async def test_dispatch_sends_signed_request_and_returns_agent_result(gw):
    a = FakeAgent()
    sid = await _connect(gw, a, gw.new_pairing_code())
    await a.conn.sent.get()  # welcome
    req = ActionRequest(device_id="dev-1", action="get_status")

    async def agent_side():
        msg = await a.conn.sent.get()
        env = Envelope.model_validate(msg)
        verify(env, gw.core_key.public_key_hex)  # agent pins core key
        assert env.type == "action.request"
        assert env.payload["action"] == "get_status"
        await gw.handle_message(sid, a.envelope(
            "action.result", request_id=env.payload["request_id"], status="completed",
            output={"uptime": 42}))

    task = asyncio.create_task(agent_side())
    res = await gw.dispatch(req)
    await task
    assert res.status == ActionStatus.COMPLETED and res.output == {"uptime": 42}


async def test_dispatch_times_out_when_agent_is_silent(gw):
    a = FakeAgent()
    await _connect(gw, a, gw.new_pairing_code())
    gw.action_timeout_s = 0.05
    res = await gw.dispatch(ActionRequest(device_id="dev-1", action="get_status"))
    assert res.status == ActionStatus.FAILED and "timeout" in res.error


async def test_dispatch_to_offline_device_fails_fast(gw):
    res = await gw.dispatch(ActionRequest(device_id="dev-1", action="get_status"))
    assert res.status == ActionStatus.DEVICE_OFFLINE


async def test_result_for_unknown_request_is_ignored(gw):
    a = FakeAgent()
    sid = await _connect(gw, a, gw.new_pairing_code())
    await gw.handle_message(sid, a.envelope("action.result", request_id="req_ghost", status="completed"))
    # nothing raised, nothing crashed
    assert gw.is_online("dev-1")
