"""
db/session.py
PostgreSQL connection, session factory, and helpers.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from db.models import Base
from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,       # drops stale connections automatically
    pool_size=5,
    max_overflow=10,
    echo=(settings.LOG_LEVEL == "DEBUG"),
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_tables() -> None:
    """Create all tables if they don't exist. Called on startup."""
    logger.info("Running create_tables()...")
    Base.metadata.create_all(bind=engine)
    logger.info("All tables are ready.")


def check_connection() -> bool:
    """Sanity check: verify DB is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection OK.")
        return True
    except Exception as e:
        logger.error(f"Database connection FAILED: {e}")
        return False


# ---------------------------------------------------------------------------
# Session dependency (use in FastAPI routes and services)
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a DB session and ensures cleanup.

    Usage in a route:
        def my_route(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """
    Context manager for use outside FastAPI (e.g. bot handlers, services).

    Usage:
        with db_session() as db:
            user = db.query(User).filter_by(telegram_id=tid).first()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
