"""Model catalog for the Settings picker: which providers have credentials in the Hermes install,
and which models each can run. Sourced from Hermes' own venv via a subprocess (never imported)."""
import json
from pathlib import Path

import pytest

from heren_core import models_catalog as mc


def _fake_hermes_home(tmp_path: Path, pool=("copilot", "anthropic")) -> Path:
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "auth.json").write_text(json.dumps({"credential_pool": {p: {} for p in pool}, "active_provider": "copilot"}))
    (home / "config.yaml").write_text("model:\n  provider: copilot\n  default: gpt-4.1\n")
    return home


def test_providers_come_from_the_credential_pool_and_default_from_config(tmp_path):
    home = _fake_hermes_home(tmp_path)
    info = mc.read_hermes_home(home)
    assert info.providers == ["copilot", "anthropic"]
    assert info.default == {"provider": "copilot", "model": "gpt-4.1"}


def test_missing_or_broken_home_is_empty_not_fatal(tmp_path):
    info = mc.read_hermes_home(tmp_path / "nope")
    assert info.providers == [] and info.default == {"provider": None, "model": None}
    home = tmp_path / "h"; home.mkdir()
    (home / "auth.json").write_text("{not json")
    assert mc.read_hermes_home(home).providers == []


def test_catalog_runs_the_lister_once_per_provider_and_caches(tmp_path, monkeypatch):
    home = _fake_hermes_home(tmp_path)
    calls: list[str] = []

    def fake_list(hermes_root: Path, provider: str) -> list[str]:
        calls.append(provider)
        return {"copilot": ["gpt-4.1", "claude-opus-5"], "anthropic": ["claude-sonnet-4-6"]}[provider]

    monkeypatch.setattr(mc, "_list_models_subprocess", fake_list)
    cat = mc.ModelCatalog(hermes_home=home, hermes_root=tmp_path, ttl_s=3600)
    first = cat.get()
    assert first["default"] == {"provider": "copilot", "model": "gpt-4.1"}
    assert [p["id"] for p in first["providers"]] == ["copilot", "anthropic"]
    assert first["providers"][0]["models"] == ["gpt-4.1", "claude-opus-5"]
    cat.get()
    assert calls == ["copilot", "anthropic"], "second call served from cache"


def test_a_provider_whose_lister_fails_is_listed_with_no_models(tmp_path, monkeypatch):
    home = _fake_hermes_home(tmp_path)

    def fake_list(hermes_root: Path, provider: str) -> list[str]:
        if provider == "anthropic":
            raise RuntimeError("venv exploded")
        return ["gpt-4.1"]

    monkeypatch.setattr(mc, "_list_models_subprocess", fake_list)
    cat = mc.ModelCatalog(hermes_home=home, hermes_root=tmp_path, ttl_s=3600).get()
    assert cat["providers"][1] == {"id": "anthropic", "models": [], "error": "venv exploded"}


@pytest.mark.skipif(not (Path.home() / ".hermes/hermes-agent/venv/bin/python").exists(), reason="no local Hermes install")
def test_real_hermes_venv_lists_models_for_a_known_provider():
    """Integration: the subprocess path against the real install (offline catalog)."""
    models = mc._list_models_subprocess(Path.home() / ".hermes/hermes-agent", "anthropic")
    assert isinstance(models, list) and models and all(isinstance(m, str) for m in models)
