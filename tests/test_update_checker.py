"""Tests for the yt-dlp update checker: version parsing/comparison,
install-method detection (which decides whether an in-app update is even
possible), update command construction, the GitHub lookup (mocked — no
network in tests), and the Api methods wired on top."""
import io
import json
import stat

import pytest

import app


# --- version parsing / comparison ---------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("2026.08.19", (2026, 8, 19)),
    ("2026.08.19.123456", (2026, 8, 19, 123456)),   # nightly channel
    ("  2026.08.19\n", (2026, 8, 19)),               # --version output has a newline
    ("", None),
    (None, None),
    ("abc", None),
    ("2026.08.19-dev", None),
    ("594bd50c2", None),                             # a git hash, not a version
])
def test_parse_version(text, expected):
    assert app.parse_version(text) == expected


@pytest.mark.parametrize("latest,current,expected", [
    ("2026.09.10", "2026.08.19", True),
    ("2026.08.19", "2026.08.19", False),
    ("2026.08.19", "2026.09.10", False),           # somehow ahead of stable
    ("2027.01.01", "2026.12.31", True),
    ("2026.08.19", "2026.08.19.123456", False),    # nightly of the same day is not behind
    ("2026.09.10", "2026.08.19.123456", True),     # but an older nightly is
    ("garbage", "2026.08.19", False),
    ("2026.09.10", "garbage", False),
])
def test_is_newer(latest, current, expected):
    assert app.is_newer(latest, current) is expected


# --- GitHub lookup (mocked) ------------------------------------------------------

