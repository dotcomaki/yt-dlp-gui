"""Tests for error hints: the substring table, the stderr tail a job keeps,
the hint attached to a failed job, Retry, and the Clear-cache command."""
import time

import pytest

import app


# --- error_hint -------------------------------------------------------------------

@pytest.mark.parametrize("line,action,starts", [
    ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser", "cookies", "YouTube wants"),
    ("ERROR: [youtube] abc: Sign in to confirm your age", "cookies", "YouTube wants"),
    ("ERROR: [vimeo] This video requires login", "cookies", "YouTube wants"),
    ("ERROR: [youtube] abc: Requested format is not available. Use --list-formats", "formats", "That format"),
    ("yt-dlp: error: no such option: --bogus", "extra", "Unrecognised option"),
    ("ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install or provide the path", None, "ffmpeg is missing"),
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "cookies", "YouTube wants"),
    ("ERROR: [youtube] abc: Video unavailable", None, "The video isn't accessible"),
    ("ERROR: [youtube] thisisnotar: This video is unavailable", None, "The video isn't accessible"),
    ("ERROR: [youtube] abc: This video has been removed by the uploader", None, "The video isn't accessible"),
    ("ERROR: [youtube] abc: Join this channel to get access to members-only content", None, "The video isn't accessible"),
    ("ERROR: Unsupported URL: https://example.com/page", None, "yt-dlp doesn't have an extractor"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "update", "yt-dlp is probably out of date"),
    ("ERROR: [youtube] abc: Unable to extract player version", "update", "yt-dlp is probably out of date"),
    ("WARNING: [youtube] abc: nsig extraction failed: Some formats may be missing", "update", "yt-dlp is probably out of date"),
])
def test_known_failures_get_a_hint(line, action, starts):
    hint = app.error_hint(["[youtube] Extracting URL", line, "[debug] Exiting"])
    assert hint["action"] == action and hint["text"].startswith(starts)


def test_private_video_wins_over_generic_sign_in_text():
    # "Private video. Sign in if you've been granted access" — the cookies
    # advice is right (a sign-in *can* fix it), and it comes first in the table
    assert app.error_hint(["ERROR: Private video. Sign in if you've been granted access"])["action"] == "cookies"


def test_matching_is_case_insensitive_and_unknown_or_empty_is_none():
    assert app.error_hint(["ERROR: HTTP ERROR 403: FORBIDDEN"])["action"] == "update"
    assert app.error_hint(["ERROR: something entirely new"]) is None
    assert app.error_hint([]) is None
    assert app.error_hint(None) is None
    assert app.error_hint(["   "]) is None


# --- the tail a job keeps -------------------------------------------------------------

def test_run_download_job_keeps_only_the_last_lines(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"
    exe.write_text("#!/bin/sh\nfor i in $(seq 1 50); do echo line$i; done\necho 'ERROR: Video unavailable'\nexit 1\n")
    exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    job = {"id": 1, "url": "https://v", "dest": str(tmp_path / "d"), "settings": {}, "title": None, "pct": 0,
           "files": [], "tail": [], "proc": None, "cancel": False}
    assert app.run_download_job(job, lambda ev, p: None) == 1
    assert len(job["tail"]) == app.TAIL_LINES
    assert job["tail"][0] == "line22" and job["tail"][-1] == "ERROR: Video unavailable"


# --- queue: hint on failure, retry ----------------------------------------------------

class Emit:
    def __init__(self):
        self.events = []

    def __call__(self, event, payload):
        self.events.append((event, payload))


def idle(q, timeout=5):
    t = time.time()
    while time.time() - t < timeout:
        if not q.is_active():
            return True
        time.sleep(0.02)
    return False


def test_failed_job_carries_a_hint_and_successful_one_does_not():
    def runner(job, emit):
        if job["url"].endswith("bad"):
            job["tail"].append("ERROR: [youtube] x: Requested format is not available")
            return 1
        job["tail"].append("[download] 100%")
        return 0
    q = app.DownloadQueue(Emit(), runner)
    q.enqueue(["https://good", "https://bad"], {}, "/dl")
    assert idle(q)
    snap = {j["url"]: j for j in q.snapshot()}
    assert snap["https://good"]["hint"] is None
    assert snap["https://bad"]["hint"] == {"text": "That format doesn't exist for this video — pick one from the format list", "action": "formats"}


def test_retry_makes_a_fresh_job_with_the_same_settings_and_keeps_the_old_row():
    q = app.DownloadQueue(Emit(), lambda job, emit: 1)
    q.enqueue([{"url": "https://a", "title": "A"}], {"preset": "480p"}, "/dl")
    assert idle(q)
    new_id = q.retry(1)
    assert new_id == 2
    assert idle(q)
    jobs = q.snapshot()
    assert [(j["id"], j["status"], j["url"], j["title"]) for j in jobs] == [(1, "failed", "https://a", "A"), (2, "failed", "https://a", "A")]
    assert q._jobs[1]["settings"] == {"preset": "480p"} and q._jobs[1]["dest"] == "/dl"


def test_retry_refuses_active_or_unknown_jobs():
    import threading
    gate = threading.Event()
    q = app.DownloadQueue(Emit(), lambda job, emit: gate.wait(5) and 0)
    q.enqueue(["https://a"], {}, "/dl")
    time.sleep(0.05)
    assert q.retry(1) is None      # running
    assert q.retry(99) is None     # unknown
    gate.set()
    assert idle(q)
    assert q.retry(1) == 2         # done: allowed too ("download again")


def test_api_retry_uses_the_snapshot_parallelism():
    api = app.Api()
    api.window = None
    api.notifier = lambda t, m: None
    api.queue = app.DownloadQueue(api._emit, lambda job, emit: 1)
    api.enqueue(["https://a"], {"network": {"parallel": "3"}}, "/dl")
    assert idle(api.queue)
    assert api.retry_download(1) == 2


# --- clear cache ------------------------------------------------------------------------

def test_clear_cache_runs_rm_cache_dir_and_logs(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"
    exe.write_text("#!/bin/sh\necho \"args: $@\"\necho 'Removing cache dir /x/yt-dlp'\n")
    exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    logs = []
    api = app.Api()
    api.window = None
    api._emit = lambda ev, p: logs.append((ev, p))
    assert api.clear_ytdlp_cache() == {"ok": True}
    lines = [p["line"] for ev, p in logs if ev == "ytdlp-log"]
    assert lines[0].endswith("--rm-cache-dir") and "Removing cache dir /x/yt-dlp" in lines and lines[-1] == "yt-dlp cache cleared."


def test_clear_cache_reports_failure(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"; exe.write_text("#!/bin/sh\nexit 3\n"); exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    api = app.Api(); api.window = None; api._emit = lambda ev, p: None
    assert api.clear_ytdlp_cache() == {"ok": False, "error": "yt-dlp exited with code 3"}
    monkeypatch.setattr(app, "find_ytdlp", lambda: None)
    assert api.clear_ytdlp_cache() == {"ok": False, "error": "yt-dlp not found"}
