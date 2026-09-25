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


def test_socket_path_prefers_runtime_dir_then_config(sock_path, monkeypatch):
    # Short directories, since the point here is the preference order and
    # pytest's own tmp_path is long enough to trip the length fallback.
    short = os.path.dirname(sock_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", short)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert app.instance_socket_path() == os.path.join(short, "ytdlp-gui", "app.sock")
    monkeypatch.setenv("XDG_RUNTIME_DIR", short)
    assert app.instance_socket_path() == os.path.join(short, "ytdlp-gui.sock")
    monkeypatch.setenv("XDG_RUNTIME_DIR", os.path.join(short, "missing"))   # set but absent: ignored
    assert app.instance_socket_path().endswith(os.path.join("ytdlp-gui", "app.sock"))


def test_round_trip_delivers_urls_and_acks(sock_path):
    got = []
    server = app.InstanceServer(lambda urls, options: got.append(urls), sock_path)
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
    server = app.InstanceServer(lambda urls, options: got.append(urls), path)
    server.start()
    try:
        assert app.send_to_running_instance(["https://a"], path) is True
        assert got == [["https://a"]]
    finally:
        server.close()


def test_second_server_detects_the_live_one(sock_path):
    path = sock_path
    first = app.InstanceServer(lambda urls, options: None, path)
    first.start()
    try:
        with pytest.raises(app.AlreadyRunning):
            app.InstanceServer(lambda urls, options: None, path).start()
        assert app.send_to_running_instance(["still"], path) is True   # the probe didn't break the first
    finally:
        first.close()


def test_garbage_and_non_string_entries_are_tolerated(sock_path):
    got = []
    path = sock_path
    server = app.InstanceServer(lambda urls, options: got.append(urls), path)
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

    def handler(urls, options):
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


def test_the_handler_receives_the_popup_options(sock_path):
    seen = []
    server = app.InstanceServer(lambda urls, options: seen.append((urls, options)), sock_path)
    server.start()
    try:
        assert app.send_to_running_instance(["https://a"], sock_path,
                                            options={"profile": "Podcast", "enqueue": True}) is True
        assert app.send_to_running_instance(["https://b"], sock_path) is True
    finally:
        server.close()
    assert seen == [
        (["https://a"], {"profile": "Podcast", "enqueue": True}),
        (["https://b"], {"profile": "", "enqueue": False}),   # a plain hand-off, as before
    ]


@pytest.mark.parametrize("argv,url,options", [
    ([], "", {"profile": "", "enqueue": False}),
    (["https://v"], "https://v", {"profile": "", "enqueue": False}),
    (["https://v", "--enqueue"], "https://v", {"profile": "", "enqueue": True}),
    (["--profile", "Podcast", "https://v"], "https://v", {"profile": "Podcast", "enqueue": False}),
    (["--profile=Archive", "--enqueue", "https://v"], "https://v", {"profile": "Archive", "enqueue": True}),
])
def test_parse_argv(argv, url, options):
    assert app.parse_argv(argv) == (url, options)


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
    assert api.window.js == ['receiveUrls(["https://a", "https://b"], {})']
    assert api.window.calls == ["restore", "show"]
    api.window.js.clear()
    api.add_urls([])   # nothing to add: only comes forward
    assert api.window.js == [] and api.window.calls == ["restore", "show", "restore", "show"]
    api.window = None
    api.add_urls(["https://c"])   # before the window exists: no crash


def test_download_now_does_not_steal_focus():
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
    api.add_urls(["https://a"], {"profile": "Podcast", "enqueue": True})
    assert api.window.js == ['receiveUrls(["https://a"], {"profile": "Podcast", "enqueue": true})']
    assert api.window.calls == []          # the point of "download now" is to stay out of the way
    api.add_urls(["https://b"], {"profile": "", "enqueue": False})
    assert api.window.calls == ["restore", "show"]


def test_socket_path_falls_back_when_the_config_dir_is_too_deep(tmp_path, monkeypatch):
    deep = tmp_path / ("nested" * 30)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(deep))
    path = app.instance_socket_path()
    assert len(path) <= app.MAX_SOCKET_PATH
    assert path.endswith(f"ytdlp-gui-{os.getuid()}.sock")
    # and it still works as a socket, which is the whole point
    server = app.InstanceServer(lambda urls, options: None, path)
    server.start()
    try:
        assert app.send_to_running_instance([], path) is True
    finally:
        server.close()


def test_a_runtime_dir_that_is_too_long_is_skipped_too(sock_path, monkeypatch):
    short = os.path.dirname(sock_path)
    os.makedirs(os.path.join(short, "x" * 120), exist_ok=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", os.path.join(short, "x" * 120))
    monkeypatch.setenv("XDG_CONFIG_HOME", short)
    assert app.instance_socket_path() == os.path.join(short, "ytdlp-gui", "app.sock")


# --- the URL a cold start is handed (#37) ---------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc&list=PL1&index=2",   # & would split the query
    "https://example.com/a b c.mp4",                          # spaces
    "https://example.com/p?q=a#frag",                         # # would truncate it
    "https://example.com/Ünïcødé/видео",
    "https://example.com/100%25",
])
def test_the_entry_url_round_trips_through_the_query_string(url):
    import urllib.parse
    entry = "ui/index.html?url=" + urllib.parse.quote(url, safe="")
    query = urllib.parse.urlparse(entry).query
    assert urllib.parse.parse_qs(query)["url"] == [url]
