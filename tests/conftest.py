import pytest
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import init_db, make_engine


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point app.db's engine/session factory at a throwaway SQLite file for
    the duration of one test, so repository tests never touch data/app.db."""
    test_engine = make_engine(tmp_path / "test.db")
    test_session_local = sessionmaker(bind=test_engine, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_local)

    init_db()
    yield test_engine
