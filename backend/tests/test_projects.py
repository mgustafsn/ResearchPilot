import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from researchpilot.api import create_app
from researchpilot.domain import ProjectInput
from researchpilot.persistence import Base


@pytest.fixture
def engine(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    engine = create_engine(url or f"sqlite:///{tmp_path / 'test.db'}")
    if url:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                (Path(__file__).parents[2] / "migrations/001_projects.sql").read_text()
            )
    else:
        Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine)) as client:
        yield client


DATA = {
    "title": "  My project  ",
    "researchQuestion": "  How does testing work?  ",
    "keywords": ["Testing", "testing", " AI "],
    "yearFrom": 2020,
    "yearTo": 2026,
    "maxPaperCount": 100,
}


def test_crud_and_restart(client, engine):
    assert client.get("/api/projects").json() == []
    response = client.post("/api/projects", json=DATA)
    assert response.status_code == 201
    project, url = response.json(), response.headers["location"]
    assert project["title"] == "My project"
    assert project["keywords"] == ["Testing", "AI"]
    assert project["status"] == "CREATED"
    assert client.get(url).json() == project
    with TestClient(create_app(engine)) as restarted:
        assert restarted.get(url).json() == project
    assert len(client.get("/api/projects").json()) == 1
    updated = client.put(url, json={"title": "Changed", "researchQuestion": "New topic"})
    assert updated.status_code == 200
    assert updated.json()["id"] == project["id"]
    assert updated.json()["createdAt"] == project["createdAt"]
    assert updated.json()["updatedAt"] >= project["updatedAt"]
    assert updated.json()["yearFrom"] is None
    assert updated.json()["keywords"] == []
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get("/api/projects").json() == []


@pytest.mark.parametrize(
    "change",
    [
        {"title": " "},
        {"title": "x" * 201},
        {"researchQuestion": " "},
        {"yearFrom": 2027, "yearTo": 2026},
        {"yearFrom": 0},
        {"yearTo": 10000},
        {"maxPaperCount": 0},
        {"maxPaperCount": 1001},
        {"maxPaperCount": True},
        {"yearFrom": 2020.5},
        {"keywords": [" "]},
        {"keywords": ["x" * 101]},
        {"keywords": ["x"] * 31},
        {"status": "COMPLETED"},
        {"id": str(uuid4())},
        {"title": None},
        {"keywords": "testing"},
    ],
)
def test_invalid_input_is_not_persisted(client, change):
    payload = DATA | change
    assert client.post("/api/projects", json=payload).status_code == 422
    assert client.get("/api/projects").json() == []
    project = client.post("/api/projects", json=DATA).json()
    url = f"/api/projects/{project['id']}"
    assert client.put(url, json=payload).status_code == 422
    assert client.get(url).json() == project


def test_missing_and_malformed_ids(client):
    url = f"/api/projects/{uuid4()}"
    assert client.get(url).status_code == 404
    assert client.put(url, json=DATA).status_code == 404
    assert client.delete(url).status_code == 404
    assert client.get("/api/projects/invalid").status_code == 422


def test_optional_fields():
    data = ProjectInput(title="A", researchQuestion="B", yearFrom=2020)
    assert data.yearTo is None
    assert data.maxPaperCount is None
    with pytest.raises(ValidationError):
        ProjectInput(title="A", researchQuestion="B", secret="value")


def test_pages(client):
    for path in [
        "/",
        "/projects/new",
        f"/projects/{uuid4()}",
        f"/projects/{uuid4()}/edit",
        "/static/app.js",
        "/static/styles.css",
    ]:
        assert client.get(path).status_code == 200


def test_database_failure(client, engine):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE research_projects"))
    response = client.get("/api/projects")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable. Try again."}


def test_service_preserves_identity_and_controls_status(engine):
    from sqlalchemy.orm import Session

    from researchpilot.persistence import ProjectRepository
    from researchpilot.service import ProjectNotFound, ProjectService

    with Session(engine) as session, session.begin():
        svc = ProjectService(ProjectRepository(session))
        created = svc.create(ProjectInput(title="Original", researchQuestion="Question"))
        changed = svc.update(created.id, ProjectInput(title="Edited", researchQuestion="New"))
        assert changed.id == created.id
        assert changed.createdAt == created.createdAt
        assert changed.status == "CREATED"
        assert changed.updatedAt >= created.updatedAt
        svc.delete(created.id)
        with pytest.raises(ProjectNotFound):
            svc.get(created.id)


def test_transaction_rolls_back(engine):
    from sqlalchemy.orm import Session

    from researchpilot.persistence import ProjectRepository
    from researchpilot.service import ProjectService

    with pytest.raises(RuntimeError), Session(engine) as session, session.begin():
        ProjectService(ProjectRepository(session)).create(
            ProjectInput(title="A", researchQuestion="B")
        )
        raise RuntimeError("Aborted operation")
    with Session(engine) as session:
        assert ProjectService(ProjectRepository(session)).list() == []
