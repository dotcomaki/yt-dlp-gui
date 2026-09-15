"""Tests for the yt-dlp/ffmpeg candidate-list detection logic.

find_ytdlp() and find_ffmpeg() both walk an ordered candidate list and
return the first entry that exists and is executable, via the shared
_first_executable() helper. Candidate order matters (it's how the real
Homebrew-alias-drift and Apple-CLT-stub bugs got fixed — see native_host.py's
PYTHON_CANDIDATES comment for the sibling story on the interpreter side), so
these tests exercise both the shared helper and the two candidate lists.
"""
import os
import stat

import app


def make_executable(path):
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def test_first_executable_returns_first_match(tmp_path):
    missing = tmp_path / "does-not-exist"
    real = tmp_path / "real-binary"
    make_executable(real)

    assert app._first_executable([str(missing), str(real)]) == str(real)


def test_first_executable_skips_non_executable_file(tmp_path):
    not_executable = tmp_path / "not-executable"
    not_executable.write_text("no shebang, no x bit")
    real = tmp_path / "real-binary"
    make_executable(real)

    assert app._first_executable([str(not_executable), str(real)]) == str(real)


def test_first_executable_returns_none_when_nothing_matches(tmp_path):
    missing = tmp_path / "nope"
    assert app._first_executable([str(missing), None, ""]) is None


def test_first_executable_skips_none_and_empty_candidates(tmp_path):
    real = tmp_path / "real-binary"
    make_executable(real)
    assert app._first_executable([None, "", str(real)]) == str(real)


def test_find_ytdlp_uses_ytdlp_candidates(monkeypatch, tmp_path):
    fake = tmp_path / "yt-dlp"
    make_executable(fake)
    monkeypatch.setattr(app, "YTDLP_CANDIDATES", [str(fake)])
    assert app.find_ytdlp() == str(fake)


def test_find_ytdlp_returns_none_when_no_candidate_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "YTDLP_CANDIDATES", [str(tmp_path / "missing")])
    assert app.find_ytdlp() is None


def test_find_ffmpeg_uses_ffmpeg_candidates(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    make_executable(fake)
    monkeypatch.setattr(app, "FFMPEG_CANDIDATES", [str(fake)])
    assert app.find_ffmpeg() == str(fake)


def test_find_ffmpeg_returns_none_when_no_candidate_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "FFMPEG_CANDIDATES", [str(tmp_path / "missing")])
    assert app.find_ffmpeg() is None
