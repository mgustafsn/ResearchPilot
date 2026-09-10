import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from researchpilot.api import create_app
from researchpilot.papers import ProviderError, SearchResult
from researchpilot.providers.openalex import normalize_work
from researchpilot.search_persistence import PaperRow, ProjectPaperRow, SearchRunRow

WORK = json.loads((Path(__file__).parent / "fixtures/openalex_work.json").read_text())
DATA = {
    "title": "Research",
    "researchQuestion": "large language models",
    "keywords": ["software engineering"],
    "yearFrom": 2021,
    "yearTo": 2026,
    "maxPaperCount": 25,
}


class RecordingProvider:
    name = "Test scholarly provider"

    def __init__(self):
        self.calls = []
        self.error = None
        self.papers = [normalize_work(WORK)]

    async def search(self, parameters):
        self.calls.append(parameters)
        if self.error:
            raise self.error
        return SearchResult(papers=self.papers, totalFound=len(self.papers))


@pytest.fixture
def search_client(engine):
    provider = RecordingProvider()
    with TestClient(create_app(engine, provider)) as client:
        project = client.post("/api/projects", json=DATA).json()
        yield client, provider, f"/api/projects/{project['id']}"


def test_search_persists_real_metadata_and_snapshot(search_client, engine):
    client, provider, url = search_client
    response = client.post(url + "/search")
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "COMPLETED"
    assert run["parameters"] == {
        "query": DATA["researchQuestion"],
        "yearFrom": 2021,
        "yearTo": 2026,
        "maxPaperCount": 25,
    }
    assert run["keywords"] == DATA["keywords"]
    assert run["paperCount"] == 1
    assert run["duplicateCount"] == 0
    assert run["startedAt"] and run["finishedAt"]
    papers = client.get(url + "/papers").json()
    assert papers[0]["title"] == WORK["title"]
    assert papers[0]["sourceId"] == WORK["id"]
    assert client.get(url).json()["status"] == "COMPLETED"
    assert client.get(url + "/searches").json()[0] == run
    with TestClient(create_app(engine, provider)) as restarted:
        assert restarted.get(url + "/papers").json() == papers
    assert 0 <= papers[0]["relevanceScore"] <= 1


def test_repeated_search_and_shared_papers(search_client, engine):
    client, provider, url = search_client
    for _ in range(2):
        assert client.post(url + "/search").status_code == 200
    other = client.post("/api/projects", json=DATA).json()["id"]
    assert client.post(f"/api/projects/{other}/search").status_code == 200
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PaperRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectPaperRow)) == 2
    assert len(client.get(url + "/searches").json()) == 2
    assert client.delete(url).status_code == 204
    assert len(client.get(f"/api/projects/{other}/papers").json()) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SearchRunRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectPaperRow)) == 1


def test_search_deduplicates_ranks_and_persists_counts(search_client):
    client, provider, url = search_client
    relevant = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W100",
            "doi": "https://doi.org/10.1000/shared",
            "title": "Large language models for software engineering",
        }
    )
    duplicate = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W101",
            "doi": "https://doi.org/10.1000/SHARED",
            "title": "A less complete duplicate",
            "abstract_inverted_index": None,
        }
    )
    unrelated = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W102",
            "doi": "https://doi.org/10.1000/other",
            "title": "Marine biology observations",
            "abstract_inverted_index": None,
            "cited_by_count": 0,
        }
    )
    provider.papers = [unrelated, duplicate, relevant]
    response = client.post(url + "/search")
    assert response.status_code == 200
    assert response.json()["duplicateCount"] == 1
    assert response.json()["paperCount"] == 2
    papers = client.get(url + "/papers").json()
    assert [item["doi"] for item in papers] == ["10.1000/shared", "10.1000/other"]
    assert papers[0]["relevanceScore"] > papers[1]["relevanceScore"]


