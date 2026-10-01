"""Stopping. ECS sends SIGTERM and, thirty seconds later, SIGKILL. Whatever
is in progress when the first arrives has to be finished or put down cleanly
before the second."""

from __future__ import annotations

import http.server
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app import config
from app.models import IngestRun, Posting
from app.services import ingest_scheduler
from app.sources import backfill, base, github_list
from app.sources.base import Source
from tests.conftest import INGEST_ROWS, age_runs, fake_source

BACKEND = Path(__file__).resolve().parent.parent
STOP_TIMEOUT = 30  # what ECS allows between SIGTERM and SIGKILL


def runs(db) -> list[IngestRun]:
    db.expire_all()
    return list(db.scalars(select(IngestRun).order_by(IngestRun.id)))


def lock_is_free(db) -> bool:
    return not backfill.is_running(db)


class Waiting(Source):
    """Fetches for ever, looking for the request to stop as it goes."""

    name = "simplify"
    started = threading.Event()

    def fetch(self):
        type(self).started.set()
        while True:
            base.check_cancelled()
            time.sleep(0.02)


@pytest.fixture()
def waiting():
    Waiting.started = threading.Event()
    return {"simplify": Waiting, "vanshb03": fake_source("vanshb03")}


# --------------------------------------------------------------------------- #
# An ingest that is asked to stop
# --------------------------------------------------------------------------- #


def test_an_ingest_asked_to_stop_stops_and_says_so(db, waiting):
    results = []
    thread = threading.Thread(target=lambda: results.append(ingest_scheduler.run_due(waiting)))
    thread.start()
    assert Waiting.started.wait(5)
    assert backfill.is_running(db)

    asked = time.perf_counter()
    base.cancel.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert time.perf_counter() - asked < 1

    (made,) = results
    # The source in progress was put down, and the next was not begun.
    assert [(r.source, r.error) for r in made] == [("simplify", backfill.INTERRUPTED)]
    (run,) = runs(db)
    assert (run.source, run.error) == ("simplify", backfill.INTERRUPTED)
    assert run.finished_at is not None and run.fetched == run.upserted == 0
    assert lock_is_free(db)
    assert not ingest_scheduler._in_flight.is_set()


def test_stopping_part_way_through_writing_keeps_none_of_it(db, monkeypatch):
    """Asked to stop between two batches. The first batch was written inside
    a transaction that is now abandoned, so the table is as it was."""
    ingest_scheduler.run_due({"simplify": fake_source("simplify")})
    age_runs(db, 25)
    before = {p.source_id: p.content_hash for p in db.scalars(select(Posting))}

    from tests.conftest import make_row

    many = [make_row(f"new-{n}", company=f"Company {n}") for n in range(25)]
    monkeypatch.setattr(backfill, "_BATCH", 10)
    executed = []
    real_execute = type(db).execute

    def stop_after_first_batch(self, statement, *args, **kwargs):
        result = real_execute(self, statement, *args, **kwargs)
        if "INSERT INTO postings" in str(statement):
            executed.append(1)
            base.cancel.set()
        return result

    monkeypatch.setattr(type(db), "execute", stop_after_first_batch)
    (result,) = ingest_scheduler.run_due({"simplify": fake_source("simplify", rows=many)})
    monkeypatch.undo()

    assert result.error == backfill.INTERRUPTED
    assert len(executed) == 1, "it went on to the next batch"
    db.expire_all()
    assert {p.source_id: p.content_hash for p in db.scalars(select(Posting))} == before
    assert db.scalar(select(func.count()).where(Posting.source_id.like("new-%"))) == 0
    assert runs(db)[-1].error == backfill.INTERRUPTED and lock_is_free(db)


def test_an_interrupted_source_is_due_again_at_once(db, waiting):
    thread = threading.Thread(target=ingest_scheduler.run_due, args=(waiting,))
    thread.start()
    Waiting.started.wait(5)
    base.cancel.set()
    thread.join(timeout=5)
    base.cancel.clear()

    assert ingest_scheduler.due_sources(db, ["simplify"]) == ["simplify"]
    (again,) = ingest_scheduler.run_due({"simplify": fake_source("simplify")})
    assert again.error is None and again.inserted == len(INGEST_ROWS)


def test_nothing_is_started_once_stopping_has_been_asked(db):
    base.cancel.set()
    source = fake_source("simplify")
    assert ingest_scheduler.run_due({"simplify": source}) == []
    assert source.fetches == 0 and runs(db) == []


