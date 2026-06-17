import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from taskmanager.models import Base


@pytest.fixture(scope="session")
def engine():
    _engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(_engine)
    yield _engine
    _engine.dispose()


@pytest.fixture
def db_session(engine):
    session = Session(engine)
    yield session
    session.rollback()
    session.close()
