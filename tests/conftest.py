import os
import shutil
import tempfile

import pytest

import app


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Every config file (settings, profiles, history) resolves under
    XDG_CONFIG_HOME — point it at a temp dir so no test touches the real
    ~/.config/ytdlp-gui."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)   # the instance socket then lands under the temp config dir too


@pytest.fixture(autouse=True)
def drain_queues(monkeypatch):
    """A job's done/notify/history hooks run on its worker thread after
    the status flips, so a test that returns the moment its queue looks
    idle can leave a history write racing the env restore — and landing
    in the real ~/.config. Wait for every queue the test created."""
    import app
    queues = []
    original = app.DownloadQueue.__init__

    def tracking_init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        queues.append(self)
    monkeypatch.setattr(app.DownloadQueue, "__init__", tracking_init)
    yield
    for q in queues:
        q.wait_idle(5)


@pytest.fixture
def sock_path():
    """A Unix socket path short enough for macOS's ~104-byte limit —
    pytest's tmp_path is far longer than that."""
    d = tempfile.mkdtemp(prefix="ytg")
    try:
        yield os.path.join(d, "s")
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def no_js_runtime(monkeypatch):
    """build_args() (and so info_args() and every job) calls
    find_js_runtime() to inject --js-runtimes. Empty the candidate list so
    argv never depends on which runtime the test machine happens to have;
    tests that want one set their own candidates or pin find_js_runtime."""
    monkeypatch.setattr(app, "JS_RUNTIME_CANDIDATES", [])
