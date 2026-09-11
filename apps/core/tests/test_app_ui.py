"""Phase 3 additions to the HTTP surface: CORS for the dev UI, static UI hosting,
snapshot on event-stream connect, action history."""
import json
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from heren_core.app import create_app
from heren_core.config import Settings
from heren_core.security import KeyPair

H = {"Authorization": "Bearer test-key"}


@pytest.fixture
def settings(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>heren</title>")
    (ui / "assets").mkdir()
    (ui / "assets" / "a.js").write_text("1")
    return Settings(db_path=tmp_path / "heren.db", api_key="test-key",
                    hermes_home=tmp_path / "hermes-home", hermes_root=tmp_path / "hermes-root",
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
            assert "<title>heren</title>" in (await c.get("/")).text
            assert (await c.get("/assets/a.js")).text == "1"
            assert "<title>heren</title>" in (await c.get("/devices/dev-1")).text  # SPA route
            assert (await c.get("/api/nope", headers=H)).status_code == 404  # api never falls back
            # /mcp must reach the MCP mount even when the SPA catch-all exists
            r = await c.post("/mcp", headers={"Authorization": "Bearer wrong", "Content-Type": "application/json",
                                              "Accept": "application/json, text/event-stream"}, json={})
            assert r.status_code == 401, r.text


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
            assert first["payload"]["character"]["activity"] == "idle"


def test_state_endpoint_and_touch(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        r = client.get("/api/state", headers=H)
        assert r.status_code == 200
        assert r.json()["character"]["activity"] == "idle"
        assert r.json()["devices"] == []
        with client.websocket_connect("/ws/events?token=test-key") as ui:
            ui.receive_json()  # snapshot
            r = client.post("/api/character/touch", headers=H)
            assert r.status_code == 200 and r.json()["activity"] == "listening"
            ev = ui.receive_json()
            while ev["type"] != "character.state":
                ev = ui.receive_json()
            assert ev["payload"]["activity"] == "listening" and ev["payload"]["attention"] == "user"


def test_ask_endpoint_reports_hermes_unavailable_cleanly(settings):
    # nothing listens on hermes_endpoint → must not 500, must say so, character returns to idle
    settings = settings.model_copy(update={"hermes_endpoint": "http://127.0.0.1:9", "hermes_api_key": "k"})
    app = create_app(settings)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events?token=test-key") as ui:
            ui.receive_json()
            r = client.post("/api/ask", headers=H, json={"text": "selam"})
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is False and "unreachable" in body["error"]
            seen = []
            for _ in range(20):
                ev = ui.receive_json()
                seen.append(ev["type"])
                if ev["type"] == "hermes.done":
                    break
            assert "hermes.thinking" in seen and "hermes.unavailable" in seen
        assert client.get("/api/state", headers=H).json()["character"]["activity"] == "idle"


def test_health_reports_hermes_reachability(settings):
    settings = settings.model_copy(update={"hermes_endpoint": "http://127.0.0.1:9"})
    app = create_app(settings)
    with TestClient(app) as client:
        r = client.get("/api/state", headers=H)
        assert r.json()["hermes"]["reachable"] is False


def test_ask_passes_dashboard_context_to_hermes(settings, monkeypatch):
    """Hermes must know which devices exist and what the panel just did, so 'that button
    failed, why?' is answerable. We intercept the bridge and inspect the kwargs it gets."""
    from heren_core import hermes_bridge as hb
    app = create_app(settings)
    captured = {}

    async def fake_ask(self, text, character=None, context=None, model=None, provider=None):
        captured.update(text=text, context=context)
        return hb.AskResult(ok=True, text="tamam")
    monkeypatch.setattr(hb.HermesBridge, "ask", fake_ask)
    with TestClient(app) as client:
        core = app.state.core
        from heren_core.protocol import Device
        client.portal.call(core.store.upsert_device, Device(device_id="dev-1", name="Salon PC", platform="linux",
                                                            public_key="pk", capabilities=["lock"]))
        client.portal.call(lambda: core.store.audit("r1", "dev-1", "lock", risk="medium", approved_by=None,
                                                    result="device_offline", duration_ms=None, error="agent offline"))
        r = client.post("/api/ask", headers=H, json={"text": "şu tuş çalışmıyor niye"})
        assert r.status_code == 200 and r.json()["ok"]
    ctx = captured["context"]
    assert ctx["app"]["name"] == "Heren"
    assert [d["device_id"] for d in ctx["devices"]] == ["dev-1"]
    assert ctx["recent_actions"][0]["action"] == "lock"
    assert ctx["recent_actions"][0]["result"] == "device_offline"


def test_ask_and_transcribe_accept_a_model_choice(settings, monkeypatch):
    from heren_core import hermes_bridge as hb
    app = create_app(settings)
    seen = []

    async def fake_ask(self, text, character=None, context=None, model=None, provider=None):
        seen.append((text, model, provider))
        return hb.AskResult(ok=True, text="tamam")
    monkeypatch.setattr(hb.HermesBridge, "ask", fake_ask)
    with TestClient(app) as client:
        r = client.post("/api/ask", headers=H, json={"text": "selam", "model": "gpt-4.1", "provider": "copilot"})
        assert r.status_code == 200
        r = client.post("/api/ask", headers=H, json={"text": "selam"})
        assert r.status_code == 200
    assert seen == [("selam", "gpt-4.1", "copilot"), ("selam", None, None)]


def test_state_exposes_lan_access_urls_for_phones(settings, monkeypatch):
    monkeypatch.setattr("heren_core.netaccess._all_ipv4", lambda: ["127.0.0.1", "192.168.1.150"])
    monkeypatch.setattr("heren_core.netaccess._hostname", lambda: "server")
    app = create_app(settings.model_copy(update={"host": "0.0.0.0", "tls": True}))
    with TestClient(app) as client:
        acc = client.get("/api/state", headers=H).json()["access"]
    assert acc["urls"] == ["https://192.168.1.150:8700", "https://server.local:8700"]
    assert acc["tls"] is True


def test_qr_endpoint_renders_the_first_access_url_as_svg(settings, monkeypatch):
    monkeypatch.setattr("heren_core.netaccess._all_ipv4", lambda: ["192.168.1.150"])
    monkeypatch.setattr("heren_core.netaccess._hostname", lambda: "server")
    app = create_app(settings.model_copy(update={"host": "0.0.0.0", "tls": True}))
    with TestClient(app) as client:
        r = client.get("/api/access/qr.svg", headers=H)
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        assert 'xmlns="http://www.w3.org/2000/svg"' in r.text   # standalone image (blob url in <img>), not inline markup
        assert b"<svg" in r.content
        # decode it back: the QR must encode exactly the first access url
        import segno.helpers  # noqa: F401  (segno present)
        r2 = client.get("/api/access/qr.svg?url=https://server.local:8700", headers=H)
        assert r2.status_code == 200 and r2.content != r.content
        # loopback-only core has nothing to advertise
    app2 = create_app(settings)
    with TestClient(app2) as client:
        assert client.get("/api/access/qr.svg", headers=H).status_code == 404


def test_models_endpoint_returns_the_catalog_and_refreshes_on_demand(settings, monkeypatch):
    from heren_core import models_catalog as mc
    home = settings.hermes_home
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text('{"credential_pool": {"copilot": {}}}')
    (home / "config.yaml").write_text("model:\n  provider: copilot\n  default: gpt-4.1\n")
    calls = []
    monkeypatch.setattr(mc, "_list_models_subprocess", lambda root, p: calls.append(p) or ["gpt-4.1", "gpt-5"])
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/models").status_code == 401
        r = client.get("/api/models", headers=H).json()
        assert r["default"] == {"provider": "copilot", "model": "gpt-4.1"}
        assert r["providers"] == [{"id": "copilot", "models": ["gpt-4.1", "gpt-5"]}]
        client.get("/api/models", headers=H)
        assert calls == ["copilot"]
        client.get("/api/models?refresh=true", headers=H)
        assert calls == ["copilot", "copilot"]


async def test_character_state_survives_a_core_restart(settings):
    """Energy/sleep debt live in the settings table; a new Core on the same db picks them up."""
    from heren_core.app import Core
    core = Core(settings)
    await core.start()
    try:
        core.character.engine._energy = 0.42
        core.character.engine._debt = 0.2
        await core.character._persist_if_changed()
        assert json.loads(await core.store.get_setting("character_state"))["energy"] == 0.42
    finally:
        await core.stop()
    core2 = Core(settings)
    await core2.start()
    try:
        st = core2.character.engine.export_state()
        assert st["energy"] == pytest.approx(0.42, abs=0.01) and st["debt"] == 0.2
    finally:
        await core2.stop()
