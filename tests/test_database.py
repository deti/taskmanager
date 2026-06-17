import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from taskmanager.database import get_db
from taskmanager.models import Base, Task


@pytest.fixture(scope="module")
def mem_engine():
    _engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(_engine)
    yield _engine
    _engine.dispose()


def test_engine_creation():
    _engine = create_engine("sqlite:///:memory:")
    assert _engine is not None
    _engine.dispose()


def test_table_creation():
    _engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(_engine)
    assert "tasks" in inspect(_engine).get_table_names()
    _engine.dispose()


def test_get_db_yields_session(mem_engine):
    with get_db(mem_engine) as session:
        assert isinstance(session, Session)


def _add_and_raise(engine, task_name: str) -> None:
    with get_db(engine) as session:
        session.add(Task(id=uuid.uuid4(), name=task_name, command="echo roll"))
        raise ValueError("intentional")


def test_get_db_rollback_on_error(mem_engine):
    task_name = "rollback-task-" + str(uuid.uuid4())

    with pytest.raises(ValueError, match="intentional"):
        _add_and_raise(mem_engine, task_name)

    with get_db(mem_engine) as session:
        result = session.query(Task).filter_by(name=task_name).first()
        assert result is None


def test_name_unique_constraint(mem_engine):
    unique_name = "unique-" + str(uuid.uuid4())

    with get_db(mem_engine) as session:
        session.add(Task(id=uuid.uuid4(), name=unique_name, command="echo 1"))

    with pytest.raises(IntegrityError), get_db(mem_engine) as session:
        session.add(Task(id=uuid.uuid4(), name=unique_name, command="echo 2"))


def test_timestamps_auto_populate(mem_engine):
    with get_db(mem_engine) as session:
        task = Task(id=uuid.uuid4(), name="ts-" + str(uuid.uuid4()), command="echo ts")
        session.add(task)
        session.flush()
        assert isinstance(task.created_at, datetime)
        assert isinstance(task.updated_at, datetime)


def test_task_description_nullable(mem_engine):
    with get_db(mem_engine) as session:
        task = Task(id=uuid.uuid4(), name="no-desc-" + str(uuid.uuid4()), command="echo x")
        session.add(task)
        session.flush()
        assert task.description is None


def test_task_shell_default(mem_engine):
    with get_db(mem_engine) as session:
        task = Task(id=uuid.uuid4(), name="shell-" + str(uuid.uuid4()), command="echo x")
        session.add(task)
        session.flush()
        assert task.shell == "/bin/sh"
