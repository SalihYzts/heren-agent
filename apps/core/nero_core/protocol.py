"""Protocol models — the wire and storage contract for Nero.

Everything that crosses a process boundary (UI ↔ core, core ↔ agent, Hermes MCP ↔ core)
is defined here. Keep this module free of I/O and framework imports.
"""
from __future__ import annotations

import re
import secrets
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------- risk


class RiskLevel(StrEnum):
    LOW = "low"  # auto
    MEDIUM = "medium"  # auto + audit
    HIGH = "high"  # user approval
    CRITICAL = "critical"  # user approval + PIN (disabled until phase 9)


BUILTIN_ACTION_RISK: dict[str, RiskLevel] = {
    "get_status": RiskLevel.LOW,
    "get_metrics": RiskLevel.LOW,
    "get_boot_entries": RiskLevel.LOW,
    "lock": RiskLevel.MEDIUM,
    "launch_app": RiskLevel.MEDIUM,
    "stop_app": RiskLevel.MEDIUM,
    "restart_service": RiskLevel.MEDIUM,
    "run_approved_command": RiskLevel.MEDIUM,
    "sleep": RiskLevel.HIGH,
    "wake": RiskLevel.MEDIUM,
    "shutdown": RiskLevel.HIGH,
    "restart": RiskLevel.HIGH,
    "set_next_boot": RiskLevel.HIGH,
}


def risk_of(action: str) -> RiskLevel:
    """Unknown actions fail closed to CRITICAL."""
    return BUILTIN_ACTION_RISK.get(action, RiskLevel.CRITICAL)


# --------------------------------------------------------------------------- ids

_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def now_ts() -> float:
    return time.time()


# --------------------------------------------------------------------------- device


class DeviceStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class Device(BaseModel):
    device_id: str
    name: str
    platform: str  # linux | windows | ...
    public_key: str  # hex ed25519 verify key
    status: DeviceStatus = DeviceStatus.OFFLINE
    last_seen: float | None = None
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("device_id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("device_id must be [A-Za-z0-9_.:-]{1,128}")
        return v


# --------------------------------------------------------------------------- action


class ActionStatus(StrEnum):
    PENDING = "pending"  # created, not yet gated
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEVICE_OFFLINE = "device_offline"


TERMINAL_STATUSES = frozenset(
    {
        ActionStatus.DENIED,
        ActionStatus.EXPIRED,
        ActionStatus.COMPLETED,
        ActionStatus.FAILED,
        ActionStatus.DEVICE_OFFLINE,
    }
)


class ActionRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: new_id("req"))
    device_id: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "ui"  # ui | hermes | macro:<name> | schedule:<id>
    created_at: float = Field(default_factory=now_ts)
    status: ActionStatus = ActionStatus.PENDING
    approved_by: str | None = None

    @property
    def risk(self) -> RiskLevel:
        return risk_of(self.action)

    @model_validator(mode="after")
    def _guard_params(self) -> ActionRequest:
        if self.action == "run_approved_command":
            if "command" in self.params or "command_id" not in self.params:
                raise ValueError("run_approved_command takes command_id only (no free-text command)")
        return self


class ActionResult(BaseModel):
    request_id: str
    status: ActionStatus
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


# --------------------------------------------------------------------------- events


class Event(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=now_ts)

    @field_validator("type")
    @classmethod
    def _namespaced(cls, v: str) -> str:
        if not _EVENT_TYPE_RE.match(v):
            raise ValueError("event type must be dotted lowercase, e.g. device.online")
        return v


# --------------------------------------------------------------------------- envelope


class Envelope(BaseModel):
    """Signed message between core and a device agent (either direction)."""

    id: str = Field(default_factory=lambda: new_id("msg"))
    ts: float = Field(default_factory=now_ts)
    nonce: str = Field(default_factory=lambda: secrets.token_hex(16))
    device_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    sig: str | None = None  # hex ed25519 signature over canonical bytes

    def canonical_bytes(self) -> bytes:
        """Bytes that get signed: everything except `sig`, key-sorted."""
        data = self.model_dump(exclude={"sig"})
        import json

        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
