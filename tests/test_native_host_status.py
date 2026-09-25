"""Tests for noticing that the browser's native-host manifests point at an
old location — what happens when the project folder is moved or renamed."""
import json
import os

import pytest

import app


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path), 1) if p.startswith("~") else p)
    return tmp_path


def write_manifest(directory, path):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, app.NATIVE_HOST_NAME + ".json"), "w") as f:
        json.dump({"name": app.NATIVE_HOST_NAME, "path": path, "type": "stdio"}, f)


def chrome_dir(home):
    return os.path.join(str(home), "Library", "Application Support", "Google", "Chrome", "NativeMessagingHosts")


def test_nothing_installed_is_not_a_problem(fake_home):
    assert app.native_host_status() == {"installed": 0, "stale": [], "ok": True}


def test_a_manifest_pointing_here_is_fine(fake_home, tmp_path):
    project = tmp_path / "project"
    (project / "native-host").mkdir(parents=True)
    (project / "native-host" / "native_host.py").write_text("#!/usr/bin/env python3\n")
    write_manifest(chrome_dir(fake_home), str(project / "native-host" / "native_host.py"))
    status = app.native_host_status(str(project))
    assert status["installed"] == 1 and status["ok"] is True


def test_a_manifest_left_behind_by_a_move_is_reported(fake_home, tmp_path):
    project = tmp_path / "new-name"
    (project / "native-host").mkdir(parents=True)
    (project / "native-host" / "native_host.py").write_text("")
    write_manifest(chrome_dir(fake_home), str(tmp_path / "old-name" / "native-host" / "native_host.py"))
    status = app.native_host_status(str(project))
    assert status["installed"] == 1 and status["ok"] is False
    assert status["stale"] == [os.path.join(chrome_dir(fake_home), app.NATIVE_HOST_NAME + ".json")]


def test_several_browsers_are_checked_and_only_the_stale_ones_listed(fake_home, tmp_path):
    project = tmp_path / "project"
    here = project / "native-host" / "native_host.py"
    here.parent.mkdir(parents=True)
    here.write_text("")
    write_manifest(chrome_dir(fake_home), str(here))
    brave = os.path.join(str(fake_home), "Library", "Application Support", "BraveSoftware",
                         "Brave-Browser", "NativeMessagingHosts")
    write_manifest(brave, "/somewhere/else/native_host.py")
    firefox = os.path.join(str(fake_home), ".mozilla", "native-messaging-hosts")
    write_manifest(firefox, "/somewhere/else/native_host.py")
    status = app.native_host_status(str(project))
    assert status["installed"] == 3
    assert sorted(status["stale"]) == sorted([
        os.path.join(brave, app.NATIVE_HOST_NAME + ".json"),
        os.path.join(firefox, app.NATIVE_HOST_NAME + ".json"),
    ])


def test_a_symlinked_project_still_counts_as_here(fake_home, tmp_path):
    real = tmp_path / "real"
    (real / "native-host").mkdir(parents=True)
    (real / "native-host" / "native_host.py").write_text("")
    link = tmp_path / "link"
    os.symlink(real, link)
    write_manifest(chrome_dir(fake_home), str(link / "native-host" / "native_host.py"))
    assert app.native_host_status(str(real))["ok"] is True


def test_an_unreadable_or_broken_manifest_is_ignored(fake_home, tmp_path):
    project = tmp_path / "project"
    (project / "native-host").mkdir(parents=True)
    (project / "native-host" / "native_host.py").write_text("")
    os.makedirs(chrome_dir(fake_home), exist_ok=True)
    with open(os.path.join(chrome_dir(fake_home), app.NATIVE_HOST_NAME + ".json"), "w") as f:
        f.write("{not json")
    assert app.native_host_status(str(project)) == {"installed": 0, "stale": [], "ok": True}
