from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from enterprise_llm_proxy.repositories.base import Base
from enterprise_llm_proxy.repositories import models  # noqa: F401


DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://router:router@127.0.0.1:55432/router_test"


@pytest.fixture(autouse=True)
def _isolate_from_production_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent unit tests from accidentally connecting to the production database.

    Tests that need Postgres use the ``postgres_database_url`` / ``postgres_session_factory``
    fixtures and pass the URL explicitly to ``create_app``; they do not rely on this env var.
    """
    monkeypatch.setenv("ENTERPRISE_LLM_PROXY_DATABASE_URL", "")


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.environ.get("ENTERPRISE_LLM_PROXY_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL test database is unavailable: {exc}")

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def postgres_session_factory(postgres_engine: Engine) -> sessionmaker[Session]:
    Base.metadata.drop_all(postgres_engine)
    Base.metadata.create_all(postgres_engine)
    return sessionmaker(bind=postgres_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def postgres_database_url(postgres_engine: Engine) -> str:
    Base.metadata.drop_all(postgres_engine)
    Base.metadata.create_all(postgres_engine)
    return postgres_engine.url.render_as_string(hide_password=False)
