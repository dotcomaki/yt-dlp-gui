"""Tests for reading yt-dlp's --newline progress lines, including the two
shapes the old pattern missed entirely, and for live-stream metadata."""
import pytest

import app


# Real lines captured from yt-dlp 2026.08.19.
FRAGMENTED = "[download]  71.4% of ~  21.00KiB at    1.19KiB/s ETA Unknown (frag 0/3)"
UNKNOWN_TOTAL = "[download]   31.00KiB at   15.19MiB/s (00:00:00)"
UNKNOWN_SPEED = "[download]    1.00KiB at  Unknown B/s (00:00:00)"
FINISHED = "[download] 100% of  113.71KiB in 00:00:00 at 143.44KiB/s"
PLAIN = "[download]  45.2% of    5.00MiB at    1.00MiB/s ETA 00:03"


def test_plain_progress():
    assert app.parse_progress(PLAIN) == {
        "pct": 45.2, "size": "5.00MiB", "speed": "1.00MiB/s", "eta": "00:03", "elapsed": ""}


def test_estimated_total_with_padding_after_the_tilde():
    # The old pattern required a digit straight after "~", so every
    # fragmented/HLS download showed no progress at all.
    p = app.parse_progress(FRAGMENTED)
    assert p["pct"] == 71.4 and p["size"] == "21.00KiB" and p["speed"] == "1.19KiB/s"
    assert p["eta"] == ""          # "Unknown" is not worth showing


def test_unknown_total_has_no_percentage():
    assert app.parse_progress(UNKNOWN_TOTAL) == {
        "pct": None, "size": "31.00KiB", "speed": "15.19MiB/s", "eta": "", "elapsed": "00:00:00"}


def test_unknown_speed_is_blank_not_the_word():
    assert app.parse_progress(UNKNOWN_SPEED)["speed"] == ""


def test_finished_line_with_elapsed_before_the_rate():
    p = app.parse_progress(FINISHED)
    assert p["pct"] == 100.0 and p["size"] == "113.71KiB"
    assert p["speed"] == "143.44KiB/s" and p["elapsed"] == "00:00:00"


@pytest.mark.parametrize("line", [
    "[download] Destination: /dl/x.mp4",
    "[youtube] abc: Downloading webpage",
    "",
    "[download] 100% of  113.71KiB",   # no rate: still fine, but not a size-only line
])
def test_non_progress_lines(line):
    result = app.parse_progress(line)
    assert result is None or result["pct"] is not None


def test_a_job_keeps_its_last_known_percentage_when_the_total_goes_unknown(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"
    exe.write_text("#!/bin/sh\n"
                   f"echo '{PLAIN}'\n"
                   f"echo '{UNKNOWN_TOTAL}'\n")
    exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    events = []
    job = {"id": 1, "url": "https://v", "dest": str(tmp_path / "d"), "settings": {}, "title": None, "pct": 0,
           "files": [], "archive": [], "tail": [], "proc": None, "cancel": False}
    app.run_download_job(job, lambda ev, p: events.append((ev, p)) if ev == "ytdlp-progress" else None)
    assert [p["pct"] for _, p in events] == [45.2, None]
    assert job["pct"] == 45.2


# --- live streams ---------------------------------------------------------------------

@pytest.mark.parametrize("data,state,label", [
    ({"live_status": "is_live"}, "is_live", "live"),
    ({"live_status": "is_upcoming"}, "is_upcoming", "upcoming"),
    ({"live_status": "post_live"}, "post_live", "just ended"),
    ({"live_status": "was_live"}, "was_live", "was live"),
    ({"is_live": True}, "is_live", "live"),                 # older/other extractors
])
def test_live_state(data, state, label):
    info = app.summarize_info(dict(data, title="t"))
    assert info["live"] == {"state": state, "label": label, "startsAt": None}


def test_ordinary_video_has_no_live_block():
    assert app.summarize_info({"title": "t", "live_status": "not_live"})["live"] is None
    assert app.summarize_info({"title": "t"})["live"] is None


def test_upcoming_carries_its_scheduled_time():
    info = app.summarize_info({"title": "t", "live_status": "is_upcoming", "release_timestamp": 1790384728})
    assert info["live"]["startsAt"] == 1790384728


def test_live_options(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)
    args = app.build_args("yt-dlp", {"live": {"fromStart": True, "waitForVideo": " 30-120 "}}, "/dl")
    assert "--live-from-start" in args
    assert args[args.index("--wait-for-video") + 1] == "30-120"
    assert "--live-from-start" not in app.build_args("yt-dlp", {}, "/dl")