class FakeResponse(io.StringIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_latest_version_reads_tag_name(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["url"] = req.full_url
        captured["ua"] = req.get_header("User-agent")
        captured["timeout"] = timeout
        return FakeResponse(json.dumps({"tag_name": "2026.09.10"}))

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)
    assert app.fetch_latest_version() == "2026.09.10"
    assert captured["url"] == app.RELEASE_APIS["stable"]
    # GitHub's API rejects requests with no User-Agent
    assert captured["ua"]
    # never block the UI indefinitely if GitHub is slow/unreachable
    assert captured["timeout"]


def test_fetch_latest_version_propagates_network_errors(monkeypatch):
    def fake_urlopen(req, timeout=None, context=None):
        raise OSError("no network")

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(OSError):
        app.fetch_latest_version()


# --- install method detection ----------------------------------------------------

def _write(path, data, executable=True):
    if isinstance(data, str):
        data = data.encode()
    path.write_bytes(data)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_detect_standalone_binary(tmp_path):
    binary = tmp_path / "yt-dlp"
    _write(binary, b"\xcf\xfa\xed\xfe" + b"\x00" * 64)  # Mach-O magic, no shebang
    assert app.detect_install_method(str(binary)) == ("standalone", None)


def test_detect_pip_script_with_absolute_shebang(tmp_path):
    script = tmp_path / "yt-dlp"
    _write(script, "#!/home/alice/venv/bin/python3\n# -*- coding: utf-8 -*-\nimport re\n")
    assert app.detect_install_method(str(script)) == ("pip", "/home/alice/venv/bin/python3")


def test_detect_pip_script_with_env_shebang_resolves_interpreter(tmp_path, monkeypatch):
    script = tmp_path / "yt-dlp"
    _write(script, "#!/usr/bin/env python3\n")
    monkeypatch.setattr(app.shutil, "which", lambda name: "/resolved/python3" if name == "python3" else None)
    assert app.detect_install_method(str(script)) == ("pip", "/resolved/python3")


def test_detect_homebrew_by_path():
    # Homebrew's yt-dlp is a python script under Cellar, but the path is
    # decisive before we ever read the file (which needn't exist here).
    assert app.detect_install_method("/opt/homebrew/bin/yt-dlp") == ("homebrew", None)
    assert app.detect_install_method("/usr/local/Cellar/yt-dlp/2026.8.19/bin/yt-dlp") == ("homebrew", None)
    assert app.detect_install_method("/home/linuxbrew/.linuxbrew/bin/yt-dlp") == ("homebrew", None)


def test_detect_distro_package_by_path():
    # /usr/bin/yt-dlp from apt/dnf/pacman is also a python script with a
    # shebang, but its system python blocks pip (PEP 668) — must not be "pip".
    assert app.detect_install_method("/usr/bin/yt-dlp") == ("package", None)


def test_detect_follows_symlinks(tmp_path):
    real = tmp_path / "real-yt-dlp"
    _write(real, "#!/some/venv/bin/python3\n")
    link = tmp_path / "yt-dlp"
    link.symlink_to(real)
    assert app.detect_install_method(str(link)) == ("pip", "/some/venv/bin/python3")


def test_detect_unreadable_path_falls_back_to_standalone(tmp_path):
    assert app.detect_install_method(str(tmp_path / "missing")) == ("standalone", None)


# --- update command ---------------------------------------------------------------

def test_update_command_standalone_uses_self_update():
    assert app.update_command("standalone", "/usr/local/bin/yt-dlp") == ["/usr/local/bin/yt-dlp", "-U"]


def test_update_command_pip_uses_the_scripts_own_interpreter():
    assert app.update_command("pip", "/x/bin/yt-dlp", "/x/bin/python3") == [
        "/x/bin/python3", "-m", "pip", "install", "--upgrade", "yt-dlp",
    ]


def test_update_command_pip_without_interpreter_is_manual():
    assert app.update_command("pip", "/x/bin/yt-dlp", None) is None


def test_update_command_homebrew_finds_brew(monkeypatch):
    monkeypatch.setattr(app.shutil, "which", lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None)
    assert app.update_command("homebrew", "/opt/homebrew/bin/yt-dlp") == ["/opt/homebrew/bin/brew", "upgrade", "yt-dlp"]


def test_update_command_homebrew_without_brew_is_manual(monkeypatch):
    monkeypatch.setattr(app.shutil, "which", lambda name: None)
    monkeypatch.setattr(app, "_first_executable", lambda candidates: None)
    assert app.update_command("homebrew", "/opt/homebrew/bin/yt-dlp") is None


def test_update_command_distro_package_is_manual():
    assert app.update_command("package", "/usr/bin/yt-dlp") is None


def test_every_method_has_a_manual_hint():
    for method in ("standalone", "homebrew", "pip", "package"):
        assert app.MANUAL_UPDATE_HINTS[method]


# --- Api.check_for_update ----------------------------------------------------------

def test_check_for_update_reports_update_available(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/usr/local/bin/yt-dlp")
    monkeypatch.setattr(app, "ytdlp_version", lambda path: "2026.08.19")
    monkeypatch.setattr(app, "fetch_latest_version", lambda **kw: "2026.09.10")
    monkeypatch.setattr(app, "detect_install_method", lambda path: ("standalone", None))

    result = app.Api().check_for_update()
    assert result == {
        "ok": True,
        "current": "2026.08.19",
        "latest": "2026.09.10",
        "channel": "stable",
        "channelApplies": True,
        "updateAvailable": True,
        "method": "standalone",
        "canAutoUpdate": True,
        "manualCommand": "yt-dlp -U",
    }


def test_check_for_update_uses_supplied_version_without_rerunning_ytdlp(monkeypatch):
    # `yt-dlp --version` costs several seconds on the standalone binary, and
    # the frontend already has the version from check_binary() — make sure
    # passing it in really does skip the subprocess.
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/usr/local/bin/yt-dlp")

    def must_not_run(path):
        raise AssertionError("ytdlp_version() should not be called when current is supplied")
    monkeypatch.setattr(app, "ytdlp_version", must_not_run)
    monkeypatch.setattr(app, "fetch_latest_version", lambda **kw: "2026.09.10")
    monkeypatch.setattr(app, "detect_install_method", lambda path: ("standalone", None))

    result = app.Api().check_for_update("2026.08.19")
    assert result["current"] == "2026.08.19"
    assert result["updateAvailable"] is True


def test_check_for_update_reports_up_to_date(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/usr/local/bin/yt-dlp")
    monkeypatch.setattr(app, "ytdlp_version", lambda path: "2026.08.19")
    monkeypatch.setattr(app, "fetch_latest_version", lambda **kw: "2026.08.19")
    monkeypatch.setattr(app, "detect_install_method", lambda path: ("standalone", None))

    result = app.Api().check_for_update()
    assert result["ok"] is True
    assert result["updateAvailable"] is False


def test_check_for_update_flags_manual_only_installs(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(app, "ytdlp_version", lambda path: "2026.08.19")
    monkeypatch.setattr(app, "fetch_latest_version", lambda **kw: "2026.09.10")
    monkeypatch.setattr(app, "detect_install_method", lambda path: ("package", None))

    result = app.Api().check_for_update()
    assert result["updateAvailable"] is True
    assert result["canAutoUpdate"] is False
    assert "package manager" in result["manualCommand"]


def test_check_for_update_is_quiet_when_offline(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/usr/local/bin/yt-dlp")
    monkeypatch.setattr(app, "ytdlp_version", lambda path: "2026.08.19")

    def offline(**kw):
        raise OSError("no network")
    monkeypatch.setattr(app, "fetch_latest_version", offline)

    result = app.Api().check_for_update()
    assert result["ok"] is False
    assert result["reason"] == "unavailable"


def test_check_for_update_when_ytdlp_missing(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: None)
    result = app.Api().check_for_update()
    assert result == {"ok": False, "reason": "not-found"}


# --- Api._run_update ----------------------------------------------------------------

class EmitCapture:
    def __init__(self):
        self.events = []

    def __call__(self, event, payload):
        self.events.append((event, payload))


def test_run_update_streams_output_and_reports_success(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/fake/yt-dlp")
    monkeypatch.setattr(app, "detect_install_method", lambda path: ("standalone", None))
    # stand-in for `yt-dlp -U`: prints two lines and exits 0
    monkeypatch.setattr(app, "update_command", lambda m, p, i=None, channel="stable": ["sh", "-c", "echo line one; echo line two"])
    monkeypatch.setattr(app, "ytdlp_version", lambda path: "2026.09.10")

    api = app.Api()
    api._emit = EmitCapture()
    api._run_update()

    events = api._emit.events
    assert events[0][0] == "ytdlp-log" and events[0][1]["line"].startswith("$ ")
    logged = [p["line"] for e, p in events if e == "ytdlp-log"]
    assert "line one" in logged and "line two" in logged
    assert events[-1] == ("ytdlp-update-done", {"success": True, "code": 0, "version": "2026.09.10"})


def test_run_update_reports_nonzero_exit_as_failure(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/fake/yt-dlp")
    monkeypatch.setattr(app, "detect_install_method", lambda path: ("standalone", None))
    monkeypatch.setattr(app, "update_command", lambda m, p, i=None, channel="stable": ["sh", "-c", "echo nope; exit 3"])
    monkeypatch.setattr(app, "ytdlp_version", lambda path: "2026.08.19")

    api = app.Api()
    api._emit = EmitCapture()
    api._run_update()

    done = api._emit.events[-1]
    assert done[0] == "ytdlp-update-done"
    assert done[1]["success"] is False
    assert done[1]["code"] == 3


def test_run_update_refuses_manual_only_installs(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(app, "detect_install_method", lambda path: ("package", None))

    api = app.Api()
    api._emit = EmitCapture()
    api._run_update()

    assert len(api._emit.events) == 1
    event, payload = api._emit.events[0]
    assert event == "ytdlp-update-done"
    assert payload["success"] is False
    assert "package manager" in payload["error"]


# --- update-done always fires (0g) ----------------------------------------------------

def test_update_done_fires_even_if_reading_output_blows_up(monkeypatch, tmp_path):
    exe = tmp_path / "yt-dlp"; exe.write_text("#!/bin/sh\necho updating\n"); exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    monkeypatch.setattr(app, "detect_install_method", lambda p: ("standalone", None))
    events = []
    api = app.Api()
    api.window = None
    api._emit = lambda ev, payload: (_ for _ in ()).throw(RuntimeError("boom")) if ev == "ytdlp-log" and payload["line"] == "updating" else events.append((ev, payload))
    api._run_update()
    done = [p for e, p in events if e == "ytdlp-update-done"]
    assert len(done) == 1 and done[0]["success"] is False and "boom" in done[0]["error"]


# --- update channels (#30) -------------------------------------------------------

def test_standalone_switches_channel_with_update_to():
    assert app.update_command("standalone", "/usr/local/bin/yt-dlp", channel="stable") == ["/usr/local/bin/yt-dlp", "-U"]
    assert app.update_command("standalone", "/usr/local/bin/yt-dlp", channel="nightly") == [
        "/usr/local/bin/yt-dlp", "--update-to", "nightly@latest"]
    assert app.update_command("standalone", "/usr/local/bin/yt-dlp", channel="master") == [
        "/usr/local/bin/yt-dlp", "--update-to", "master@latest"]


def test_packaged_installs_ignore_the_channel(monkeypatch):
    monkeypatch.setattr(app.shutil, "which", lambda n: "/opt/homebrew/bin/brew" if n == "brew" else None)
    assert app.update_command("homebrew", "/opt/homebrew/bin/yt-dlp", channel="nightly") == [
        "/opt/homebrew/bin/brew", "upgrade", "yt-dlp"]
    assert app.update_command("pip", "/x/bin/yt-dlp", "/x/bin/python3", channel="nightly") == [
        "/x/bin/python3", "-m", "pip", "install", "--upgrade", "yt-dlp"]


@pytest.mark.parametrize("settings,expected", [
    (None, "stable"), ({}, "stable"), ({"debug": {}}, "stable"),
    ({"debug": {"updateChannel": "nightly"}}, "nightly"),
    ({"debug": {"updateChannel": "master"}}, "master"),
    ({"debug": {"updateChannel": "nonsense"}}, "stable"),
])
def test_update_channel_from_settings(settings, expected):
    assert app.update_channel(settings) == expected


def test_each_channel_has_its_own_release_feed(monkeypatch):
    seen = []
    monkeypatch.setattr(app, "fetch_latest_version", lambda timeout=5, channel="stable": seen.append(channel) or "2026.09.10")
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/usr/local/bin/yt-dlp")
    monkeypatch.setattr(app, "detect_install_method", lambda p: ("standalone", None))
    api = app.Api()
    result = api.check_for_update("2026.08.19", {"debug": {"updateChannel": "nightly"}})
    assert seen == ["nightly"] and result["channel"] == "nightly" and result["channelApplies"] is True
    assert app.RELEASE_APIS["nightly"].endswith("yt-dlp-nightly-builds/releases/latest")


def test_channel_does_not_apply_to_a_packaged_install(monkeypatch):
    monkeypatch.setattr(app, "fetch_latest_version", lambda timeout=5, channel="stable": "2026.09.10")
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/opt/homebrew/bin/yt-dlp")
    monkeypatch.setattr(app, "detect_install_method", lambda p: ("homebrew", None))
    result = app.Api().check_for_update("2026.08.19", {"debug": {"updateChannel": "nightly"}})
    assert result["channelApplies"] is False


def test_update_runs_the_channel_the_settings_ask_for(monkeypatch):
    seen = []
    monkeypatch.setattr(app, "find_ytdlp", lambda: "/usr/local/bin/yt-dlp")
    monkeypatch.setattr(app, "detect_install_method", lambda p: ("standalone", None))
    monkeypatch.setattr(app, "update_command",
                        lambda m, p, i=None, channel="stable": seen.append(channel) or ["sh", "-c", "true"])
    api = app.Api()
    api.window = None
    api._emit = lambda ev, payload: None
    api._run_update(app.update_channel({"debug": {"updateChannel": "master"}}))
    assert seen == ["master"]
