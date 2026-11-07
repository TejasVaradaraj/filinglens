"""Ingestion against the real local database (skipped if Postgres isn't running)."""
import pytest

from filinglens import config

DOC = "PEPSICO_2023_8K_dated-2023-05-05"  # 5 pages: quick


@pytest.fixture
def conn():
    psycopg = pytest.importorskip("psycopg")
    if not (config.FINANCEBENCH_DIR / "pdfs").exists():
        pytest.skip("FinanceBench not downloaded")
    try:
        c = psycopg.connect(config.DATABASE_URL, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (docker compose up -d)")
    yield c
    c.close()


def counts(conn):
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
