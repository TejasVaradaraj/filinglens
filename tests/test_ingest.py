"""Ingestion against a separate local test database (never the dev database).

The tests create `filinglens_test` on the docker-compose server if needed and
point config.DATABASE_URL at it, so they can't touch real data. Skipped if
Postgres isn't running.
"""
import pytest

from filinglens import config

DOC = "PEPSICO_2023_8K_dated-2023-05-05"  # 5 pages: quick
TEST_DB = "filinglens_test"


@pytest.fixture
def conn(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    if not (config.FINANCEBENCH_DIR / "pdfs").exists():
        pytest.skip("FinanceBench not downloaded")
    base = config.DATABASE_URL
    try:
        admin = psycopg.connect(base, connect_timeout=2, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (docker compose up -d)")
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone():
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    test_url = base.rsplit("/", 1)[0] + f"/{TEST_DB}"
    assert test_url != base
    monkeypatch.setattr(config, "DATABASE_URL", test_url)
    c = psycopg.connect(test_url)
    yield c
    c.close()


def counts(conn):
    conn.commit()  # see rows written by other connections
    return conn.execute(
        """SELECT f.id, (SELECT count(*) FROM pages p WHERE p.filing_id = f.id),
                  (SELECT count(*) FROM tables t WHERE t.filing_id = f.id)
           FROM filings f WHERE doc_name = %s""", (DOC,)).fetchall()


def test_ingest_twice_creates_no_duplicates(conn):
    from filinglens.ingest import ingest
    ingest([DOC], force=True)
    first = counts(conn)
    result = ingest([DOC])
    assert result["skipped"] == 1 and result["ingested"] == 0
    assert counts(conn) == first and len(first) == 1


def test_forced_reingest_replaces_rows(conn):
    from filinglens.ingest import ingest
    ingest([DOC], force=True)
    (_, pages1, tables1), = counts(conn)
    ingest([DOC], force=True)
    (_, pages2, tables2), = counts(conn)
    assert (pages1, tables1) == (pages2, tables2) == (5, tables1)
