"""Tests for the single-instance hand-off: a running app listens on a Unix
socket, later launches send their URL there and exit. Covers the round
trip, stale socket files, the already-running case, and Api.add_urls."""
import json
import os
import socket
import threading
import time

import pytest

import app


def wait_until(pred, timeout=5):
    t = time.time()
    while time.time() - t < timeout:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_socket_path_prefers_runtime_dir_then_config(tmp_path, monkeypatch):
    assert app.instance_socket_path() == os.path.join(app.config_path(""), "app.sock")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert app.instance_socket_path() == os.path.join(str(tmp_path), "ytdlp-gui.sock")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "missing"))   # set but absent: ignored
    assert app.instance_socket_path().endswith("app.sock")


def test_round_trip_delivers_urls_and_acks(sock_path):
    got = []
    server = app.InstanceServer(got.append, sock_path)
    server.start()
    try:
        assert app.send_to_running_instance(["https://a", "https://b"], sock_path) is True
        assert got == [["https://a", "https://b"]]
        assert app.send_to_running_instance([], sock_path) is True   # "just bring the window forward"
        assert got == [["https://a", "https://b"], []]
    finally:
        server.close()
    assert not os.path.exists(sock_path)


def test_send_without_a_server_is_false(sock_path):
    assert app.send_to_running_instance(["https://a"], sock_path) is False


def test_stale_socket_file_is_replaced(sock_path):
    path = sock_path
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(path)
    dead.close()   # file stays behind, nobody listens — what a crash leaves
    assert app.send_to_running_instance(["x"], path) is False
    got = []
    server = app.InstanceServer(got.append, path)
    server.start()
    try:
        assert app.send_to_running_instance(["https://a"], path) is True
        assert got == [["https://a"]]
    finally:
        server.close()


def test_second_server_detects_the_live_one(sock_path):
    path = sock_path
    first = app.InstanceServer(lambda urls: None, path)
    first.start()
    try:
        with pytest.raises(app.AlreadyRunning):
            app.InstanceServer(lambda urls: None, path).start()
        assert app.send_to_running_instance(["still"], path) is True   # the probe didn't break the first
    finally:
        first.close()


def test_garbage_and_non_string_entries_are_tolerated(sock_path):
    got = []
    path = sock_path
    server = app.InstanceServer(got.append, path)
    server.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(path)
            s.sendall(b"not json\n")
            reply = json.loads(s.makefile("r").readline())
        assert reply["ok"] is False
        assert app.send_to_running_instance(["https://a", 5, "", None], path) is True
        assert got == [["https://a"]]
    finally:
        server.close()


def test_handler_failure_is_reported_and_the_server_survives(sock_path):
    path = sock_path
    calls = []

    def handler(urls):
        calls.append(urls)
        if urls == ["boom"]:
            raise RuntimeError("boom")
    server = app.InstanceServer(handler, path)
    server.start()
    try:
        assert app.send_to_running_instance(["boom"], path) is False
        assert app.send_to_running_instance(["fine"], path) is True
        assert calls == [["boom"], ["fine"]]
    finally:
        server.close()


def test_add_urls_evaluates_js_and_brings_the_window_forward():
    class FakeWindow:
        def __init__(self):
            self.js, self.calls = [], []
        def evaluate_js(self, js):
            self.js.append(js)
        def restore(self):
            self.calls.append("restore")
        def show(self):
            self.calls.append("show")
    api = app.Api()
    api.window = FakeWindow()
    api.add_urls(["https://a", "https://b"])
    assert api.window.js == ['receiveUrls(["https://a", "https://b"])']
    assert api.window.calls == ["restore", "show"]
    api.window.js.clear()
    api.add_urls([])   # nothing to add: only comes forward
    assert api.window.js == [] and api.window.calls == ["restore", "show", "restore", "show"]
    api.window = None
    api.add_urls(["https://c"])   # before the window exists: no crash
