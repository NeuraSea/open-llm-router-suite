from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from enterprise_llm_proxy.config import AppSettings


def create_engine_from_settings(settings: AppSettings) -> Engine:
    if not settings.database_url:
        raise ValueError("ENTERPRISE_LLM_PROXY_DATABASE_URL is required")
    return create_engine(settings.database_url, echo=settings.sqlalchemy_echo)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
