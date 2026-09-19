"""Tests for DownloadQueue and the pieces around it. The queue takes an
injectable runner and emit, so these never need pywebview or yt-dlp —
except the cancel-a-running-job tests, which use a real `sleep` subprocess
to prove terminate() actually reaches the process."""
import subprocess
import threading
import time

import pytest

import app


class Emit:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def __call__(self, event, payload):
        with self.lock:
            self.events.append((event, payload))

    def of(self, name):
        with self.lock:
            return [p for e, p in self.events if e == name]


def wait_until(pred, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def idle(queue):
    return wait_until(lambda: not queue.is_active())


# --- title extraction ------------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("[download] Destination: /dl/Me at the zoo.webm", "Me at the zoo"),
    ("[download] Destination: /dl/Some Video.f137.mp4", "Some Video"),        # intermediate stream
    ("[download] Destination: /dl/Kimi Antonelli's Lap | 2026 GP.webm", "Kimi Antonelli's Lap | 2026 GP"),
    ("[ExtractAudio] Destination: /dl/Song.mp3", "Song"),
    ('[Merger] Merging formats into "/dl/Clip.mp4"', "Clip"),
    # --write-subs makes the *first* Destination line the subtitle file; it
    # must not become the title (found in the real-window run: "Me at the zoo.en")
    ("[download] Destination: /dl/Me at the zoo.en.vtt", None),
    ("[download] Destination: /dl/Me at the zoo.en-US.srt", None),
    ("[download] Destination: /dl/Title.With.Dots.mp4", "Title.With.Dots"),
    ("[download]   0.4% of 246.27KiB at 356.87KiB/s ETA 00:00", None),
    ("[youtube] jNQXAC9IVRw: Downloading webpage", None),
])
def test_title_from_log_line(line, expected):
    assert app.title_from_log_line(line) == expected


# --- enqueue ---------------------------------------------------------------------

def test_enqueue_assigns_sequential_ids_and_snapshots_settings():
    emit = Emit()
    q = app.DownloadQueue(emit, runner=lambda job, emit: 0)
    settings = {"preset": "best"}
    ids = q.enqueue(["https://a", "https://b"], settings, "/dl")
    assert ids == [1, 2]
    settings["preset"] = "720p"  # mutate after enqueue
    assert idle(q)
    # jobs kept their own copy
    assert all(j["settings"]["preset"] == "best" for j in q._jobs)


def test_enqueue_skips_blank_urls_and_empty_input_is_a_noop():
    emit = Emit()
    q = app.DownloadQueue(emit, runner=lambda job, emit: 0)
    assert q.enqueue([], {}, "/dl") == []
    assert q.enqueue(["", "   ", None], {}, "/dl") == []
    assert emit.events == []  # nothing to report
    assert q.enqueue(["  https://a  "], {}, "/dl") == [1]
    assert q.snapshot()[0]["url"] == "https://a"


def test_enqueue_accepts_url_title_dicts_and_seeds_the_title():
    emit = Emit()
    gate = threading.Event()
    q = app.DownloadQueue(emit, runner=lambda job, emit: gate.wait(5) and 0)
    ids = q.enqueue([{"url": " https://a ", "title": "One"}, {"url": "https://b"}, {"title": "no url"}, "https://c"], {}, "/dl")
    assert ids == [1, 2, 3]
    snap = {j["url"]: j["title"] for j in q.snapshot()}
    assert snap == {"https://a": "One", "https://b": None, "https://c": None}  # title shows before any Destination line
    gate.set()
    assert idle(q)


def test_every_mutation_emits_a_queue_snapshot():
    emit = Emit()
    q = app.DownloadQueue(emit, runner=lambda job, emit: 0)
    q.enqueue(["https://a"], {}, "/dl")
    assert idle(q)
    n = len(emit.of("ytdlp-queue"))
    assert n >= 2  # at least: enqueued, running, done
    q.clear_finished()
    assert len(emit.of("ytdlp-queue")) == n + 1
    # snapshots only expose public fields, never the Popen or settings blob
    for snap in emit.of("ytdlp-queue"):
        for job in snap["jobs"]:
            assert set(job) == {"id", "url", "status", "title", "pct", "code", "hint"}


# --- sequential processing -------------------------------------------------------

