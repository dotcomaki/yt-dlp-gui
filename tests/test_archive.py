"""Tests for "skip videos already downloaded": the archive line captured
per finished video, the archive file derived from history, the
--download-archive argv, and the preview flagging what's already there."""
import os
import time

import app


def flag(args, name):
    return args[args.index(name) + 1]


# --- capture -----------------------------------------------------------------------

def test_run_download_job_captures_archive_lines(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"
    exe.write_text("#!/bin/sh\n"
                   f"printf '%s/dl/a.mp4\\n' \"$(printf '{app.FILE_MARKER}')\"\n"
                   f"printf '%sYoutube jNQXAC9IVRw\\n' \"$(printf '{app.ARCHIVE_MARKER}')\"\n"
                   f"printf '%sNA NA\\n' \"$(printf '{app.ARCHIVE_MARKER}')\"\n")
    exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    logs = []
    job = {"id": 1, "url": "https://v", "dest": str(tmp_path / "d"), "settings": {}, "title": None, "pct": 0,
           "files": [], "archive": [], "tail": [], "proc": None, "cancel": False}
    assert app.run_download_job(job, lambda ev, p: logs.append(p.get("line", ""))) == 0
    assert job["archive"] == ["youtube jNQXAC9IVRw"]           # lower-cased, NA dropped
    assert not any(app.ARCHIVE_MARKER in l for l in logs)


def test_history_entry_carries_the_archive_lines():
    job = {"id": 1, "url": "https://v", "title": "t", "dest": "/dl", "files": [], "status": "done", "code": 0,
           "settings": {}, "archive": ["youtube a", "youtube b"]}
    assert app.history_entry(job)["archive"] == ["youtube a", "youtube b"]


# --- derived archive file ------------------------------------------------------------

def test_archive_ids_only_from_successful_entries_deduped():
    entries = [
        {"status": "done", "archive": ["youtube a", "youtube b"]},
        {"status": "failed", "archive": ["youtube c"]},
        {"status": "done", "archive": ["youtube b", "vimeo 1"]},
        {"status": "done"},                                   # older entry without the key
    ]
    assert app.archive_ids(entries) == ["youtube a", "youtube b", "vimeo 1"]


def test_write_archive_produces_yt_dlp_format():
    app.write_archive([{"status": "done", "archive": ["youtube a"]}, {"status": "done", "archive": ["vimeo 1"]}])
    assert open(app.archive_path()).read() == "youtube a\nvimeo 1\n"


# --- build_args -------------------------------------------------------------------------

def test_skip_downloaded_passes_the_archive(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    args = app.build_args("yt-dlp", {"playlist": {"skipDownloaded": True}}, "/dl")
    assert flag(args, "--download-archive") == app.archive_path()
    assert "--break-on-existing" not in args
    args = app.build_args("yt-dlp", {"playlist": {"skipDownloaded": True, "breakOnExisting": True}}, "/dl")
    assert "--break-on-existing" in args
    args = app.build_args("yt-dlp", {"playlist": {"breakOnExisting": True}}, "/dl")   # meaningless without the archive
    assert "--download-archive" not in args and "--break-on-existing" not in args


def test_preview_never_sends_the_archive(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    args = app.info_args("yt-dlp", {"playlist": {"skipDownloaded": True, "items": "1:3"}}, "/dl", "https://v")
    assert "--download-archive" not in args and flag(args, "--playlist-items") == "1:3"


# --- preview flags -------------------------------------------------------------------------

def test_summarize_marks_downloaded_entries_and_videos():
    downloaded = frozenset({"youtube b"})
    info = app.summarize_info({"_type": "playlist", "entries": [
        {"ie_key": "Youtube", "id": "a", "url": "https://v/a"},
        {"ie_key": "Youtube", "id": "b", "url": "https://v/b"},
        {"url": "https://v/c"},
    ]}, downloaded)
    assert [e["downloaded"] for e in info["entries"]] == [False, True, False]
    assert app.summarize_info({"extractor_key": "Youtube", "id": "b"}, downloaded)["downloaded"] is True
    assert app.summarize_info({"extractor_key": "Youtube", "id": "z"}, downloaded)["downloaded"] is False


def test_archive_line_matches_yt_dlp_format():
    assert app.archive_line({"extractor_key": "Youtube", "id": "x"}) == "youtube x"
    assert app.archive_line({"ie_key": "Vimeo", "id": "1"}) == "vimeo 1"
    assert app.archive_line({"id": "x"}) is None and app.archive_line({}) is None


# --- Api ---------------------------------------------------------------------------------------

def idle(q, timeout=10):
    """wait_idle, not is_active: a job's persist/history/archive writes run
    on its worker thread after the status flips, so "nothing is running"
    comes a moment before "everything is written"."""
    return q.wait_idle(timeout)


def make_api(runner):
    api = app.Api()
    api.window = None
    api.notifier = lambda t, m: None
    api.queue = app.DownloadQueue(api._emit, runner)
    return api


def test_enqueue_regenerates_the_archive_only_when_the_setting_is_on():
    def runner(job, emit):
        job["archive"].append("youtube " + job["url"][-1])
        return 0
    api = make_api(runner)
    api.enqueue(["https://a"], {}, "/dl")
    assert idle(api.queue)
    assert not os.path.exists(app.archive_path())
    api.enqueue(["https://b"], {"playlist": {"skipDownloaded": True}}, "/dl")
    assert open(app.archive_path()).read() == "youtube a\n"      # from history, before b ran
    assert idle(api.queue)
    api.enqueue(["https://c"], {"playlist": {"skipDownloaded": True}}, "/dl")
    assert open(app.archive_path()).read() == "youtube a\nyoutube b\n"


def test_removing_or_clearing_history_shrinks_the_archive():
    def runner(job, emit):
        job["archive"].append("youtube " + job["url"][-1])
        return 0
    api = make_api(runner)
    api.enqueue(["https://a", "https://b"], {"playlist": {"skipDownloaded": True}}, "/dl")
    assert idle(api.queue)
    api._sync_archive()
    assert open(app.archive_path()).read() == "youtube a\nyoutube b\n"
    newest = api.history_list()[0]
    api.history_remove(newest["id"])
    assert open(app.archive_path()).read() == "youtube a\n"
    api.history_clear()
    assert open(app.archive_path()).read() == ""


def test_fetch_info_flags_what_history_already_has(tmp_path, monkeypatch):
    import json
    data = {"_type": "video", "extractor_key": "Youtube", "id": "abc", "title": "T"}
    exe = tmp_path / "yt-dlp"; exe.write_text(f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(data)}\nEOF\n"); exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    api = make_api(lambda job, emit: 0)
    assert api.fetch_info("https://v", {}, "/dl")["downloaded"] is False
    app.write_history([app.history_entry({"id": 1, "url": "https://v", "title": "T", "dest": "/dl", "files": [],
                                          "status": "done", "code": 0, "settings": {}, "archive": ["youtube abc"]})])
    assert api.fetch_info("https://v", {}, "/dl")["downloaded"] is True


def test_archive_skips_are_marked_and_not_recorded_in_history():
    def runner(job, emit):
        if job["url"].endswith("skip"):
            job["tail"].append("[download] abc: has already been recorded in the archive")
            return 0
        job["files"].append("/dl/x.mp4")
        job["archive"].append("youtube x")
        return 0
    api = make_api(runner)
    api.enqueue(["https://real", "https://skip"], {"playlist": {"skipDownloaded": True}}, "/dl")
    assert idle(api.queue)
    snap = {j["url"]: j for j in api.queue_snapshot()}
    assert snap["https://real"]["hint"] is None
    assert snap["https://skip"]["status"] == "done" and snap["https://skip"]["hint"]["text"].startswith("Already in History")
    assert [e["url"] for e in api.history_list()] == ["https://real"]
