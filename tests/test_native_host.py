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
    server = app.InstanceServer(got.append, path)
    server.start()
    try:
        assert host.deliver("https://v") == "running"
        assert got == [["https://v"]]
    finally:
        server.close()


def test_deliver_launches_when_nothing_listens(host, tmp_path, monkeypatch):
    monkeypatch.setattr(host, "instance_socket_path", lambda: os.path.join(str(tmp_path), "none"))
    launched = []
    monkeypatch.setattr(host, "launch", launched.append)
    assert host.deliver("https://v") == "launched"
    assert launched == ["https://v"]