def test_jobs_run_strictly_one_at_a_time_in_order():
    emit = Emit()
    running = []
    order = []
    lock = threading.Lock()

    def runner(job, emit):
        with lock:
            running.append(job["id"])
            assert len(running) == 1, "two jobs ran concurrently"
        order.append(job["id"])
        time.sleep(0.05)
        with lock:
            running.remove(job["id"])
        return 0

    q = app.DownloadQueue(emit, runner)
    q.enqueue(["https://a", "https://b", "https://c"], {}, "/dl")
    assert idle(q)
    assert order == [1, 2, 3]
    assert [j["status"] for j in q.snapshot()] == ["done", "done", "done"]


def test_enqueueing_while_running_extends_the_same_worker():
    emit = Emit()
    order = []

    def runner(job, emit):
        order.append(job["id"])
        time.sleep(0.05)
        return 0

    q = app.DownloadQueue(emit, runner)
    q.enqueue(["https://a"], {}, "/dl")
    time.sleep(0.01)
    q.enqueue(["https://b"], {}, "/dl")
    assert idle(q)
    assert order == [1, 2]


def test_failed_job_does_not_stop_the_queue():
    emit = Emit()
    q = app.DownloadQueue(emit, runner=lambda job, emit: 1 if job["url"].endswith("bad") else 0)
    q.enqueue(["https://ok1", "https://bad", "https://ok2"], {}, "/dl")
    assert idle(q)
    snap = q.snapshot()
    assert [j["status"] for j in snap] == ["done", "failed", "done"]
    assert snap[1]["code"] == 1
    done = emit.of("ytdlp-done")
    assert [d["success"] for d in done] == [True, False, True]
    assert all(d["jobId"] == i + 1 for i, d in enumerate(done))


def test_runner_exception_is_reported_as_failure_not_a_crash():
    emit = Emit()

    def runner(job, emit):
        raise RuntimeError("boom")

    q = app.DownloadQueue(emit, runner)
    q.enqueue(["https://a", "https://b"], {}, "/dl")
    assert idle(q)
    assert [j["status"] for j in q.snapshot()] == ["failed", "failed"]
    assert any("boom" in p["line"] for p in emit.of("ytdlp-log"))


def test_done_job_reports_100_percent():
    emit = Emit()
    q = app.DownloadQueue(emit, runner=lambda job, emit: 0)
    q.enqueue(["https://a"], {}, "/dl")
    assert idle(q)
    assert q.snapshot()[0]["pct"] == 100


# --- cancellation ---------------------------------------------------------------

def test_cancel_queued_job_never_runs():
    emit = Emit()
    ran = []
    gate = threading.Event()

    def runner(job, emit):
        ran.append(job["id"])
        gate.wait(5)  # hold the first job so the second stays queued
        return 0

    q = app.DownloadQueue(emit, runner)
    q.enqueue(["https://a", "https://b"], {}, "/dl")
    assert wait_until(lambda: ran == [1])
    assert q.cancel(2) is True
    assert q.snapshot()[1]["status"] == "cancelled"
    gate.set()
    assert idle(q)
    assert ran == [1]
    assert [j["status"] for j in q.snapshot()] == ["done", "cancelled"]


def test_terminate_job_kills_the_whole_process_group():
    # yt-dlp runs ffmpeg as a child for merging; cancelling must reach it too.
    # A shell that spawns a grandchild sleep and waits stands in for that.
    proc = subprocess.Popen(["sh", "-c", "sleep 30 & echo $!; wait"], stdout=subprocess.PIPE, text=True,
                            start_new_session=True)
    child_pid = int(proc.stdout.readline())
    app.terminate_job(proc)
    proc.wait(timeout=5)
    assert wait_until(lambda: subprocess.run(["kill", "-0", str(child_pid)], capture_output=True).returncode != 0)


def test_terminate_job_never_signals_our_own_process_group():
    # A process that isn't a session leader shares pytest's group: killpg
    # there would take the test runner down. Fall back to terminate().
    proc = subprocess.Popen(["sleep", "30"])
    app.terminate_job(proc)
    assert proc.wait(timeout=5) != 0
    # ...and we're still alive to assert it.


def test_cancel_running_job_terminates_the_real_process():
    emit = Emit()

    def runner(job, emit):
        proc = subprocess.Popen(["sleep", "30"])
        job["proc"] = proc
        return proc.wait()

    q = app.DownloadQueue(emit, runner)
    q.enqueue(["https://a"], {}, "/dl")
    assert wait_until(lambda: q._jobs[0].get("proc") is not None)
    pid = q._jobs[0]["proc"].pid
    t = time.time()
    assert q.cancel(1) is True
    assert idle(q), "cancelled job should finish promptly, not after 30s"
    assert time.time() - t < 5
    assert q.snapshot()[0]["status"] == "cancelled"
    # the sleep really died
    assert subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode != 0
    done = emit.of("ytdlp-done")[0]
    assert done["cancelled"] is True and done["success"] is False


