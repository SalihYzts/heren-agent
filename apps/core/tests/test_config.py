

def test_explicit_config_path_that_does_not_exist_is_an_error(tmp_path, monkeypatch):
    """A typo in HEREN_CONFIG must not silently boot a mute Heren (tts=none, stt=none)."""
    from heren_core.config import Settings
    import pytest
    monkeypatch.setenv("HEREN_CONFIG", str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError, match="HEREN_CONFIG"):
        Settings.load()
    # the implicit default (heren.yaml in cwd) may be absent — that is fine
    monkeypatch.delenv("HEREN_CONFIG")
    monkeypatch.chdir(tmp_path)
    Settings.load()
