"""Phase 3 additions to the HTTP surface: CORS for the dev UI, static UI hosting,
snapshot on event-stream connect, action history."""
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from nero_core.app import create_app
from nero_core.config import Settings
from nero_core.security import KeyPair

H = {"Authorization": "Bearer test-key"}


@pytest.fixture
def settings(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>nero</title>")
    (ui / "assets").mkdir()
    (ui / "assets" / "a.js").write_text("1")
    return Settings(db_path=tmp_path / "nero.db", api_key="test-key",
                    core_seed_hex=KeyPair.generate().seed_hex, ui_dir=ui,
                    cors_origins=["http://localhost:5173"])


async def test_cors_preflight_allows_configured_origin(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.options("/api/devices", headers={
                "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization"})
            assert r.status_code == 200
            assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
            r = await c.options("/api/devices", headers={
                "Origin": "http://evil", "Access-Control-Request-Method": "GET"})
            assert "access-control-allow-origin" not in r.headers


async def test_ui_is_served_at_root_with_spa_fallback(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert "<title>nero</title>" in (await c.get("/")).text
            assert (await c.get("/assets/a.js")).text == "1"
            assert "<title>nero</title>" in (await c.get("/devices/dev-1")).text  # SPA route
            assert (await c.get("/api/nope", headers=H)).status_code == 404  # api never falls back


async def test_action_history_endpoint(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/api/actions", headers=H)
            assert r.status_code == 200 and r.json() == []


def test_events_ws_sends_snapshot_first(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events?token=test-key") as ui:
            first = ui.receive_json()
            assert first["type"] == "ui.snapshot"
            assert first["payload"]["devices"] == []
            assert first["payload"]["approvals"] == []
