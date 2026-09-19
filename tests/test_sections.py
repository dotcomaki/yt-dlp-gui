"""Tests for clips and chapters: the --download-sections argv, the output
template suffix that keeps sections from overwriting each other, chapters
in the preview, and the section riding along on queue jobs and history."""
import pytest

import app


def flag(args, name):
    return args[args.index(name) + 1]


@pytest.fixture(autouse=True)
def no_tools(monkeypatch):
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)


# --- helpers ----------------------------------------------------------------------

@pytest.mark.parametrize("sec,text", [(0, "0s"), (45, "45s"), (90, "1m30s"), (3723, "1h02m03s"), (59.6, "1m00s")])
def test_format_seconds(sec, text):
    assert app.format_seconds(sec) == text


def test_section_label_prefers_the_chapter_title():
    assert app.section_label({"start": 5, "end": 17, "title": "The cool thing"}) == "The cool thing"
    assert app.section_label({"start": 90, "end": 120}) == "1m30s-2m00s"
    assert app.section_label({"start": 0, "end": None}) == "0s-end"


def test_template_suffix_goes_before_the_extension_and_is_made_safe():
    assert app.template_with_suffix("%(title)s.%(ext)s", "Intro") == "%(title)s - Intro.%(ext)s"
    assert app.template_with_suffix("%(title)s [%(id)s].%(ext)s", "a/b\\c") == "%(title)s [%(id)s] - a b c.%(ext)s"
    assert app.template_with_suffix("%(title)s.%(ext)s", "100% done") == "%(title)s - 100%% done.%(ext)s"
    assert app.template_with_suffix("custom_name", "x") == "custom_name - x"
    assert len(app.template_with_suffix("%(title)s.%(ext)s", "y" * 200)) <= 100


# --- build_args -------------------------------------------------------------------

def test_time_range_section():
    args = app.build_args("yt-dlp", {}, "/dl", {"start": 90, "end": 120})
    assert flag(args, "--download-sections") == "*90-120"
    assert flag(args, "-o") == "/dl/%(title)s - 1m30s-2m00s.%(ext)s"
    assert "--force-keyframes-at-cuts" not in args


def test_open_ended_and_fractional_sections():
    args = app.build_args("yt-dlp", {}, "/dl", {"start": 2.5, "end": None})
    assert flag(args, "--download-sections") == "*2.5-inf"
    args = app.build_args("yt-dlp", {}, "/dl", {"start": 0, "end": 5})
    assert flag(args, "--download-sections") == "*0-5"


def test_chapter_section_uses_its_time_range_and_title():
    args = app.build_args("yt-dlp", {"filename": {"template": "%(uploader)s/%(title)s.%(ext)s"}}, "/dl",
                          {"start": 5, "end": 17, "title": "The cool thing"})
    assert flag(args, "--download-sections") == "*5-17"
    assert flag(args, "-o") == "/dl/%(uploader)s/%(title)s - The cool thing.%(ext)s"


def test_force_keyframes_only_with_a_section():
    settings = {"format": {"forceKeyframesAtCuts": True}}
    assert "--force-keyframes-at-cuts" in app.build_args("yt-dlp", settings, "/dl", {"start": 0, "end": 5})
    assert "--force-keyframes-at-cuts" not in app.build_args("yt-dlp", settings, "/dl")


def test_split_chapters_keeps_the_template_and_points_chapter_files_at_the_folder():
    args = app.build_args("yt-dlp", {}, "/dl", {"splitChapters": True})
    assert "--split-chapters" in args and "--download-sections" not in args
    outs = [args[i + 1] for i, a in enumerate(args) if a == "-o"]
    assert outs == ["/dl/%(title)s.%(ext)s",
                    "chapter:/dl/%(title)s - %(section_number)03d %(section_title)s [%(id)s].%(ext)s"]


def test_info_args_never_carry_a_section():
    assert "--download-sections" not in app.info_args("yt-dlp", {}, "/dl", "https://v")


# --- preview chapters ---------------------------------------------------------------

def test_summarize_info_surfaces_chapters():
    info = app.summarize_info({"title": "t", "chapters": [
        {"start_time": 0, "end_time": 5, "title": "Intro"},
        {"start_time": 5, "end_time": 17},           # untitled
        {"start_time": 17},                          # no end: skipped
        "junk",
    ]})
    assert info["chapters"] == [{"title": "Intro", "start": 0, "end": 5}, {"title": "Chapter 2", "start": 5, "end": 17}]
    assert app.summarize_info({"title": "t"})["chapters"] == []


# --- queue + history --------------------------------------------------------------------

def test_section_rides_on_the_job_and_into_retry_and_history():
    import time
    seen = []

    def runner(job, emit):
        seen.append(job.get("section"))
        return 0
    q = app.DownloadQueue(lambda e, p: None, runner)
    q.enqueue([{"url": "https://v", "title": "T — Intro", "section": {"start": 0, "end": 5, "title": "Intro"}},
               {"url": "https://v", "section": "not a dict"}], {}, "/dl")
    t = time.time()
    while time.time() - t < 5 and q.is_active():
        time.sleep(0.02)
    assert seen == [{"start": 0, "end": 5, "title": "Intro"}, None]
    assert q.snapshot()[0]["section"] == {"start": 0, "end": 5, "title": "Intro"}
    assert q.retry(1) == 3
    t = time.time()
    while time.time() - t < 5 and q.is_active():
        time.sleep(0.02)
    assert seen[-1] == {"start": 0, "end": 5, "title": "Intro"}
    entry = app.history_entry(q.get(1) | {"status": "done"})
    assert entry["section"] == {"start": 0, "end": 5, "title": "Intro"}


def test_run_download_job_passes_the_section_through(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"; exe.write_text('#!/bin/sh\necho "ARGS: $@"\n'); exe.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(exe))
    lines = []
    job = {"id": 1, "url": "https://v", "dest": str(tmp_path), "settings": {}, "title": None, "pct": 0, "files": [],
           "tail": [], "proc": None, "cancel": False, "section": {"start": 1, "end": 2}}
    app.run_download_job(job, lambda ev, p: lines.append(p.get("line", "")))
    out = next(l for l in lines if l.startswith("ARGS:"))
    assert "--download-sections *1-2" in out and "- 1s-2s.%(ext)s" in out
