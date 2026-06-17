from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.settings import get_settings


def create_db_engine() -> Engine:
    return create_engine(get_settings().db_url)


@contextmanager
def get_db(engine: Engine | None = None) -> Generator[Session, None, None]:
    if engine is None:
        engine = create_db_engine()
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
