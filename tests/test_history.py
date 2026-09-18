"""Tests for download history: the entry built from a finished job, the
final-path capture from yt-dlp's --print marker, the on-disk file (cap,
remove, clear), the Api hook that records done/failed but never cancelled,
and the reveal command per OS."""
import datetime
import json
import os
import threading
import time

import pytest

import app


def finished_job(**kw):
    job = {"id": 7, "url": "https://v", "title": "Me at the zoo", "dest": "/dl", "files": ["/dl/Me at the zoo.mp4"],
           "status": "done", "code": 0, "settings": {"preset": "720p", "auth": {"password": "hunter2", "username": "u"}}}
    job.update(kw)
    return job


# --- history_entry ----------------------------------------------------------------

def test_entry_carries_everything_download_again_needs_minus_the_password():
    now = datetime.datetime(2026, 9, 18, 14, 30, 5, tzinfo=datetime.timezone.utc)
    e = app.history_entry(finished_job(), now=now)
    assert e["id"] == f"{int(now.timestamp() * 1000)}-7"
    assert e["url"] == "https://v" and e["title"] == "Me at the zoo" and e["dest"] == "/dl"
    assert e["files"] == ["/dl/Me at the zoo.mp4"]
    assert e["status"] == "done" and e["code"] == 0
    assert e["quality"] == "720p"
    assert e["settings"]["auth"] == {"password": "", "username": "u"}
    assert datetime.datetime.fromisoformat(e["when"]) == now


@pytest.mark.parametrize("settings,label", [
    ({"preset": "best"}, "best"),
    ({"preset": "custom", "format": {"customFormat": "137+bestaudio/best"}}, "137+bestaudio/best"),
    ({"preset": "custom"}, "custom"),
    ({"preset": "audio", "audio": {"extractAudio": True, "audioFormat": "mp3"}}, "audio (mp3)"),
    ({"preset": "audio", "audio": {"extractAudio": False, "audioFormat": "mp3"}}, "audio"),
    ({}, "best"),
])
def test_quality_label(settings, label):
    assert app.quality_label(settings) == label


# --- --print marker ------------------------------------------------------------------

