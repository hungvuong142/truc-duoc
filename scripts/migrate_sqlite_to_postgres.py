"""One-time (idempotent) data copy: local data/app.db (SQLite) -> Postgres.

Run this once after provisioning a Postgres database (e.g. Supabase), to
carry over existing staff/duty-weight/holiday/assignment data before
deploying. Safe to re-run: rows are upserted (merged) by primary key.

Usage:
    uv run python scripts/migrate_sqlite_to_postgres.py "postgresql://user:pass@host:port/dbname"

If no URL is given as an argument, falls back to the DATABASE_URL env var.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import sessionmaker

from app.config import DB_PATH
from app.db import make_engine
from app.models import Assignment, Base, DutyWeight, Holiday, Staff

# Order matters: staff/duty_weights/holidays have no FK dependency on each
# other, but assignments references staff, so it must come last.
MODELS_IN_FK_ORDER = [Staff, DutyWeight, Holiday, Assignment]


def _copy_table(model, source_session, target_session) -> int:
    rows = source_session.query(model).all()
    count = 0
    for row in rows:
        source_session.expunge(row)
        target_session.merge(row)
        count += 1
    return count


def main() -> None:
    database_url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "Missing target Postgres URL. Pass it as an argument or set DATABASE_URL.\n"
            'Usage: uv run python scripts/migrate_sqlite_to_postgres.py "postgresql://..."'
        )
    if not DB_PATH.exists():
        raise SystemExit(f"Source SQLite database not found at {DB_PATH}.")

    source_engine = make_engine(db_path=DB_PATH)
    target_engine = make_engine(database_url=database_url)
    Base.metadata.create_all(target_engine)

    SourceSession = sessionmaker(bind=source_engine, expire_on_commit=False)
    TargetSession = sessionmaker(bind=target_engine, expire_on_commit=False)

    with SourceSession() as source_session, TargetSession() as target_session:
        for model in MODELS_IN_FK_ORDER:
            count = _copy_table(model, source_session, target_session)
            print(f"Copied {count} row(s) into {model.__tablename__}.")
        target_session.commit()

    print("Done.")


if __name__ == "__main__":
    main()
