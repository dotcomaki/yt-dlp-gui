import pytest


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Every config file (settings, profiles, history) resolves under
    XDG_CONFIG_HOME — point it at a temp dir so no test touches the real
    ~/.config/ytdlp-gui."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
