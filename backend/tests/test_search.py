import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from researchpilot.api import create_app
from researchpilot.llm import ClusterNaming
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


class RecordingEmbeddingProvider:
    name = "Test embedding provider"
    model = "test-embed"
    dimension = 8

    def __init__(self):
        self.batches = []
        self.error = None

    async def embed(self, texts):
        self.batches.append(list(texts))
        if self.error:
            raise self.error
        return [self._vector(text) for text in texts]

    def _vector(self, text):
        for index, marker in enumerate(("alpha", "bravo", "charlie")):
            if marker in text:
                vector = [0.0] * self.dimension
                vector[index] = 10.0
                return vector
        return [1.0] * self.dimension


class RecordingLlmProvider:
    name = "Test LLM provider"
    model = "test-llm"

    def __init__(self):
        self.calls = []
        self.error = None
        self.explain_calls = []
        self.explain_error = None

    async def name_cluster(self, question, papers):
        self.calls.append((question, list(papers)))
        if self.error:
            raise self.error
        marker = (papers[0].title or "topic").split()[0]
        return ClusterNaming(
            name=f"Topic {marker}", description=f"Papers about {marker}.", keywords=[marker.lower()]
        )

    async def explain_paper(self, question, subtopic, paper):
        self.explain_calls.append((question, subtopic, paper))
        if self.explain_error:
            raise self.explain_error
        return f"{paper.title} fits {subtopic}."


@pytest.fixture
def search_client(engine):
    provider = RecordingProvider()
    with TestClient(
        create_app(engine, provider, RecordingEmbeddingProvider(), RecordingLlmProvider())
    ) as client:
        project = client.post("/api/projects", json=DATA).json()
        yield client, provider, f"/api/projects/{project['id']}"


@pytest.fixture
def search_client_with_embedder(engine):
    provider = RecordingProvider()
    embedder = RecordingEmbeddingProvider()
    with TestClient(create_app(engine, provider, embedder, RecordingLlmProvider())) as client:
        project = client.post("/api/projects", json=DATA).json()
        yield client, provider, embedder, f"/api/projects/{project['id']}"


@pytest.fixture
def search_client_named(engine):
    provider = RecordingProvider()
    embedder = RecordingEmbeddingProvider()
    llm = RecordingLlmProvider()
    with TestClient(create_app(engine, provider, embedder, llm)) as client:
        project = client.post("/api/projects", json=DATA).json()
        yield client, provider, embedder, llm, f"/api/projects/{project['id']}"


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
    assert run["clusterCount"] == 1
    assert run["startedAt"] and run["finishedAt"]
    papers = client.get(url + "/papers").json()
    assert papers[0]["title"] == WORK["title"]
    assert papers[0]["sourceId"] == WORK["id"]
    assert papers[0]["clusterId"] == 0
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


def _grouped_papers():
    return [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W1{['alpha', 'bravo', 'charlie'].index(group)}{n}",
                "doi": f"https://doi.org/10.5000/{group}-{n}",
                "title": f"{group} paper {n}",
                "abstract_inverted_index": None,
            }
        )
        for group in ("alpha", "bravo", "charlie")
        for n in range(5)
    ]


def test_search_embeds_and_clusters_papers(search_client_with_embedder):
    client, provider, embedder, url = search_client_with_embedder
    provider.papers = _grouped_papers()
    run = client.post(url + "/search").json()
    assert run["clusterCount"] == 3
    papers = client.get(url + "/papers").json()
    assert {paper["clusterId"] for paper in papers} == {0, 1, 2}
    assert sum(len(batch) for batch in embedder.batches) == 15


def test_embeddings_are_reused_on_a_second_search(search_client_with_embedder):
    client, provider, embedder, url = search_client_with_embedder
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    client.post(url + "/search")
    assert len(embedder.batches) == 1


def test_embedding_failure_preserves_previous_results(search_client_with_embedder):
    client, provider, embedder, url = search_client_with_embedder
    client.post(url + "/search")
    original = client.get(url + "/papers").json()
    embedder.error = ProviderError("EMBEDDING_UNAVAILABLE")
    provider.papers = [normalize_work(WORK | {"id": "https://openalex.org/W999"})]
    assert client.post(url + "/search").status_code == 503
    assert client.get(url + "/papers").json() == original
    history = client.get(url + "/searches").json()
    assert history[0]["status"] == "FAILED"
    assert history[0]["errorCode"] == "EMBEDDING_UNAVAILABLE"