def test_cancel_all_clears_queued_and_terminates_running():
    emit = Emit()

    def runner(job, emit):
        proc = subprocess.Popen(["sleep", "30"])
        job["proc"] = proc
        return proc.wait()

    q = app.DownloadQueue(emit, runner)
    q.enqueue(["https://a", "https://b", "https://c"], {}, "/dl")
    assert wait_until(lambda: q._jobs[0].get("proc") is not None)
    q.cancel_all()
    assert idle(q)
    assert [j["status"] for j in q.snapshot()] == ["cancelled", "cancelled", "cancelled"]


def test_cancel_unknown_id_is_harmless():
    emit = Emit()
    q = app.DownloadQueue(emit, runner=lambda job, emit: 0)
    assert q.cancel(999) is False


def test_cancel_finished_job_is_a_noop():
    emit = Emit()
    q = app.DownloadQueue(emit, runner=lambda job, emit: 0)
    q.enqueue(["https://a"], {}, "/dl")
    assert idle(q)
    q.cancel(1)
    assert q.snapshot()[0]["status"] == "done"


# --- clear_finished ----------------------------------------------------------------

def test_clear_finished_removes_only_terminal_jobs():
    emit = Emit()
    gate = threading.Event()

    def runner(job, emit):
        if job["url"] == "https://slow":
            gate.wait(5)
        return 0 if "ok" in job["url"] or job["url"] == "https://slow" else 1

    q = app.DownloadQueue(emit, runner)
    q.enqueue(["https://ok", "https://bad", "https://slow", "https://ok-queued"], {}, "/dl")
    assert wait_until(lambda: q.snapshot()[2]["status"] == "running")
    q.cancel(4)
    q.clear_finished()
    assert [(j["url"], j["status"]) for j in q.snapshot()] == [("https://slow", "running")]
    gate.set()
    assert idle(q)


def test_remove_drops_one_finished_row_only():
    emit = Emit()
    gate = threading.Event()

    def runner(job, emit):
        if job["url"] == "https://slow":
            gate.wait(5)
        return 0

    q = app.DownloadQueue(emit, runner)
    q.enqueue(["https://a", "https://slow", "https://b"], {}, "/dl")
    assert wait_until(lambda: q.snapshot()[1]["status"] == "running")
    assert q.remove(1) is True                 # done -> removed
    assert q.remove(2) is False                # running -> refused
    assert q.remove(3) is False                # queued -> refused
    assert q.remove(999) is False
    assert [j["url"] for j in q.snapshot()] == ["https://slow", "https://b"]
    gate.set()
    assert idle(q)


# --- Api wiring ----------------------------------------------------------------------

def test_api_methods_delegate_to_the_queue():
    api = app.Api()
    api._emit = Emit()
    api.queue = app.DownloadQueue(api._emit, runner=lambda job, emit: 0)
    assert api.enqueue(["https://a"], {"preset": "best"}, "/dl") == [1]
    assert idle(api.queue)
    assert api.queue_snapshot()[0]["status"] == "done"
    assert api.cancel_download(1) is True  # no-op on a done job, but delegates
    assert api.remove_download(1) is True
    assert api.clear_finished() is True
    assert api.queue_snapshot() == []
    assert api.cancel_all() is True


# --- run_download_job (the real runner, with yt-dlp stubbed by a script) -----------

