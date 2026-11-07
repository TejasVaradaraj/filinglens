"""API keys and limits against the separate filinglens_test database."""
import pytest
from fastapi.testclient import TestClient

from filinglens import config
from filinglens.systems.base import SystemAnswer

TEST_DB = "filinglens_test"


@pytest.fixture
def client(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(config.DATABASE_URL, connect_timeout=2, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running")
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone():
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setattr(config, "DATABASE_URL", config.DATABASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB}")
    monkeypatch.setenv("FL_REQUIRE_API_KEY", "1")
    from filinglens import api, auth, db
    auth.init()
    with db.connect() as conn:
        conn.execute("TRUNCATE api_usage, api_keys")
    monkeypatch.setattr(api.system, "answer", lambda q, emit=None: SystemAnswer("ok", 0.4))
    return TestClient(api.app), auth


def test_missing_and_bad_keys_are_rejected(client):
    c, auth = client
    assert c.post("/ask", json={"question": "what was revenue?"}).status_code == 401
    assert c.post("/ask", json={"question": "what was revenue?"}, headers={"X-API-Key": "flk_x_y"}).status_code == 401


def test_valid_key_and_rate_limit(client):
    c, auth = client
    key = auth.create("test", per_minute=2, daily_usd=100)
    h = {"X-API-Key": key}
    assert c.post("/ask", json={"question": "what was revenue?"}, headers=h).status_code == 200
    assert c.post("/ask", json={"question": "what was revenue?"}, headers=h).status_code == 200
    r = c.post("/ask", json={"question": "what was revenue?"}, headers=h)
    assert r.status_code == 429 and "per minute" in r.json()["detail"]


def test_daily_spend_cap(client):
    c, auth = client
    key = auth.create("test", per_minute=100, daily_usd=0.5)
    h = {"X-API-Key": key}
    assert c.post("/ask", json={"question": "what was revenue?"}, headers=h).status_code == 200   # spends 0.4
    assert c.post("/ask", json={"question": "what was revenue?"}, headers=h).status_code == 200   # 0.8 total
    r = c.post("/ask", json={"question": "what was revenue?"}, headers=h)
    assert r.status_code == 429 and "spend cap" in r.json()["detail"]


def test_revoked_key(client):
    c, auth = client
    key = auth.create("test")
    from filinglens import db
    with db.connect() as conn:
        conn.execute("UPDATE api_keys SET revoked = true")
    assert c.post("/ask", json={"question": "what was revenue?"}, headers={"X-API-Key": key}).status_code == 401


def test_only_hash_is_stored(client):
    c, auth = client
    key = auth.create("test")
    from filinglens import db
    with db.connect() as conn:
        stored = conn.execute("SELECT secret_hash FROM api_keys").fetchone()[0]
    assert key.split("_", 2)[2] not in stored and len(stored) == 64
