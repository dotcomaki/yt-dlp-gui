"""Tests for pause/resume, the queue file written after every change, and
restoring it (paused) on the next launch."""
import os
import threading
import time

import app


def idle(q, timeout=10):
    """wait_idle, not is_active: a job's persist/history/archive writes run
    on its worker thread after the status flips, so "nothing is running"
    comes a moment before "everything is written"."""
    return q.wait_idle(timeout)


def wait_until(pred, timeout=5):
    t = time.time()
    while time.time() - t < timeout:
        if pred():
            return True
        time.sleep(0.02)
    return False


# --- pause ---------------------------------------------------------------------------

def test_paused_queue_starts_nothing_and_resume_dispatches():
    started = []
    q = app.DownloadQueue(lambda e, p: None, lambda job, emit: started.append(job["url"]) or 0)
    q.set_paused(True)
    q.enqueue(["https://a", "https://b"], {}, "/dl")
    time.sleep(0.2)
    assert started == [] and [j["status"] for j in q.snapshot()] == ["queued", "queued"]
    assert q.state()["paused"] is True
    q.set_paused(False)
    assert idle(q)
    assert started == ["https://a", "https://b"] and q.state()["paused"] is False


def test_pausing_lets_running_jobs_finish_but_holds_the_rest():
    gate = threading.Event()
    started = []

    def runner(job, emit):
        started.append(job["url"])
        gate.wait(5)
        return 0
    q = app.DownloadQueue(lambda e, p: None, runner, max_concurrent=1)
    q.enqueue(["https://a", "https://b"], {}, "/dl")
    assert wait_until(lambda: started == ["https://a"])
    q.set_paused(True)
    gate.set()
    assert wait_until(lambda: q.snapshot()[0]["status"] == "done")
    time.sleep(0.1)
    assert started == ["https://a"] and q.snapshot()[1]["status"] == "queued"
    q.set_paused(False)
    assert idle(q)
    assert started == ["https://a", "https://b"]


def test_state_and_snapshot_carry_files():
    def runner(job, emit):
        job["files"].append("/dl/x.mp4")
        return 0
    q = app.DownloadQueue(lambda e, p: None, runner)
    q.enqueue(["https://a"], {}, "/dl")
    assert idle(q)
    assert q.state()["jobs"][0]["files"] == ["/dl/x.mp4"]


# --- persistence -----------------------------------------------------------------------

def test_pending_is_written_after_every_change_and_removed_when_empty():
    gate = threading.Event()
    q = app.DownloadQueue(lambda e, p: None, lambda job, emit: gate.wait(5) and 0)
    q.persist = app.write_queue
    q.enqueue([{"url": "https://a", "title": "A", "section": {"start": 1, "end": 2}}, "https://b"], {"preset": "480p"}, "/dl")
    assert wait_until(lambda: os.path.exists(app.queue_path()))
    items = app.load_queue()
    assert [(i["url"], i["title"], i["section"], i["settings"], i["dest"]) for i in items] == [
        ("https://a", "A", {"start": 1, "end": 2}, {"preset": "480p"}, "/dl"),   # running: still pending
        ("https://b", None, None, {"preset": "480p"}, "/dl"),
    ]
    q.cancel(2)
    assert wait_until(lambda: [i["url"] for i in app.load_queue()] == ["https://a"])
    gate.set()
    assert idle(q)
    assert wait_until(lambda: not os.path.exists(app.queue_path()))


def test_persist_failure_does_not_stall_the_queue():
    q = app.DownloadQueue(lambda e, p: None, lambda job, emit: 0)
    q.persist = lambda items: (_ for _ in ()).throw(OSError("disk full"))
    q.enqueue(["https://a", "https://b"], {}, "/dl")
    assert idle(q)
    assert [j["status"] for j in q.snapshot()] == ["done", "done"]


def test_load_queue_tolerates_garbage():
    assert app.load_queue() == []
    with open(app.queue_path(), "w") as f:
        f.write("{")
    assert app.load_queue() == []
    app.write_queue([{"url": "https://a"}, {"nourl": 1}, "junk", {"url": ""}])
    assert app.load_queue() == [{"url": "https://a"}]


def test_restore_requeues_paused_with_each_items_own_settings():
    app.write_queue([{"url": "https://a", "title": "A", "section": None, "settings": {"preset": "720p"}, "dest": "/x"},
                     {"url": "https://b", "settings": {"preset": "best"}, "dest": "/y"}])
    api = app.Api()
    api.window = None
    started = []
    api.queue = app.DownloadQueue(api._emit, lambda job, emit: started.append((job["url"], job["settings"]["preset"], job["dest"])) or 0)
    api.queue.persist = api._persist_queue
    assert api.restore_queue() == 2
    time.sleep(0.2)
    assert started == [] and api.queue.state()["paused"] is True
    state = api.queue_state()
    assert state["restored"] == 2 and api.queue_state()["restored"] == 0   # notice is one-time
    assert [(j["url"], j["title"]) for j in state["jobs"]] == [("https://a", "A"), ("https://b", None)]
    api.set_paused(False)
    assert idle(api.queue)
    assert started == [("https://a", "720p", "/x"), ("https://b", "best", "/y")]
    assert not os.path.exists(app.queue_path())


def test_restore_with_nothing_pending_is_a_noop():
    api = app.Api()
    api.window = None
    assert api.restore_queue() == 0 and api.queue.state()["paused"] is False