def test_run_download_job_streams_log_title_and_progress(tmp_path, monkeypatch):
    fake = tmp_path / "yt-dlp"
    fake.write_text(
        "#!/bin/sh\n"
        "echo '[youtube] abc: Downloading webpage'\n"
        "echo '[download] Destination: /dl/My Video.f137.mp4'\n"
        "echo '[download]  50.0% of 10.00MiB at 2.00MiB/s ETA 00:02'\n"
        "echo '[download] 100% of 10.00MiB in 00:00:05 at 2.00MiB/s'\n"
        "exit 0\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(app, "find_ytdlp", lambda: str(fake))
    monkeypatch.setattr(app, "find_ffmpeg", lambda: None)

    emit = Emit()
    job = {"id": 7, "url": "https://x", "dest": str(tmp_path / "out"), "settings": {},
           "status": "running", "title": None, "pct": 0, "code": None, "proc": None, "cancel": False}
    code = app.run_download_job(job, emit)

    assert code == 0
    assert job["title"] == "My Video"
    assert job["pct"] == 100.0  # the final "[download] 100% of ..." line counts too
    assert emit.of("ytdlp-title") == [{"jobId": 7, "title": "My Video"}]
    prog = emit.of("ytdlp-progress")
    assert [p["pct"] for p in prog] == [50.0, 100.0]
    assert prog[0]["jobId"] == 7 and prog[0]["eta"] == "00:02"
    logged = [p["line"] for p in emit.of("ytdlp-log")]
    assert logged[0].startswith("$ ") and "https://x" in logged[0]
    assert all(p["jobId"] == 7 for p in emit.of("ytdlp-log"))
    assert (tmp_path / "out").is_dir()  # dest gets created


def test_run_download_job_reports_missing_binary(monkeypatch):
    monkeypatch.setattr(app, "find_ytdlp", lambda: None)
    emit = Emit()
    job = {"id": 1, "url": "https://x", "dest": "/tmp", "settings": {},
           "status": "running", "title": None, "pct": 0, "code": None, "proc": None, "cancel": False}
    assert app.run_download_job(job, emit) == -1
    assert "not found" in emit.of("ytdlp-log")[0]["line"]


# --- concurrency (#8) ----------------------------------------------------------------

class Overlap:
    """Runner that records how many jobs were in flight at once."""
    def __init__(self, hold=0.15):
        self.hold = hold
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0
        self.started = []

    def __call__(self, job, emit):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
            self.started.append(job["id"])
        time.sleep(self.hold)
        with self.lock:
            self.running -= 1
        return 0


def test_default_is_sequential():
    runner = Overlap()
    q = app.DownloadQueue(Emit(), runner)
    q.enqueue(["a", "b", "c"], {}, "/dl")
    assert idle(q)
    assert runner.peak == 1


def test_max_concurrent_bounds_in_flight_jobs():
    runner = Overlap()
    q = app.DownloadQueue(Emit(), runner, max_concurrent=2)
    t = time.time()
    q.enqueue(["a", "b", "c", "d"], {}, "/dl")
    assert idle(q)
    elapsed = time.time() - t
    assert runner.peak == 2
    # Slots are *assigned* in queue order under the lock, but the threads
    # that then start them race, so the observed start order isn't fixed
    # (CI saw [1, 2, 4, 3]). Strict ordering is covered by the sequential
    # test; here only "everything ran" is a valid claim.
    assert sorted(runner.started) == [1, 2, 3, 4]
    assert elapsed < 4 * runner.hold                  # actually overlapped, not serialized
    assert [j["status"] for j in q.snapshot()] == ["done"] * 4


def test_raising_max_concurrent_mid_queue_starts_more_immediately():
    runner = Overlap(hold=0.4)
    q = app.DownloadQueue(Emit(), runner, max_concurrent=1)
    q.enqueue(["a", "b", "c"], {}, "/dl")
    assert wait_until(lambda: runner.running == 1)
    q.set_max_concurrent(3)
    assert wait_until(lambda: runner.running == 3, timeout=0.3), "extra slots didn't start"
    assert idle(q)


def test_lowering_max_concurrent_does_not_interrupt_running_jobs():
    runner = Overlap(hold=0.3)
    q = app.DownloadQueue(Emit(), runner, max_concurrent=2)
    q.enqueue(["a", "b", "c"], {}, "/dl")
    assert wait_until(lambda: runner.running == 2)
    q.set_max_concurrent(1)
    time.sleep(0.05)
    assert runner.running == 2                         # nothing killed
    assert idle(q)
    assert [j["status"] for j in q.snapshot()] == ["done"] * 3
    assert runner.peak == 2


def test_cancel_all_with_parallel_running_jobs():
    def runner(job, emit):
        proc = subprocess.Popen(["sleep", "30"])
        job["proc"] = proc
        return proc.wait()

    q = app.DownloadQueue(Emit(), runner, max_concurrent=2)
    q.enqueue(["a", "b", "c"], {}, "/dl")
    assert wait_until(lambda: sum(1 for j in q._jobs if j.get("proc")) == 2)
    q.cancel_all()
    assert idle(q)
    assert [j["status"] for j in q.snapshot()] == ["cancelled"] * 3


def test_api_enqueue_applies_parallel_setting():
    api = app.Api()
    api._emit = Emit()
    runner = Overlap()
    api.queue = app.DownloadQueue(api._emit, runner)
    api.enqueue(["a", "b", "c", "d"], {"network": {"parallel": "2"}}, "/dl")
    assert idle(api.queue)
    assert runner.peak == 2
    assert api.set_parallel(1) is True
    assert api.queue._max_concurrent == 1
