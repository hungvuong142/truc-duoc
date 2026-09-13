"""Engine/session setup for the app database.

Defaults to a local SQLite file (zero setup for local dev). If a
`DATABASE_URL` secret/env var is set, connects to that instead (Postgres in
production, e.g. Supabase) so data survives redeploys on Streamlit Community
Cloud, whose container filesystem is ephemeral.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import DB_PATH
from app.models import Base


def _resolve_database_url() -> str | None:
    try:
        import streamlit as st

        url = st.secrets.get("DATABASE_URL")
        if url:
            return url
    except Exception:
        pass
    return os.environ.get("DATABASE_URL") or None


def make_engine(db_path: Path = DB_PATH, database_url: str | None = None):
    if database_url:
        return create_engine(database_url, pool_pre_ping=True)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = make_engine(database_url=_resolve_database_url())
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _ensure_column(table: str, column: str, ddl_type: str, default_sql: str) -> None:
    """`Base.metadata.create_all` only creates missing tables, not columns
    added to a model after the DB already has data. This adds one column
    if it isn't there yet -- a minimal stand-in for a real migration tool,
    reasonable at this project's scale (SQLite, no Alembic). Uses
    `inspect()` rather than SQLite's `PRAGMA table_info` so it also works
    against Postgres."""
    existing = {col["name"] for col in inspect(engine).get_columns(table)}
    if column not in existing:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type} DEFAULT {default_sql}"))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _ensure_column("assignments", "is_half_day", "BOOLEAN", "FALSE")


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
