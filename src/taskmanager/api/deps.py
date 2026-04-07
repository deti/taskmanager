"""FastAPI dependency injection utilities.

This module provides dependency injection functions for FastAPI route handlers,
primarily for database session management.
"""

from collections.abc import Iterator

from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import get_engine


def get_db() -> Iterator[Session]:
    """Yield a SQLAlchemy session for FastAPI dependency injection.

    This generator function creates a new database session for each request
    and ensures proper cleanup after the request completes. The session is
    automatically committed on success or rolled back on exception.

    Usage in FastAPI routes:
        @app.get("/items")
        def list_items(db: Session = Depends(get_db)):
            return db.query(Item).all()

    Yields:
        Session: A SQLAlchemy session bound to the application's database engine.

    Notes:
        - The session is created fresh for each request
        - Successful requests trigger an automatic commit
        - Exceptions trigger an automatic rollback
        - The session is always closed in the finally block
    """
    engine = get_engine()
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
