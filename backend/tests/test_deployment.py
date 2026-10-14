import base64

import pytest
from fastapi.testclient import TestClient
from fakes import DATA, RecordingEmbeddingProvider, RecordingLlmProvider, RecordingProvider

from researchpilot.api import create_app
from researchpilot.config import database_url


def test_heroku_database_url_uses_psycopg_and_ssl(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:password@database.example/researchpilot")
    monkeypatch.setenv("DYNO", "web.1")

    url = database_url()

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "database.example"
    assert url.query["sslmode"] == "require"


def test_local_database_url_does_not_force_ssl(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:password@localhost/db")
    monkeypatch.delenv("DYNO", raising=False)

    assert "sslmode" not in database_url().query


def test_heroku_requires_password(engine, monkeypatch):
    monkeypatch.setenv("DYNO", "web.1")
    monkeypatch.delenv("RESEARCHPILOT_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="RESEARCHPILOT_PASSWORD"):
        create_app(engine)


def test_private_access_covers_pages_api_and_writes(engine, monkeypatch):
    monkeypatch.setenv("DYNO", "web.1")
    monkeypatch.setenv("RESEARCHPILOT_PASSWORD", "a-long-private-password")
    auth = "Basic " + base64.b64encode(b"researchpilot:a-long-private-password").decode()
    headers = {"X-Forwarded-Proto": "https"}

    with TestClient(create_app(engine), base_url="https://example.test") as client:
        assert client.get("/", headers=headers).status_code == 401
        assert client.get("/api/projects", headers=headers).status_code == 401
        assert client.get("/docs", headers=headers).status_code == 401
        assert client.get("/static/app.js", headers=headers).status_code == 401
        non_ascii = "Basic " + base64.b64encode("résearchpilot:wrong".encode()).decode()
        assert (
            client.get("/api/projects", headers={**headers, "Authorization": non_ascii}).status_code
            == 401
        )
        assert client.get("/api/projects", headers={**headers, "Authorization": auth}).json() == []

        response = client.post(
            "/api/projects",
            headers={**headers, "Authorization": auth, "Origin": "https://other.example"},
            json={"title": "Blocked", "researchQuestion": "Example"},
        )
        assert response.status_code == 403

        response = client.post(
            "/api/projects",
            headers={**headers, "Authorization": auth, "Origin": "https://example.test"},
            json={"title": "Allowed", "researchQuestion": "Example"},
        )
        assert response.status_code == 201


def test_heroku_redirects_http_before_auth(engine, monkeypatch):
    monkeypatch.setenv("DYNO", "web.1")
    monkeypatch.setenv("RESEARCHPILOT_PASSWORD", "a-long-private-password")

    with TestClient(create_app(engine), base_url="http://example.test") as client:
        response = client.get("/", headers={"X-Forwarded-Proto": "http"}, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://example.test/"


def test_hosted_search_returns_accepted_and_persists_result(engine, monkeypatch):
    monkeypatch.setenv("DYNO", "web.1")
    monkeypatch.setenv("RESEARCHPILOT_PASSWORD", "a-long-private-password")
    auth = "Basic " + base64.b64encode(b"researchpilot:a-long-private-password").decode()
    headers = {
        "Authorization": auth,
        "X-Forwarded-Proto": "https",
        "Origin": "https://example.test",
    }
    app = create_app(
        engine, RecordingProvider(), RecordingEmbeddingProvider(), RecordingLlmProvider()
    )

    with TestClient(app, base_url="https://example.test") as client:
        project = client.post("/api/projects", headers=headers, json=DATA).json()
        response = client.post(f"/api/projects/{project['id']}/search", headers=headers)
        history = client.get(f"/api/projects/{project['id']}/searches", headers=headers).json()

    assert response.status_code == 202
    assert response.json()["status"] == "SEARCHING"
    assert history[0]["status"] == "COMPLETED"
