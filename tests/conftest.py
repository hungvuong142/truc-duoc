import pytest
import streamlit as st
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import init_db, make_engine


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point app.db's engine/session factories (both the read/write engine
    and the read-only one) at the same throwaway SQLite file for the
    duration of one test, so repository tests never touch data/app.db."""
    db_path = tmp_path / "test.db"
    test_engine = make_engine(db_path)
    test_read_engine = make_engine(db_path, readonly=True)
    test_session_local = sessionmaker(bind=test_engine, expire_on_commit=False)
    test_read_session_local = sessionmaker(bind=test_read_engine, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "read_engine", test_read_engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_local)
    monkeypatch.setattr(db_module, "ReadSessionLocal", test_read_session_local)

    init_db()
    # repository's @st.cache_data getters are process-global; without this,
    # a getter called (with the same args) by an earlier test against a
    # different temp_db could leak its cached result into this one.
    st.cache_data.clear()
    yield test_engine
