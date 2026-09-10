"""MCP server exposing device control to Hermes. Every call goes through ActionService
with requested_by='hermes' — so HIGH risk still waits for the user."""
import json

import pytest
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from heren_core.app import create_app
from heren_core.config import Settings
from heren_core.protocol import Device, DeviceStatus
from heren_core.security import KeyPair


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "t.db", api_key="ui-key", mcp_key="mcp-key",
                    core_seed_hex=KeyPair.generate().seed_hex)


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    def is_online(self, device_id):
        return device_id == "pc"

    async def dispatch(self, req):
        from heren_core.protocol import ActionResult, ActionStatus
        self.calls.append(req)
        return ActionResult(request_id=req.request_id, status=ActionStatus.COMPLETED, output={"uptime_s": 5})


async def _mcp(app, key="mcp-key"):
    """Open an MCP client session against the in-process app (mcp 2.x API)."""
    client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t",
                                headers={"Authorization": f"Bearer {key}"}, timeout=10)
    return streamable_http_client("http://t/mcp", http_client=client)


async def _seed(app):
    core = app.state.core
    await core.store.upsert_device(Device(device_id="pc", name="MAIN PC", platform="linux",
                                          public_key="ab" * 32, capabilities=["get_status", "shutdown"]))
    await core.store.set_device_status("pc", DeviceStatus.ONLINE)
    disp = FakeDispatcher()
    core.actions.dispatcher = disp
    return disp


async def test_lists_tools_and_devices(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await _seed(app)
        async with await _mcp(app) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert {"device_list", "device_status", "device_action"} <= names
                res = await s.call_tool("device_list", {})
                data = json.loads(res.content[0].text)
                assert data[0]["device_id"] == "pc" and data[0]["status"] == "online"


async def test_low_risk_action_runs_and_is_attributed_to_hermes(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        disp = await _seed(app)
        async with await _mcp(app) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool("device_action", {"device_id": "pc", "action": "get_status"})
                data = json.loads(res.content[0].text)
                assert data["status"] == "completed" and data["output"]["uptime_s"] == 5
        assert disp.calls[0].requested_by == "hermes"
        audit = await app.state.core.store.list_audit()
        assert audit[0]["action"] == "get_status"


async def test_high_risk_action_returns_awaiting_approval_and_does_not_run(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        disp = await _seed(app)
        async with await _mcp(app) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool("device_action", {"device_id": "pc", "action": "shutdown"})
                data = json.loads(res.content[0].text)
                assert data["status"] == "awaiting_approval"
                assert "approval" in data["message"].lower()
        assert disp.calls == []
        pending = await app.state.core.actions.list_pending_approvals()
        assert pending[0].requested_by == "hermes"


async def test_unknown_device_and_bad_key(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await _seed(app)
        async with await _mcp(app) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool("device_action", {"device_id": "ghost", "action": "get_status"})
                assert res.is_error or "unknown" in res.content[0].text
        with pytest.raises(Exception):
            async with await _mcp(app, key="wrong") as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
