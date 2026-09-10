"""Protocol models: the single source of truth shared by UI, core, agents, Hermes MCP."""
import pytest
from pydantic import ValidationError

from nero_core.protocol import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    Device,
    DeviceStatus,
    Envelope,
    Event,
    RiskLevel,
    risk_of,
)


def test_builtin_actions_have_fixed_risk_levels():
    assert risk_of("get_status") == RiskLevel.LOW
    assert risk_of("get_metrics") == RiskLevel.LOW
    assert risk_of("restart_service") == RiskLevel.MEDIUM
    assert risk_of("launch_app") == RiskLevel.MEDIUM
    assert risk_of("shutdown") == RiskLevel.HIGH
    assert risk_of("restart") == RiskLevel.HIGH
    assert risk_of("set_next_boot") == RiskLevel.HIGH


def test_unknown_action_is_critical_by_default():
    # Fail closed: anything we did not classify needs the strongest gate.
    assert risk_of("format_disk") == RiskLevel.CRITICAL
    assert risk_of("") == RiskLevel.CRITICAL


def test_action_request_derives_risk_and_ids():
    req = ActionRequest(device_id="dev-1", action="shutdown")
    assert req.risk == RiskLevel.HIGH
    assert req.request_id.startswith("req_")
    assert req.params == {}
    assert req.status == ActionStatus.PENDING


def test_action_request_rejects_free_text_command_for_run_approved_command():
    # run_approved_command takes a command *id* from config, never a shell string.
    with pytest.raises(ValidationError):
        ActionRequest(device_id="dev-1", action="run_approved_command", params={"command": "rm -rf /"})
    ok = ActionRequest(device_id="dev-1", action="run_approved_command", params={"command_id": "start-backend"})
    assert ok.params["command_id"] == "start-backend"


def test_device_defaults_to_offline():
    d = Device(device_id="dev-1", name="MAIN PC", platform="linux", public_key="a" * 64)
    assert d.status == DeviceStatus.OFFLINE
    assert d.last_seen is None


def test_device_id_must_be_public_key_fingerprint_shape():
    with pytest.raises(ValidationError):
        Device(device_id="has space", name="x", platform="linux", public_key="a" * 64)


def test_event_has_namespace_and_timestamp():
    ev = Event(type="device.online", payload={"device_id": "dev-1"})
    assert ev.type == "device.online"
    assert ev.ts > 0
    with pytest.raises(ValidationError):
        Event(type="not_namespaced", payload={})


def test_envelope_round_trips_json_and_carries_nonce():
    env = Envelope(device_id="dev-1", type="action.request", payload={"action": "get_status"})
    raw = env.model_dump_json()
    back = Envelope.model_validate_json(raw)
    assert back == env
    assert len(env.nonce) >= 16
    assert env.sig is None


def test_action_result_marks_terminal_states():
    ok = ActionResult(request_id="req_x", status=ActionStatus.COMPLETED, output={"uptime": 3})
    assert ok.is_terminal
    fail = ActionResult(request_id="req_x", status=ActionStatus.FAILED, error="boom")
    assert fail.is_terminal
    running = ActionResult(request_id="req_x", status=ActionStatus.RUNNING)
    assert not running.is_terminal
