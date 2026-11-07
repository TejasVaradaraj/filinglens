"""A Postgres-backed job queue for bulk ingestion.

    python -m filinglens.jobs enqueue-edgar AAPL --company Apple --forms 10-K 10-Q --limit 4
    python -m filinglens.jobs worker [--once] [--concurrency 2]
    python -m filinglens.jobs status

Why Postgres and not Redis + RQ/Celery: no new infrastructure, and a job's state change
commits in the same database as the data it produces. The pattern:
- enqueue with an idempotency key: the same work enqueued twice is one job;
- claim with `FOR UPDATE SKIP LOCKED`: parallel workers never take the same job;
- a visibility timeout (`locked_until`): a job whose worker died is claimed again;
- retries with exponential backoff, then status 'dead' (the dead-letter queue) with the error;
- chaining: a finished ingest job enqueues chunk+embed for that filing.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import time
import traceback
from typing import Callable

from psycopg.types.json import Jsonb

from filinglens import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL,
    payload         JSONB NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | dead
    attempts        INT NOT NULL DEFAULT 0,
    max_attempts    INT NOT NULL DEFAULT 4,
    run_after       TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by       TEXT,
    locked_until    TIMESTAMPTZ,
    last_error      TEXT,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_claimable ON jobs (status, run_after);
"""

VISIBILITY_TIMEOUT_S = 900   # a running job not finished in 15 min is assumed dead and re-claimable
BACKOFF_BASE_S = 30          # retry after 30 s, 60 s, 120 s, ...

HANDLERS: dict[str, Callable[[dict], dict]] = {}


def handler(kind: str):
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


def init() -> None:
    with db.connect() as conn:
        conn.execute(SCHEMA)


def enqueue(kind: str, payload: dict, key: str, max_attempts: int = 4) -> int | None:
    """Add a job; returns its id, or None if a job with this idempotency key already exists."""
    with db.connect() as conn:
        row = conn.execute(
            """INSERT INTO jobs (kind, payload, idempotency_key, max_attempts) VALUES (%s, %s, %s, %s)
               ON CONFLICT (idempotency_key) DO NOTHING RETURNING id""",
            (kind, Jsonb(payload), key, max_attempts)).fetchone()
    return row[0] if row else None


def claim(worker: str) -> dict | None:
    """Atomically take the oldest runnable job (queued and due, or running past its timeout)."""
    with db.connect() as conn:
        row = conn.execute(
            """UPDATE jobs SET status = 'running', attempts = attempts + 1, locked_by = %s,
                      locked_until = now() + make_interval(secs => %s), updated_at = now()
               WHERE id = (
                   SELECT id FROM jobs
                   WHERE (status = 'queued' AND run_after <= now())
                      OR (status = 'running' AND locked_until < now())
                   ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
               RETURNING id, kind, payload, attempts, max_attempts""",
            (worker, VISIBILITY_TIMEOUT_S)).fetchone()
    if not row:
        return None
    return dict(zip(["id", "kind", "payload", "attempts", "max_attempts"], row))


def complete(job_id: int, result: dict) -> None:
    with db.connect() as conn:
        conn.execute("""UPDATE jobs SET status = 'done', result = %s, locked_by = NULL, locked_until = NULL,
                        last_error = NULL, updated_at = now() WHERE id = %s""", (Jsonb(result), job_id))


def fail(job: dict, error: str) -> str:
    """Retry later with exponential backoff, or move to the dead-letter state."""
    dead = job["attempts"] >= job["max_attempts"]
    delay = BACKOFF_BASE_S * 2 ** (job["attempts"] - 1)
    with db.connect() as conn:
        conn.execute(
            """UPDATE jobs SET status = %s, last_error = %s, locked_by = NULL, locked_until = NULL,
                      run_after = now() + make_interval(secs => %s), updated_at = now() WHERE id = %s""",
            ("dead" if dead else "queued", error[-4000:], delay, job["id"]))
    return "dead" if dead else "queued"


def run_one(worker: str) -> bool:
    """Claim and run one job. Returns False if there was nothing to do."""
    job = claim(worker)
    if job is None:
        return False
    fn = HANDLERS.get(job["kind"])
    try:
        if fn is None:
            raise KeyError(f"no handler for job kind {job['kind']!r}")
        result = fn(job["payload"])
        complete(job["id"], result or {})
        print(f"[{worker}] job {job['id']} {job['kind']} done: {json.dumps(result)[:160]}", flush=True)
    except Exception as exc:
        state = fail(job, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}")
        print(f"[{worker}] job {job['id']} {job['kind']} failed (attempt {job['attempts']}/"
              f"{job['max_attempts']}) -> {state}: {exc}", flush=True)
    return True


def worker_loop(once: bool = False, concurrency: int = 1, idle_sleep: float = 2.0) -> None:
    init()
    base = f"{socket.gethostname()}:{os.getpid()}"

    def loop(n):
        name = f"{base}:{n}"
        while True:
            did = run_one(name)
            if not did:
                if once:
                    return
                time.sleep(idle_sleep)

    threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def status() -> list[tuple]:
    with db.connect() as conn:
        return conn.execute("SELECT kind, status, count(*) FROM jobs GROUP BY 1, 2 ORDER BY 1, 2").fetchall()


# --- Handlers -------------------------------------------------------------------------

@handler("ingest_edgar")
def _ingest_edgar(p: dict) -> dict:
    from filinglens.edgar import EdgarClient, FilingRef
    from filinglens.ingest import ingest_edgar_filing
    result = ingest_edgar_filing(FilingRef(**p["ref"]), p["company"], EdgarClient())
    if not result.get("skipped"):
        enqueue("index_filing", {"doc_name": result["doc_name"]}, f"index:{result['doc_name']}:{result['sha256'][:16]}")
    return result


@handler("index_filing")
def _index_filing(p: dict) -> dict:
    """Chunk new filings and embed chunks without vectors (small: runs fine on the M1)."""
    from filinglens.retrieval.index import chunk_all, embed_all
    chunked = chunk_all([p["doc_name"]])
    embed_all([p["doc_name"]])
    return {"doc_name": p["doc_name"], **chunked}


@handler("xbrl_refresh")
def _xbrl_refresh(p: dict) -> dict:
    from filinglens import xbrl
    return xbrl.load()


def enqueue_edgar(ticker: str, company: str, forms: list[str], limit: int) -> list[int]:
    from filinglens.edgar import EdgarClient
    init()
    refs = EdgarClient().list_filings(ticker, tuple(forms))[:limit]
    ids = []
    for ref in refs:
        job_id = enqueue("ingest_edgar", {"ref": ref.__dict__, "company": company}, f"edgar:{ref.accession}")
        ids.append(job_id)
        print(f"{'enqueued' if job_id else 'already queued'}: {ref.form} {ref.report_date} {ref.accession}")
    return [i for i in ids if i]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enqueue-edgar")
    e.add_argument("ticker")
    e.add_argument("--company", required=True, help="display name stored on the filings")
    e.add_argument("--forms", nargs="+", default=["10-K", "10-Q"])
    e.add_argument("--limit", type=int, default=4)
    w = sub.add_parser("worker")
    w.add_argument("--once", action="store_true", help="exit when the queue is empty")
    w.add_argument("--concurrency", type=int, default=1)
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "enqueue-edgar":
        enqueue_edgar(args.ticker, args.company, args.forms, args.limit)
    elif args.cmd == "worker":
        worker_loop(args.once, args.concurrency)
    else:
        init()
        for row in status():
            print(*row)


if __name__ == "__main__":
    main()