def test_search_names_each_cluster(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    run = client.post(url + "/search").json()
    assert run["clusterCount"] == 3
    assert run["namingError"] is None
    assert len(llm.calls) == 3
    subtopics = client.get(url + "/subtopics").json()
    assert {s["clusterId"] for s in subtopics} == {0, 1, 2}
    by_cluster = {s["clusterId"]: s for s in subtopics}
    for topic in by_cluster.values():
        assert topic["name"].startswith("Topic ")
        assert topic["description"]
        assert topic["keywords"]


def test_naming_failure_completes_search_with_fallback(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    llm.error = ProviderError("LLM_RATE_LIMITED")
    run = client.post(url + "/search").json()
    assert run["status"] == "COMPLETED"
    assert run["clusterCount"] == 3
    assert run["namingError"] == "LLM_RATE_LIMITED"
    assert client.get(url + "/subtopics").json() == []
    assert {p["clusterId"] for p in client.get(url + "/papers").json()} == {0, 1, 2}


def test_subtopics_are_replaced_on_a_new_search(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    assert len(client.get(url + "/subtopics").json()) == 3
    provider.papers = [normalize_work(WORK)]
    client.post(url + "/search")
    assert client.get(url + "/subtopics").json() == []  # single cluster, not named


def test_explanation_is_generated_then_cached(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper = client.get(url + "/papers").json()[0]
    assert paper["classificationExplanation"] is None

    first = client.post(f"{url}/papers/{paper['id']}/explanation")
    assert first.status_code == 200
    assert (
        first.json()["explanation"] == f"{paper['title']} fits Topic {paper['title'].split()[0]}."
    )
    assert len(llm.explain_calls) == 1
    assert (
        client.get(url + "/papers").json()[0]["classificationExplanation"]
        == first.json()["explanation"]
    )

    second = client.post(f"{url}/papers/{paper['id']}/explanation")
    assert second.json() == first.json()
    assert len(llm.explain_calls) == 1  # served from cache, no second LLM call


def test_explanation_requires_a_named_subtopic(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = [normalize_work(WORK)]  # single cluster, no subtopic
    client.post(url + "/search")
    paper_id = client.get(url + "/papers").json()[0]["id"]
    assert client.post(f"{url}/papers/{paper_id}/explanation").status_code == 422
    assert llm.explain_calls == []


def test_explanation_unknown_paper_is_404(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    assert client.post(f"{url}/papers/{uuid4()}/explanation").status_code == 404


def test_explanation_llm_failure_propagates(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper_id = client.get(url + "/papers").json()[0]["id"]
    llm.explain_error = ProviderError("LLM_RATE_LIMITED")
    assert client.post(f"{url}/papers/{paper_id}/explanation").status_code == 503


def test_new_search_clears_stored_explanations(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper_id = client.get(url + "/papers").json()[0]["id"]
    client.post(f"{url}/papers/{paper_id}/explanation")
    client.post(url + "/search")
    assert all(p["classificationExplanation"] is None for p in client.get(url + "/papers").json())


def test_search_reports_pipeline_stages(search_client_named, monkeypatch):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    seen = []
    original = client.app.state.search._set_stage

    def spy(run_id, stage):
        seen.append(stage)
        return original(run_id, stage)

    monkeypatch.setattr(client.app.state.search, "_set_stage", spy)
    client.post(url + "/search")
    assert seen == ["ANALYZING", "EMBEDDING", "CLUSTERING", "NAMING"]
    assert client.get(url + "/searches").json()[0]["stage"] is None


def test_stage_is_retrieving_while_a_search_runs(search_client_named):
    client, *_, url = search_client_named
    project_id = UUID(client.get(url).json()["id"])
    run = client.app.state.search.start(project_id)
    assert run.stage == "RETRIEVING"
    assert client.get(url + "/searches").json()[0]["stage"] == "RETRIEVING"


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
        row.startedAt = datetime.now(UTC) - timedelta(minutes=5)
    history = client.get(url + "/searches").json()
    assert history[0]["errorCode"] == "INTERRUPTED"
    assert client.get(url).json()["status"] == "FAILED"
    assert client.post(url + "/search").status_code == 200
    from researchpilot.search_persistence import SearchConflict

    with pytest.raises(SearchConflict):
        client.app.state.search.finish(run, error=ProviderError("INTERRUPTED"))
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
