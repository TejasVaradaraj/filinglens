"""API keys and per-key rate limits.

    python -m filinglens.auth create "tejasvi laptop" [--per-minute 20] [--daily-usd 1.00]
    python -m filinglens.auth list
    python -m filinglens.auth revoke <key_id>

Keys look like `flk_<id>_<secret>`. Only a SHA-256 hash of the secret is stored, so a
database leak doesn't leak working keys; the full key is shown once at creation.
Limits per key: requests per minute (sliding window, counted in Postgres so they hold across
API processes) and a daily spend cap in USD.

Auth is off unless FL_REQUIRE_API_KEY=1, so local development keeps working without keys.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import secrets

from filinglens import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    secret_hash  TEXT NOT NULL,
    per_minute   INT NOT NULL DEFAULT 20,
    daily_usd    DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    revoked      BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS api_usage (
    key_id   TEXT NOT NULL REFERENCES api_keys(id),
    at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS api_usage_key_time ON api_usage (key_id, at);
"""


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def required() -> bool:
    return os.getenv("FL_REQUIRE_API_KEY", "0") == "1"


def init() -> None:
    with db.connect() as conn:
        conn.execute(SCHEMA)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def create(name: str, per_minute: int = 20, daily_usd: float = 1.0) -> str:
    init()
    key_id, secret = secrets.token_hex(4), secrets.token_urlsafe(24)
    with db.connect() as conn:
        conn.execute("INSERT INTO api_keys (id, name, secret_hash, per_minute, daily_usd) VALUES (%s, %s, %s, %s, %s)",
                     (key_id, name, _hash(secret), per_minute, daily_usd))
    return f"flk_{key_id}_{secret}"


def check(key: str | None) -> str:
    """Validate a key and its limits; returns the key id. Raises AuthError(401/429)."""
    if not key or not key.startswith("flk_") or key.count("_") < 2:
        raise AuthError(401, "missing or malformed API key (send header X-API-Key: flk_...)")
    _, key_id, secret = key.split("_", 2)
    with db.connect() as conn:
        row = conn.execute("SELECT secret_hash, per_minute, daily_usd, revoked FROM api_keys WHERE id = %s",
                           (key_id,)).fetchone()
        if not row or row[3] or not hmac.compare_digest(row[0], _hash(secret)):
            raise AuthError(401, "invalid or revoked API key")
        per_minute, daily_usd = row[1], row[2]
        recent, spent = conn.execute(
            """SELECT count(*) FILTER (WHERE at > now() - interval '1 minute'),
                      coalesce(sum(cost_usd) FILTER (WHERE at > now() - interval '1 day'), 0)
               FROM api_usage WHERE key_id = %s""", (key_id,)).fetchone()
        if recent >= per_minute:
            raise AuthError(429, f"rate limit: {per_minute} requests per minute")
        if spent >= daily_usd:
            raise AuthError(429, f"daily spend cap reached (${daily_usd:.2f})")
    return key_id


def record(key_id: str, cost_usd: float) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO api_usage (key_id, cost_usd) VALUES (%s, %s)", (key_id, cost_usd))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("name")
    c.add_argument("--per-minute", type=int, default=20)
    c.add_argument("--daily-usd", type=float, default=1.0)
    sub.add_parser("list")
    r = sub.add_parser("revoke")
    r.add_argument("key_id")
    args = ap.parse_args()
    init()
    if args.cmd == "create":
        print("API key (shown once, store it now):", create(args.name, args.per_minute, args.daily_usd))
    elif args.cmd == "list":
        with db.connect() as conn:
            for row in conn.execute("SELECT id, name, per_minute, daily_usd, revoked, created_at FROM api_keys ORDER BY created_at"):
                print(*row)
    else:
        with db.connect() as conn:
            conn.execute("UPDATE api_keys SET revoked = true WHERE id = %s", (args.key_id,))
        print("revoked", args.key_id)


if __name__ == "__main__":
    main()
