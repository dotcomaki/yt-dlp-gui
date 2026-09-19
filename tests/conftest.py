import os
import shutil
import tempfile

import pytest


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Every config file (settings, profiles, history) resolves under
    XDG_CONFIG_HOME — point it at a temp dir so no test touches the real
    ~/.config/ytdlp-gui."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)   # the instance socket then lands under the temp config dir too


@pytest.fixture
def sock_path():
    """A Unix socket path short enough for macOS's ~104-byte limit —
    pytest's tmp_path is far longer than that."""
    d = tempfile.mkdtemp(prefix="ytg")
    try:
        yield os.path.join(d, "s")
    finally:
        shutil.rmtree(d, ignore_errors=True)
