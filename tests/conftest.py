from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_execution_queue
from app.domain.models import Base
from app.infrastructure.database import get_session
from app.main import app


class FakeQueue:
    def __init__(self) -> None:
        self.execution_ids: list[str] = []

    def enqueue(self, execution_id: str) -> None:
        self.execution_ids.append(execution_id)

    def ping(self) -> bool:
        return True


@pytest.fixture
def session_factory(tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    with session_factory() as database_session:
        yield database_session


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    queue = FakeQueue()

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as database_session:
            yield database_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_execution_queue] = lambda: queue
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