# --------------------------------------------------------------------------- #
# A download that is asked to stop
# --------------------------------------------------------------------------- #


class Trickle(http.server.BaseHTTPRequestHandler):
    """Serves a JSON array one small piece at a time, slowly, for ever."""

    body = None

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            if type(self).body is not None:
                self.wfile.write(type(self).body)
                return
            self.wfile.write(b"[")
            while True:
                self.wfile.write(b'{"id": "x"},' * 30_000)
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass  # the client hung up, which is the point

    def log_message(self, *args):
        pass


@pytest.fixture()
def upstream(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Trickle)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    ).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/listings.json"
    monkeypatch.setattr(github_list, "listings_url", lambda repo, branch=None: url)
    Trickle.body = None
    yield server
    server.shutdown()


def test_a_download_in_progress_is_abandoned(upstream):
    outcome = []

    def download():
        try:
            outcome.append(github_list.fetch_listings("any/repo"))
        except BaseException as exc:  # noqa: BLE001
            outcome.append(exc)

    thread = threading.Thread(target=download)
    thread.start()
    time.sleep(0.4)
    assert thread.is_alive(), "the download should still be arriving"
    asked = time.perf_counter()
    base.cancel.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert time.perf_counter() - asked < 1.5
    assert isinstance(outcome[0], base.Cancelled)


def test_a_download_has_a_deadline_of_its_own(upstream, monkeypatch):
    monkeypatch.setattr(config, "SOURCE_FETCH_TIMEOUT_S", 0.5)
    started = time.perf_counter()
    with pytest.raises(TimeoutError, match="did not finish in 0.5 seconds"):
        github_list.fetch_listings("any/repo")
    assert time.perf_counter() - started < 3


def test_a_download_that_is_too_large_is_given_up_on(upstream, monkeypatch):
    monkeypatch.setattr(github_list, "_MAX_BYTES", 1024 * 1024)
    with pytest.raises(ValueError, match="is larger than 1 MB"):
        github_list.fetch_listings("any/repo")


def test_an_ordinary_download_still_works(upstream):
    Trickle.body = b'[{"id": "a", "title": "t"}, "not a row", {"id": "b"}]'
    assert github_list.fetch_listings("any/repo") == [{"id": "a", "title": "t"}, {"id": "b"}]
    Trickle.body = b'{"not": "a list"}'
    with pytest.raises(ValueError, match="did not return a JSON array"):
        github_list.fetch_listings("any/repo")


# --------------------------------------------------------------------------- #
# The server, stopping
# --------------------------------------------------------------------------- #


