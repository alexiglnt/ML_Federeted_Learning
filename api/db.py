"""Database engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from api.config import settings

engine = create_engine(
    settings.database_url,
    # Long-lived connections go stale behind a container restart or a network
    # blip; recycling keeps the first request after an idle period from
    # failing on a dead socket.
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Used as the default for every timestamp column. Naive datetimes are a
    reliable source of off-by-hours bugs once a server and a browser disagree
    about the local zone, so nothing in this codebase stores one.
    """
    return datetime.now(timezone.utc)


# Every timestamp column uses this type, so the tz-awareness above survives the
# round trip through Postgres.
TZDateTime = DateTime(timezone=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
