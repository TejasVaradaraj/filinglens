"""Database access. `python -m filinglens.db` creates the schema."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import psycopg

from filinglens import config

SCHEMA = Path(__file__).with_name("schema.sql")


@contextmanager
def connect():
    """A connection that commits on success and rolls back on error."""
    with psycopg.connect(config.DATABASE_URL) as conn:
        yield conn


def init_schema() -> None:
    with connect() as conn:
        conn.execute(SCHEMA.read_text())