def test_failure_preserves_previous_results(search_client):
    client, provider, url = search_client
    client.post(url + "/search")
    original = client.get(url + "/papers").json()
    provider.error = ProviderError("RATE_LIMITED")
    assert client.post(url + "/search").status_code == 503
    assert client.get(url + "/papers").json() == original
    history = client.get(url + "/searches").json()
    assert history[0]["status"] == "FAILED"
    assert history[0]["errorCode"] == "RATE_LIMITED"
    assert history[1]["status"] == "COMPLETED"
    assert client.get(url).json()["status"] == "FAILED"
    provider.error = None
    assert client.post(url + "/search").status_code == 200


def test_successful_empty_search_replaces_previous_results(search_client):
    client, provider, url = search_client
    client.post(url + "/search")
    provider.papers = []
    response = client.post(url + "/search")
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["paperCount"] == 0
    assert client.get(url + "/papers").json() == []


def test_search_in_progress_blocks_mutations_and_recovers(search_client, engine):
    client, provider, url = search_client
    project_id = client.get(url).json()["id"]
    from uuid import UUID

    run = client.app.state.search.start(UUID(project_id))
    assert client.get(url).json()["status"] == "SEARCHING"
    assert client.get(url + "/searches").json()[0]["status"] == "SEARCHING"
    assert client.post(url + "/search").status_code == 409
    assert client.put(url, json=DATA).status_code == 409
    assert client.delete(url).status_code == 409
    assert provider.calls == []
    with Session(engine) as session, session.begin():
        row = session.get(SearchRunRow, run.id)
        row.startedAt = datetime.now(UTC) - timedelta(minutes=3)
    history = client.get(url + "/searches").json()
    assert history[0]["errorCode"] == "INTERRUPTED"
    assert client.get(url).json()["status"] == "FAILED"
    assert client.post(url + "/search").status_code == 200
    from researchpilot.search_persistence import SearchConflict

    with pytest.raises(SearchConflict):
        client.app.state.search.finish(run, result=SearchResult(papers=[], totalFound=0))
    assert len(client.get(url + "/papers").json()) == 1


def test_missing_project_never_calls_provider(search_client):
    client, provider, _ = search_client
    url = f"/api/projects/{uuid4()}"
    for method, suffix in [("post", "/search"), ("get", "/papers"), ("get", "/searches")]:
        assert getattr(client, method)(url + suffix).status_code == 404
        assert getattr(client, method)("/api/projects/bad-id" + suffix).status_code == 422
    assert provider.calls == []


def test_default_limit_and_snapshot_survives_edit(search_client):
    client, provider, url = search_client
    client.put(url, json={"title": "A", "researchQuestion": "B"})
    assert client.post(url + "/search").status_code == 200
    assert provider.calls[0].maxPaperCount == 100
    assert provider.calls[0].yearFrom is None
    client.put(url, json={"title": "A", "researchQuestion": "Changed"})
    assert client.get(url + "/searches").json()[0]["researchQuestion"] == "B"


def test_timeout_persists_failure(search_client, monkeypatch):
    client, provider, url = search_client

    async def slow(parameters):
        await asyncio.sleep(1)

    provider.search = slow
    monkeypatch.setattr("researchpilot.search.SEARCH_TIMEOUT_SECONDS", 0.01)
    assert client.post(url + "/search").status_code == 504
    assert client.get(url).json()["status"] == "FAILED"
    assert client.get(url + "/searches").json()[0]["errorCode"] == "TIMEOUT"


def test_unexpected_error_is_sanitized(search_client):
    client, provider, url = search_client
    provider.error = RuntimeError("secret-key-should-not-leak")
    response = client.post(url + "/search")
    assert response.status_code == 502
    assert "secret-key" not in response.text
    assert "secret-key" not in client.get(url + "/searches").text


def test_postgres_concurrent_search_start(search_client, engine):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production row locking requires PostgreSQL")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import UUID
    from researchpilot.search_persistence import SearchConflict

    client, provider, url = search_client
    project_id = UUID(client.get(url).json()["id"])
    barrier = Barrier(2)

    def start():
        barrier.wait()
        try:
            client.app.state.search.start(project_id)
            return "started"
        except SearchConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start) for _ in range(2)]
        assert sorted(future.result() for future in futures) == ["conflict", "started"]
