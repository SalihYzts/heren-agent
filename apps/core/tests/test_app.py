"""HTTP/WS surface: Action API for UI + Hermes MCP, agent WebSocket, UI event stream."""
import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from heren_core.app import create_app
from heren_core.config import Settings
from heren_core.protocol import Envelope
from heren_core.security import KeyPair, sign, verify


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "heren.db", api_key="test-key", core_seed_hex=KeyPair.generate().seed_hex,
                    approval_ttl_s=60, heartbeat_timeout_s=30, action_timeout_s=2)


@pytest.fixture
def app(settings):
    return create_app(settings)


H = {"Authorization": "Bearer test-key"}


async def test_health_is_public(app):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_api_requires_bearer_key(app):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/api/devices")).status_code == 401
            assert (await c.get("/api/devices", headers={"Authorization": "Bearer wrong"})).status_code == 401
            assert (await c.get("/api/devices", headers=H)).status_code == 200


async def test_pairing_code_endpoint_returns_six_digits(app):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/devices/pairing-code", headers=H)
    assert r.status_code == 200
    assert len(r.json()["code"]) == 6 and r.json()["code"].isdigit()


async def test_action_on_unknown_device_is_404(app):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/actions", headers=H, json={"device_id": "ghost", "action": "get_status"})
    assert r.status_code == 404


def _pair_agent(client: TestClient, code: str, device_id="dev-1"):
    """Open the agent WS, send hello, return (ws, keypair). Sync TestClient for WS."""
    kp = KeyPair.generate()
    cm = client.websocket_connect("/ws/agent")
    ws = cm.__enter__()
    ws._cm = cm  # closed via _close(ws)
    ws.send_json({"type": "hello", "device_id": device_id, "name": "PC", "platform": "linux",
                  "public_key": kp.public_key_hex, "capabilities": ["get_status", "shutdown"],
                  "pairing_code": code})
    welcome = ws.receive_json()
    assert welcome["type"] == "welcome"
    return ws, kp, welcome["core_public_key"]


def _close(ws):
    ws._cm.__exit__(None, None, None)


def test_paired_device_is_listed_online(app):
    with TestClient(app) as client:
        code = client.post("/api/devices/pairing-code", headers=H).json()["code"]
        ws, kp, core_pk = _pair_agent(client, code)
        devs = client.get("/api/devices", headers=H).json()
        assert devs[0]["device_id"] == "dev-1" and devs[0]["status"] == "online"
        assert "public_key" in devs[0]
        _close(ws)


def test_action_roundtrip_with_agent_answering(app):
    import threading

    with TestClient(app) as client:
        code = client.post("/api/devices/pairing-code", headers=H).json()["code"]
        ws, kp, core_pk = _pair_agent(client, code)

        result_holder = {}

        def agent_loop():
            msg = ws.receive_json()
            env = Envelope.model_validate(msg)
            verify(env, core_pk)
            assert env.type == "action.request" and env.payload["action"] == "get_status"
            reply = sign(Envelope(device_id="dev-1", type="action.result",
                                  payload={"request_id": env.payload["request_id"], "status": "completed",
                                           "output": {"uptime": 7}}), kp)
            ws.send_json(reply.model_dump())

        t = threading.Thread(target=agent_loop)
        t.start()
        r = client.post("/api/actions", headers=H, json={"device_id": "dev-1", "action": "get_status"})
        t.join(timeout=3)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed" and body["output"] == {"uptime": 7}

        audit = client.get("/api/audit", headers=H).json()
        assert audit[0]["action"] == "get_status" and audit[0]["result"] == "completed"
        _close(ws)


def test_high_risk_flow_requires_approval_via_api(app):
    import threading

    with TestClient(app) as client:
        code = client.post("/api/devices/pairing-code", headers=H).json()["code"]
        ws, kp, core_pk = _pair_agent(client, code)

        with client.websocket_connect("/ws/events?token=test-key") as ui:
            r = client.post("/api/actions", headers=H,
                            json={"device_id": "dev-1", "action": "shutdown", "requested_by": "hermes"})
            assert r.status_code == 202, r.text
            rid = r.json()["request_id"]
            assert r.json()["status"] == "awaiting_approval"

            ev = ui.receive_json()
            while ev["type"] != "ui.approval.needed":
                ev = ui.receive_json()
            assert ev["payload"]["request_id"] == rid and ev["payload"]["risk"] == "high"

            pending = client.get("/api/approvals", headers=H).json()
            assert [p["request_id"] for p in pending] == [rid]

            # Hermes may not approve
            r = client.post(f"/api/approvals/{rid}/approve", headers=H, json={"approved_by": "hermes"})
            assert r.status_code == 403

            def agent_loop():
                msg = ws.receive_json()
                env = Envelope.model_validate(msg)
                reply = sign(Envelope(device_id="dev-1", type="action.result",
                                      payload={"request_id": env.payload["request_id"],
                                               "status": "completed", "output": {}}), kp)
                ws.send_json(reply.model_dump())

            t = threading.Thread(target=agent_loop)
            t.start()
            r = client.post(f"/api/approvals/{rid}/approve", headers=H, json={"approved_by": "ui:salih"})
            t.join(timeout=3)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "completed"

            audit = client.get("/api/audit", headers=H).json()
            assert audit[0]["approved_by"] == "ui:salih" and audit[0]["risk"] == "high"
        _close(ws)


def test_deny_endpoint(app):
    with TestClient(app) as client:
        code = client.post("/api/devices/pairing-code", headers=H).json()["code"]
        ws, kp, _ = _pair_agent(client, code)
        rid = client.post("/api/actions", headers=H,
                          json={"device_id": "dev-1", "action": "shutdown"}).json()["request_id"]
        r = client.post(f"/api/approvals/{rid}/deny", headers=H, json={"denied_by": "ui:salih"})
        assert r.status_code == 200 and r.json()["status"] == "denied"
        assert client.post(f"/api/approvals/{rid}/approve", headers=H,
                           json={"approved_by": "ui:salih"}).status_code == 404
        _close(ws)


def test_events_ws_requires_token(app):
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/events?token=wrong") as ui:
                ui.receive_json()
