import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from researchpilot.api import create_app
from researchpilot.persistence import Base


@pytest.fixture
def engine(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    engine = create_engine(url or f"sqlite:///{tmp_path / 'test.db'}")
    if not url:

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    if url:
        with engine.begin() as conn:
            for migration in sorted((Path(__file__).parents[2] / "migrations").glob("*.sql")):
                conn.exec_driver_sql(migration.read_text())
    else:
        Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine)) as client:
        yield client
