"""Synchronous SQLAlchemy sessions for synchronous API handlers and workers."""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        get_settings().database_url.get_secret_value(), pool_pre_ping=True
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    # Callers explicitly commit; closing rolls back any unfinished transaction.
    with get_session_factory()() as session:
        yield session

