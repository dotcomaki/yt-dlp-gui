"""Tests for desktop notifications: the per-OS command, the queue-drained
summary text, and the Api hook that decides when to fire (once per batch,
never per job, never for cancellations, off when the setting is off)."""
import threading
import time

import pytest

import app


# --- notify_command --------------------------------------------------------------

def test_macos_uses_osascript_with_escaping(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "darwin")
    cmd = app.notify_command("yt-dlp", 'Downloaded: He said "hi" \\ done')
    assert cmd[:2] == ["osascript", "-e"]
    assert cmd[2] == 'display notification "Downloaded: He said \\"hi\\" \\\\ done" with title "yt-dlp"'


def test_linux_uses_notify_send_when_present(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.shutil, "which", lambda name: "/usr/bin/notify-send" if name == "notify-send" else None)
    assert app.notify_command("yt-dlp", "hello") == ["/usr/bin/notify-send", "yt-dlp", "hello"]


def test_linux_without_notify_send_is_none(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.shutil, "which", lambda name: None)
    assert app.notify_command("yt-dlp", "hello") is None


def test_other_platforms_are_none(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "win32")
    assert app.notify_command("yt-dlp", "hello") is None


def test_send_notification_is_quiet_when_unsupported(monkeypatch):
    monkeypatch.setattr(app, "notify_command", lambda t, m: None)
    assert app.send_notification("yt-dlp", "x") is False


# --- summarize_finished -------------------------------------------------------------

def J(status, title=None, url="https://u"):
    return {"status": status, "title": title, "url": url}


@pytest.mark.parametrize("jobs,expected", [
    ([], None),
    ([J("cancelled")], None),                                       # user did it, no news
    ([J("done", "Me at the zoo")], "Downloaded: Me at the zoo"),
    ([J("done", None, "https://x")], "Downloaded: https://x"),        # no title resolved
    ([J("failed", "Bad One")], "Download failed: Bad One"),
    ([J("done", "a"), J("done", "b")], "2 downloads finished"),
    ([J("done", "a"), J("failed", "b")], "1 download finished, 1 failed"),
    ([J("failed", "a"), J("failed", "b")], "2 failed"),
    ([J("done", "a"), J("cancelled", "b"), J("done", "c")], "2 downloads finished"),
])
def test_summarize_finished(jobs, expected):
    assert app.summarize_finished(jobs) == expected


# --- Api hook -----------------------------------------------------------------------

def make_api(runner, **settings_overrides):
    api = app.Api()
    api.window = None  # no JS to dispatch to
    api.queue = app.DownloadQueue(api._emit, runner)
    sent = []
    api.notifier = lambda title, msg: sent.append((title, msg))
    return api, sent


def idle(q, timeout=5):
    t = time.time()
    while time.time() - t < timeout:
        if not q.is_active():
            return True
        time.sleep(0.02)
    return False


def test_single_download_notifies_once_with_its_title():
    def runner(job, emit):
        job["title"] = "Me at the zoo"
        return 0
    api, sent = make_api(runner)
    api.enqueue(["https://a"], {}, "/dl")
    assert idle(api.queue)
    assert sent == [("yt-dlp", "Downloaded: Me at the zoo")]


def test_batch_notifies_once_when_the_queue_drains_not_per_job():
    def runner(job, emit):
        time.sleep(0.03)
        return 1 if job["url"].endswith("bad") else 0
    api, sent = make_api(runner)
    api.enqueue(["https://a", "https://bad", "https://c"], {}, "/dl")
    assert idle(api.queue)
    assert sent == [("yt-dlp", "2 downloads finished, 1 failed")]


def test_parallel_batch_still_notifies_once():
    def runner(job, emit):
        time.sleep(0.05)
        return 0
    api, sent = make_api(runner)
    api.enqueue(["https://a", "https://b", "https://c", "https://d"], {"network": {"parallel": "2"}}, "/dl")
    assert idle(api.queue)
    time.sleep(0.05)
    assert sent == [("yt-dlp", "4 downloads finished")]


def test_second_batch_reports_only_its_own_jobs():
    api, sent = make_api(lambda job, emit: 0)
    api.enqueue(["https://a"], {}, "/dl")
    assert idle(api.queue)
    api.enqueue(["https://b", "https://c"], {}, "/dl")
    assert idle(api.queue)
    assert sent == [("yt-dlp", "Downloaded: https://a"), ("yt-dlp", "2 downloads finished")]


def test_disabled_setting_suppresses_notification():
    api, sent = make_api(lambda job, emit: 0)
    api.enqueue(["https://a"], {"notifications": {"enabled": False}}, "/dl")
    assert idle(api.queue)
    assert sent == []


def test_default_is_enabled_for_settings_without_the_key():
    assert app.notifications_enabled({}) is True
    assert app.notifications_enabled({"notifications": {}}) is True
    assert app.notifications_enabled({"notifications": {"enabled": False}}) is False


def test_cancelled_batch_does_not_notify():
    gate = threading.Event()

    def runner(job, emit):
        gate.wait(5)
        return 0
    api, sent = make_api(runner)
    api.enqueue(["https://a", "https://b"], {}, "/dl")
    time.sleep(0.05)
    api.queue.cancel_all()
    gate.set()
    assert idle(api.queue)
    assert sent == []


def test_notifier_failure_never_breaks_the_queue():
    def boom(title, msg):
        raise OSError("no notification daemon")
    api, sent = make_api(lambda job, emit: 0)
    api.notifier = boom
    # The hook runs on the worker thread before the queue emits its snapshot
    # and dispatches the next job — an escaping exception would stall the
    # queue. Two batches: the second must still run after the first's
    # notifier blew up.
    api.enqueue(["https://a"], {}, "/dl")
    assert idle(api.queue)
    api.enqueue(["https://b"], {}, "/dl")
    assert idle(api.queue)
    assert [j["status"] for j in api.queue_snapshot()] == ["done", "done"]
