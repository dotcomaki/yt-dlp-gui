"""Tests for native-host/native_host.py: message framing and the
deliver() decision — hand the URL to a running app over its socket, or
launch one. Loaded by path; it isn't a package."""
import importlib.util
import io
import json
import os
import struct

import pytest

import app

HOST = os.path.join(os.path.dirname(__file__), "..", "native-host", "native_host.py")


@pytest.fixture
def host():
    spec = importlib.util.spec_from_file_location("native_host", HOST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_socket_path_agrees_with_the_app(host, tmp_path, monkeypatch):
    assert host.instance_socket_path() == app.instance_socket_path()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert host.instance_socket_path() == app.instance_socket_path()


def test_message_framing_round_trips(host, monkeypatch):
    payload = json.dumps({"url": "https://v"}).encode()
    monkeypatch.setattr(host.sys, "stdin", io.TextIOWrapper(io.BytesIO(struct.pack("=I", len(payload)) + payload)))
    assert host.read_message() == {"url": "https://v"}
    out = io.BytesIO()
    monkeypatch.setattr(host.sys, "stdout", io.TextIOWrapper(out))
    host.send_message({"ok": True})
    raw = out.getvalue()
    assert struct.unpack("=I", raw[:4])[0] == len(raw) - 4 and json.loads(raw[4:]) == {"ok": True}


def test_deliver_hands_off_to_a_running_app(host, sock_path, monkeypatch):
    path = sock_path
    monkeypatch.setattr(host, "instance_socket_path", lambda: path)
    monkeypatch.setattr(host, "launch", lambda url: (_ for _ in ()).throw(AssertionError("must not launch")))
    got = []
    server = app.InstanceServer(lambda urls, options: got.append(urls), path)
    server.start()
    try:
        assert host.deliver("https://v") == "running"
        assert got == [["https://v"]]
    finally:
        server.close()


def test_deliver_launches_when_nothing_listens(host, tmp_path, monkeypatch):
    monkeypatch.setattr(host, "instance_socket_path", lambda: os.path.join(str(tmp_path), "none"))
    launched = []
    monkeypatch.setattr(host, "launch", lambda url, profile="", enqueue=False: launched.append((url, profile, enqueue)))
    assert host.deliver("https://v") == "launched"
    assert host.deliver("https://w", "Podcast", True) == "launched"
    assert launched == [("https://v", "", False), ("https://w", "Podcast", True)]


def test_launch_passes_the_popup_choices_on_the_command_line(host, monkeypatch):
    spawned = []
    monkeypatch.setattr(host.platform, "system", lambda: "Linux")
    monkeypatch.setattr(host, "find_python", lambda: "/usr/bin/python3")
    monkeypatch.setattr(host.subprocess, "Popen", lambda args, **kw: spawned.append(args))
    host.launch("https://v", "Podcast", True)
    assert spawned[0][2:] == ["https://v", "--profile", "Podcast", "--enqueue"]
    host.launch("https://v")
    assert spawned[1][2:] == ["https://v"]


def test_profiles_action_reads_the_saved_names(host, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert host.handle({"action": "profiles"}) == {"ok": True, "profiles": []}
    (tmp_path / "ytdlp-gui").mkdir()
    (tmp_path / "ytdlp-gui" / "profiles.json").write_text(
        '{"profiles": {"podcast": {"settings": {}}, "Archive": {"settings": {}}}}')
    assert host.handle({"action": "profiles"}) == {"ok": True, "profiles": ["Archive", "podcast"]}
    (tmp_path / "ytdlp-gui" / "profiles.json").write_text("{")
    assert host.handle({"action": "profiles"}) == {"ok": True, "profiles": []}


def test_handle_forwards_the_popup_choices(host, monkeypatch):
    seen = []
    monkeypatch.setattr(host, "deliver", lambda url, profile="", enqueue=False: seen.append((url, profile, enqueue)) or "running")
    assert host.handle({"url": "https://v", "profile": "Podcast", "enqueue": True}) == {"ok": True, "delivered": "running"}
    assert seen == [("https://v", "Podcast", True)]
    assert host.handle({})["ok"] is False


def test_socket_path_fallback_matches_the_app_too(host, tmp_path, monkeypatch):
    # If the two disagreed about the fallback, every hand-off would quietly
    # launch a second app instead of talking to the running one.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ("nested" * 30)))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert host.instance_socket_path() == app.instance_socket_path()
    assert len(host.instance_socket_path()) <= host.MAX_SOCKET_PATH