def test_final_paths_come_from_the_print_marker_and_stay_out_of_the_log(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"
    exe.write_text("#!/bin/sh\necho '[download] Destination: /dl/x.f137.mp4'\n"
                   f"printf '%s/dl/x.mp4\\n' \"$(printf '{app.FILE_MARKER}')\"\n"
                   "echo '[Merger] done'\n")
    exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    logs = []
    job = {"id": 1, "url": "https://v", "dest": str(tmp_path / "out"), "settings": {}, "title": None, "pct": 0,
           "files": [], "proc": None, "cancel": False}
    code = app.run_download_job(job, lambda ev, p: logs.append((ev, p)))
    assert code == 0
    assert job["files"] == ["/dl/x.mp4"]
    lines = [p["line"] for ev, p in logs if ev == "ytdlp-log"]
    assert not any(app.FILE_MARKER in l for l in lines)
    assert lines[0].startswith("$ ") and "--print" not in lines[0]   # plumbing stays out of the shown command
    assert "[Merger] done" in lines and "[download] Destination: /dl/x.f137.mp4" in lines


def test_print_args_keep_progress_output_on():
    # --print implies --quiet; --no-quiet has to come along or the UI loses its progress lines
    assert app.FILE_PRINT_ARGS[0] == "--no-quiet"
    assert app.FILE_PRINT_ARGS[1:3] == ["--print", f"after_move:{app.FILE_MARKER}%(filepath)s"]


def test_info_args_do_not_include_the_print(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    assert "--print" not in app.info_args("yt-dlp", {}, "/dl", "https://v")   # would corrupt the -J output


# --- file ---------------------------------------------------------------------------

def test_load_missing_or_garbage_history_is_empty(tmp_path):
    assert app.load_history() == []
    with open(app.history_path(), "w") as f:
        f.write("not json")
    assert app.load_history() == []
    with open(app.history_path(), "w") as f:
        json.dump({"entries": [{"id": "a"}, "junk", None]}, f)
    assert app.load_history() == [{"id": "a"}]


def test_write_keeps_only_the_newest_cap_entries(monkeypatch):
    monkeypatch.setattr(app, "HISTORY_CAP", 3)
    app.write_history([{"id": str(i)} for i in range(10)])
    assert [e["id"] for e in app.load_history()] == ["7", "8", "9"]


# --- Api hook -----------------------------------------------------------------------

def make_api(runner):
    api = app.Api()
    api.window = None
    api.notifier = lambda t, m: None
    api.queue = app.DownloadQueue(api._emit, runner)
    return api


def wait_history(n, timeout=5):
    t = time.time()
    while time.time() - t < timeout:
        if len(app.load_history()) >= n:
            return True
        time.sleep(0.02)
    return False


def test_done_and_failed_jobs_are_recorded_newest_first_but_cancelled_are_not():
    gate = threading.Event()

    def runner(job, emit):
        if job["url"].endswith("slow"):
            gate.wait(5)
        job["title"] = job["url"].rsplit("/", 1)[-1]
        job["files"].append(f"/dl/{job['title']}.mp4")
        return 1 if job["url"].endswith("bad") else 0
    api = make_api(runner)
    api.enqueue(["https://good", "https://bad", "https://slow"], {"preset": "480p"}, "/dl")
    assert wait_history(2)
    api.cancel_download(3)
    gate.set()
    time.sleep(0.2)
    entries = api.history_list()
    assert [(e["title"], e["status"], e["code"]) for e in entries] == [("bad", "failed", 1), ("good", "done", 0)]
    assert entries[1]["files"] == ["/dl/good.mp4"] and entries[1]["quality"] == "480p" and entries[1]["dest"] == "/dl"
    assert entries[0]["settings"] == {"preset": "480p"}


def test_parallel_finishes_do_not_lose_entries():
    def runner(job, emit):
        time.sleep(0.02)
        return 0
    api = make_api(runner)
    api.enqueue([f"https://{i}" for i in range(8)], {"network": {"parallel": "4"}}, "/dl")
    assert wait_history(8)
    assert len(app.load_history()) == 8


def test_history_event_fires_after_the_entry_is_on_disk():
    seen = []

    class FakeWindow:
        def evaluate_js(self, js):
            if "ytdlp-history" in js:
                seen.append(len(app.load_history()))
    api = make_api(lambda job, emit: 0)
    api.window = FakeWindow()
    api.enqueue(["https://a"], {}, "/dl")
    assert wait_history(1)
    time.sleep(0.1)
    assert seen == [1]


def test_remove_and_clear():
    api = make_api(lambda job, emit: 0)
    api.enqueue(["https://a", "https://b"], {}, "/dl")
    assert wait_history(2)
    entries = api.history_list()
    api.history_remove(entries[0]["id"])
    assert [e["url"] for e in api.history_list()] == ["https://a"]
    api.history_clear()
    assert api.history_list() == []


def test_unwritable_history_never_breaks_the_queue(monkeypatch):
    monkeypatch.setattr(app, "write_history", lambda entries: (_ for _ in ()).throw(OSError("read-only")))
    api = make_api(lambda job, emit: 0)
    api.enqueue(["https://a", "https://b"], {}, "/dl")
    t = time.time()
    while time.time() - t < 5 and api.queue.is_active():
        time.sleep(0.02)
    assert [j["status"] for j in api.queue_snapshot()] == ["done", "done"]


# --- reveal_command -----------------------------------------------------------------

def test_reveal_selects_the_file_in_finder(tmp_path, monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "darwin")
    f = tmp_path / "a.mp4"; f.write_text("x")
    assert app.reveal_command(str(f)) == ["open", "-R", str(f)]


def test_reveal_falls_back_to_the_folder_when_the_file_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "darwin")
    assert app.reveal_command(str(tmp_path / "gone.mp4")) == ["open", str(tmp_path)]
    assert app.reveal_command(str(tmp_path / "nodir" / "gone.mp4")) is None


def test_reveal_on_linux_opens_the_containing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.shutil, "which", lambda n: "/usr/bin/xdg-open" if n == "xdg-open" else None)
    f = tmp_path / "a.mp4"; f.write_text("x")
    assert app.reveal_command(str(f)) == ["/usr/bin/xdg-open", str(tmp_path)]
    assert app.reveal_command(str(tmp_path)) == ["/usr/bin/xdg-open", str(tmp_path)]
    monkeypatch.setattr(app.shutil, "which", lambda n: None)
    assert app.reveal_command(str(f)) is None
