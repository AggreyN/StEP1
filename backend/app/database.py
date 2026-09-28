"""SQLAlchemy engine, session factory, declarative Base, and the get_db dependency."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config

# pool_pre_ping: RDS failovers and idle timeouts silently kill pooled
# connections; pre-ping replaces a dead one instead of erroring the request.
# TLS needs no code — append `?sslmode=require` to DATABASE_URL.
engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=config.DB_POOL_SIZE,
    max_overflow=config.DB_MAX_OVERFLOW,
    pool_recycle=1800,  # under RDS's default idle-connection timeout
    connect_args={
        "connect_timeout": config.DB_CONNECT_TIMEOUT,
        # Timestamps come back in the session's zone. Pin it, or the same
        # instant reads as -04:00 on a laptop and +00:00 on the server.
        "options": "-c timezone=utc",
    },
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Yield a request-scoped session, guaranteed to close afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