def test_the_server_waits_for_a_refresh_to_stop_before_it_does(db, waiting, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(config, "AUTO_INGEST", True)
    monkeypatch.setattr(backfill, "SOURCES", waiting)
    with TestClient(app) as client:
        assert Waiting.started.wait(5), "the refresh did not start"
        assert client.get("/health").status_code == 200
        leaving = time.perf_counter()
    assert time.perf_counter() - leaving < 3

    assert [r.error for r in runs(db)] == [backfill.INTERRUPTED]
    assert lock_is_free(db) and not ingest_scheduler._in_flight.is_set()
    # The request to stop was honoured and withdrawn: a later ingest in this
    # process is not cancelled before it starts.
    assert not base.cancel.is_set()


def test_the_server_does_not_wait_for_ever(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    begun = threading.Event()

    class Deaf(Source):
        name = "simplify"

        def fetch(self):
            begun.set()
            time.sleep(4)  # never looks
            return []

    monkeypatch.setattr(config, "AUTO_INGEST", True)
    monkeypatch.setattr(config, "INGEST_SHUTDOWN_GRACE_S", 0.5)
    monkeypatch.setattr(backfill, "SOURCES", {"simplify": Deaf})
    with TestClient(app):
        assert begun.wait(5)
        leaving = time.perf_counter()
    took = time.perf_counter() - leaving
    assert 0.4 < took < 2, took
    # Let the straggler finish before the next test uses the database.
    assert ingest_scheduler._wait_until_idle(10)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(manner: str, tmp_path, **settings) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    env = os.environ | {
        "AUTO_INGEST": "true",
        "INGEST_CHECK_MINUTES": "30",
        "RATE_LIMIT_ENABLED": "false",
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        **settings,
    }
    process = subprocess.Popen(
        [
            sys.executable,
            str(BACKEND / "tests" / "support" / "refreshing_server.py"),
            str(port),
            manner,
        ],  # fmt: skip
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if urllib.request.urlopen(base_url + "/health", timeout=1).status == 200:
                return process, base_url
        except OSError:
            time.sleep(0.1)
    process.kill()
    pytest.fail("the server did not start")


def _wait_for_a_run_in_progress(db) -> IngestRun:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        in_progress = [r for r in runs(db) if r.finished_at is None]
        if in_progress and backfill.is_running(db):
            return in_progress[0]
        time.sleep(0.05)
    pytest.fail("no refresh began")


def test_sigterm_during_a_refresh(db, tmp_path):
    """A real process, a real signal. The refresh is recorded as interrupted,
    the lock is released, and the process has exited cleanly long before it
    would have been killed."""
    process, base_url = _serve("polite", tmp_path)
    try:
        _wait_for_a_run_in_progress(db)
        assert urllib.request.urlopen(base_url + "/health", timeout=2).status == 200

        sent = time.perf_counter()
        process.send_signal(signal.SIGTERM)
        code = process.wait(timeout=STOP_TIMEOUT)
        took = time.perf_counter() - sent
    finally:
        if process.poll() is None:
            process.kill()

    # uvicorn shuts down cleanly and then re-raises the signal it caught, so
    # the status is "ended by SIGTERM", which is what a container runtime
    # expects of a task it asked to stop. What it must not be is SIGKILL.
    assert code in (0, -signal.SIGTERM), code
    assert took < 5, f"took {took:.1f}s to stop"
    (run,) = runs(db)
    assert run.error == backfill.INTERRUPTED and run.finished_at is not None
    assert lock_is_free(db)
    assert db.scalar(select(func.count()).select_from(Posting)) == 0


def test_sigterm_during_a_refresh_that_will_not_stop(db, tmp_path):
    """The refresh ignores the request. The process gives it the grace
    period and then leaves without it, still inside the stop timeout. What
    it left unfinished is closed by the next ingest, anywhere."""
    process, _ = _serve("deaf", tmp_path, INGEST_SHUTDOWN_GRACE_S="2")
    try:
        _wait_for_a_run_in_progress(db)
        sent = time.perf_counter()
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=STOP_TIMEOUT)
        took = time.perf_counter() - sent
    finally:
        if process.poll() is None:
            process.kill()

    assert 1.5 < took < 10, f"took {took:.1f}s to stop"
    # The connection went with the process, and the lock with the connection.
    deadline = time.monotonic() + 5
    while not lock_is_free(db) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert lock_is_free(db)
    (left,) = runs(db)
    assert left.finished_at is None and left.error is None

    (result,) = ingest_scheduler.run_due({"simplify": fake_source("simplify")})
    assert result.error is None
    first, second = runs(db)
    assert first.error == backfill.INTERRUPTED and first.finished_at is not None
    assert second.error is None


def test_the_container_gives_itself_less_than_the_stop_timeout():
    """Ten seconds for requests in progress, fifteen for a refresh. The
    numbers in the entrypoint and the settings have to agree with that."""
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert "--timeout-graceful-shutdown 10" in entrypoint
    assert "--no-proxy-headers" in entrypoint
    assert entrypoint.rstrip().splitlines()[-2].startswith("exec uvicorn"), "uvicorn must be PID 1"
    assert 10 + config.INGEST_SHUTDOWN_GRACE_S < STOP_TIMEOUT


def test_a_manual_backfill_stops_on_sigterm_too(db, tmp_path):
    script = (
        "import sys, time\n"
        "from app.sources import backfill, base\n"
        "from app.sources.base import Source\n"
        "class Waiting(Source):\n"
        "    name = 'simplify'\n"
        "    def fetch(self):\n"
        "        print('fetching', flush=True)\n"
        "        while True:\n"
        "            base.check_cancelled(); time.sleep(0.02)\n"
        "backfill.SOURCES.clear(); backfill.SOURCES['simplify'] = Waiting\n"
        "sys.exit(backfill.main(['--source', 'simplify']))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=os.environ | {"AUTO_INGEST": "false"},
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "fetching"
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
    (run,) = runs(db)
    assert run.error == backfill.INTERRUPTED and run.finished_at is not None
    assert lock_is_free(db)
    assert db.execute(text("SELECT count(*) FROM postings")).scalar() == 0
