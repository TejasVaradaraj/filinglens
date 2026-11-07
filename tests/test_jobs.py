"""Job queue semantics against the separate filinglens_test database."""
import threading

import pytest

from filinglens import config

TEST_DB = "filinglens_test"


@pytest.fixture
def q(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(config.DATABASE_URL, connect_timeout=2, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running")
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone():
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setattr(config, "DATABASE_URL", config.DATABASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB}")
    from filinglens import db, jobs
    jobs.init()
    with db.connect() as conn:
        conn.execute("TRUNCATE jobs")
    monkeypatch.setattr(jobs, "BACKOFF_BASE_S", 0)
    yield jobs


def test_enqueue_is_idempotent(q):
    assert q.enqueue("noop", {}, "k1") is not None
    assert q.enqueue("noop", {}, "k1") is None


def test_parallel_workers_never_claim_the_same_job(q):
    for i in range(20):
        q.enqueue("noop", {"i": i}, f"job{i}")
    claimed, lock = [], threading.Lock()

    def worker(n):
        while (job := q.claim(f"w{n}")) is not None:
            with lock:
                claimed.append(job["id"])

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == 20 and len(set(claimed)) == 20


def test_retry_then_dead_letter(q, monkeypatch):
    calls = []

    def flaky(p):
        calls.append(1)
        raise RuntimeError("SEC returned 503")

    monkeypatch.setitem(q.HANDLERS, "flaky", flaky)
    q.enqueue("flaky", {}, "f1", max_attempts=3)
    while q.run_one("w"):
        pass
    assert len(calls) == 3
    from filinglens import db
    with db.connect() as conn:
        status, attempts, err = conn.execute("SELECT status, attempts, last_error FROM jobs").fetchone()
    assert (status, attempts) == ("dead", 3) and "503" in err


def test_success_after_a_failure(q, monkeypatch):
    attempts = []

    def once_flaky(p):
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError("network")
        return {"ok": True}

    monkeypatch.setitem(q.HANDLERS, "once_flaky", once_flaky)
    q.enqueue("once_flaky", {}, "o1")
    while q.run_one("w"):
        pass
    assert q.status() == [("once_flaky", "done", 1)]


def test_crashed_worker_job_is_reclaimed_after_timeout(q, monkeypatch):
    q.enqueue("noop", {}, "c1")
    monkeypatch.setattr(q, "VISIBILITY_TIMEOUT_S", -1)  # lock already expired
    first = q.claim("dies")
    assert first is not None
    second = q.claim("rescuer")
    assert second is not None and second["id"] == first["id"] and second["attempts"] == 2
