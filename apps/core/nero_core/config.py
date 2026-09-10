"""Settings — every tunable lives here (no magic constants in modules).

Load order: defaults < YAML file (NERO_CONFIG) < environment (NERO_*).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class Settings(BaseModel):
    # server
    host: str = "127.0.0.1"
    port: int = 8700
    api_key: str = "change-me"
    db_path: Path = Path("data/nero.db")
    core_seed_hex: str | None = None  # ed25519 seed; generated + persisted if None
    ui_dir: Path | None = None  # built UI (apps/ui/dist); served at / when set
    cors_origins: list[str] = Field(default_factory=list)  # dev UI origins, e.g. http://localhost:5173

    # actions / permissions
    approval_ttl_s: float = 60.0
    critical_enabled: bool = False
    approved_commands: dict[str, list[str]] = Field(default_factory=dict)  # command_id → argv

    # device gateway
    heartbeat_timeout_s: float = 30.0
    action_timeout_s: float = 30.0
    pairing_code_ttl_s: float = 300.0

    # character
    sleep_start: str = "23:00"
    deep_sleep_start: str = "00:00"
    wake_word: str = "Nero"
    language: str = "tr"

    # hermes bridge
    hermes_endpoint: str = "http://127.0.0.1:8642"
    hermes_api_key: str | None = None

    # voice
    stt_provider: str = "none"
    tts_provider: str = "none"

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> Settings:
        data: dict[str, Any] = {}
        cfg = Path(path or os.environ.get("NERO_CONFIG", "nero.yaml"))
        if cfg.exists():
            data.update(yaml.safe_load(cfg.read_text()) or {})
        for name, field in cls.model_fields.items():
            env = os.environ.get(f"NERO_{name.upper()}")
            if env is not None:
                ann = str(field.annotation)
                data[name] = [s.strip() for s in env.split(",") if s.strip()] if "list" in ann else env
        return cls.model_validate(data)
