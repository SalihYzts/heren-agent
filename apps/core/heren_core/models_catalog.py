"""Model catalog for the Settings picker.

What Hermes can run = providers that have credentials (auth.json → credential_pool) × the models
models.dev knows for each provider. Heren never imports Hermes internals: a tiny script runs in
Hermes' own venv and prints JSON. Results are cached (models.dev changes rarely).
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("heren.models")

_LISTER = (
    "import json,sys\n"
    "from agent.models_dev import list_provider_models\n"
    "print(json.dumps(list_provider_models(sys.argv[1], allow_network=False)))\n"
)


@dataclass
class HermesHomeInfo:
    providers: list[str] = field(default_factory=list)
    default: dict[str, str | None] = field(default_factory=lambda: {"provider": None, "model": None})


def read_hermes_home(home: Path) -> HermesHomeInfo:
    """Providers with credentials + the configured default. Never raises."""
    info = HermesHomeInfo()
    try:
        auth = json.loads((home / "auth.json").read_text())
        pool = auth.get("credential_pool") or {}
        info.providers = [p for p in pool if isinstance(p, str)]
    except (OSError, ValueError, AttributeError) as e:
        log.info("hermes auth.json unreadable at %s: %s", home, e)
    try:
        cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
        model = cfg.get("model") or {}
        info.default = {"provider": model.get("provider"), "model": model.get("default")}
    except (OSError, ValueError, AttributeError) as e:
        log.info("hermes config.yaml unreadable at %s: %s", home, e)
    return info


def _list_models_subprocess(hermes_root: Path, provider: str, timeout_s: float = 20.0) -> list[str]:
    """Run the lister inside Hermes' venv. Raises on any failure (caller decides)."""
    python = hermes_root / "venv" / "bin" / "python"
    if not python.exists():
        raise FileNotFoundError(f"hermes venv not found: {python}")
    out = subprocess.run(
        [str(python), "-c", _LISTER, provider],
        cwd=hermes_root, capture_output=True, text=True, timeout=timeout_s, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip().splitlines()[-1] if (out.stderr or out.stdout).strip() else f"exit {out.returncode}")
    models = json.loads(out.stdout)
    if not isinstance(models, list):
        raise RuntimeError("lister returned non-list")
    return [m for m in models if isinstance(m, str)]


class ModelCatalog:
    def __init__(self, hermes_home: Path, hermes_root: Path, ttl_s: float = 3600.0) -> None:
        self.home = Path(hermes_home)
        self.root = Path(hermes_root)
        self.ttl_s = ttl_s
        self._cached: dict[str, Any] | None = None
        self._at = 0.0

    def get(self, refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if self._cached is not None and not refresh and now - self._at < self.ttl_s:
            return self._cached
        info = read_hermes_home(self.home)
        providers: list[dict[str, Any]] = []
        for p in info.providers:
            try:
                providers.append({"id": p, "models": _list_models_subprocess(self.root, p)})
            except Exception as e:  # one broken provider must not hide the others
                log.warning("model list for %s failed: %s", p, e)
                providers.append({"id": p, "models": [], "error": str(e)})
        self._cached = {"default": info.default, "providers": providers}
        self._at = now
        return self._cached
