"""Settings — every tunable lives here (no magic constants in modules).

Load order: defaults < YAML file (HEREN_CONFIG) < environment (HEREN_*).
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
    db_path: Path = Path("data/heren.db")
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

    # character (time rules; the rest of CharacterConfig via `character:` mapping)
    sleep_start: str = "23:00"
    deep_sleep_start: str = "00:00"
    wake_time: str = "07:00"
    character: dict[str, Any] = Field(default_factory=dict)  # extra CharacterConfig overrides
    character_tick_s: float = 1.0
    wake_word: str = "Heren"
    language: str = "tr"

    def character_config(self) -> Any:
        from heren_core.character import CharacterConfig

        return CharacterConfig(sleep_start=self.sleep_start, deep_sleep_start=self.deep_sleep_start,
                               wake_time=self.wake_time, **self.character)

    # hermes bridge
    hermes_endpoint: str = "http://127.0.0.1:8642"
    hermes_api_key: str | None = None
    hermes_session_id: str = "heren"
    hermes_language: str = "Turkish"
    hermes_request_timeout_s: float = 600.0
    mcp_key: str = "change-me-mcp"  # Hermes → /mcp bearer (separate from api_key)
    mcp_allowed_hosts: list[str] = Field(default_factory=list)  # e.g. ["127.0.0.1:8700"]; empty = any

    # voice — provider name + free-form options (e.g. tts_options: {model: data/voices/x.onnx})
    stt_provider: str = "none"
    stt_options: dict[str, Any] = Field(default_factory=dict)
    tts_provider: str = "none"
    tts_options: dict[str, Any] = Field(default_factory=dict)
    voice_max_clips: int = 64

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> Settings:
        data: dict[str, Any] = {}
        cfg = Path(path or os.environ.get("HEREN_CONFIG", "heren.yaml"))
        if cfg.exists():
            data.update(yaml.safe_load(cfg.read_text()) or {})
        for name, field in cls.model_fields.items():
            env = os.environ.get(f"HEREN_{name.upper()}")
            if env is not None:
                ann = str(field.annotation)
                data[name] = [s.strip() for s in env.split(",") if s.strip()] if "list" in ann else env
        return cls.model_validate(data)
